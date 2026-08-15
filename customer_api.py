import hashlib
import logging
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse

from auth import create_token, get_current_user, hash_password, require_role, verify_password
from database import (
    assign_user_to_customer,
    create_customer,
    create_user,
    get_file_ids_for_customer,
    get_file_owner_map,
    get_files_for_customer,
    get_user_by_email,
    save_chat,
    save_file_record,
    user_has_access,
    verify_customer_access_password,
)
from index import RetrievalError, search_all_files

logger = logging.getLogger("deepfind.customer_api")

router = APIRouter(prefix="/customer", tags=["customer"])
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "AI_AGENT"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
VALID_USER_ROLES = {"owner", "manager", "employee", "customer"}
READ_ONLY_ROLES = {"customer"}
WRITE_ALLOWED_ROLES = {"owner", "manager", "employee"}

# get_current_user and require_role now live in auth.py as the single
# source of truth for authentication/RBAC — app.py and customer_api.py
# both import the same dependency instead of keeping their own copies
# that could silently drift out of sync.


def require_org_password(customer_id: int, current_user: dict, organization_password: str | None):
    """Require a valid owner-set access password to enter a customer organization."""
    if not user_has_access(current_user["id"], customer_id):
        raise HTTPException(status_code=403, detail="No customer access")

    if not organization_password:
        raise HTTPException(status_code=403, detail="Organization access password is required")

    if not verify_customer_access_password(customer_id, organization_password):
        raise HTTPException(status_code=403, detail="Incorrect organization password")


@router.post("/login")
def login_user(email: str = Form(...), password: str = Form(...)):
    user = get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token(user["id"], user["role"])
    return {"token": token, "user": {"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"]}}


@router.post("/register")
def register_user(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
):
    if role not in VALID_USER_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")

    if get_user_by_email(email):
        raise HTTPException(status_code=400, detail="User already exists")

    user_id = create_user(name, email, hash_password(password), role)
    return {"id": user_id, "name": name, "email": email, "role": role}


@router.post("/create-customer")
def create_customer_api(
    name: str = Form(...),
    organization_password: str = Form(...),
    current_user: dict = Depends(require_role("owner")),
):
    if not organization_password or len(organization_password.strip()) < 4:
        raise HTTPException(status_code=400, detail="Organization password must be at least 4 characters")

    customer_id = create_customer(name, current_user["id"], organization_password)
    return {"customer_id": customer_id, "name": name, "message": "Organization created. Members must enter this password to access the org."}


@router.post("/{customer_id}/join")
def join_customer_org(
    customer_id: int,
    organization_password: str = Form(...),
    current_user: dict = Depends(get_current_user),
):
    if not user_has_access(current_user["id"], customer_id):
        raise HTTPException(status_code=403, detail="No customer access")

    if not verify_customer_access_password(customer_id, organization_password):
        raise HTTPException(status_code=403, detail="Incorrect organization password")

    return {
        "customer_id": customer_id,
        "message": "Organization access granted",
        "user": {"id": current_user["id"], "name": current_user["name"], "role": current_user["role"]},
    }


@router.post("/create-user")
def create_member_account(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    customer_id: int | None = Form(default=None),
    current_user: dict = Depends(require_role("owner")),
):
    if role not in {"manager", "employee", "customer"}:
        raise HTTPException(status_code=400, detail="Invalid role")

    if get_user_by_email(email):
        raise HTTPException(status_code=400, detail="User already exists")

    user_id = create_user(name, email, hash_password(password), role)

    if customer_id is not None:
        assign_user_to_customer(user_id, customer_id, role)

    return {
        "id": user_id,
        "name": name,
        "email": email,
        "role": role,
        "customer_id": customer_id,
        "message": "User account created by owner",
    }


@router.post("/{customer_id}/assign-user")
def assign_user(
    customer_id: int,
    user_id: int = Form(...),
    role: str = Form(...),
    current_user: dict = Depends(require_role("owner")),
):
    if role not in {"manager", "employee", "customer"}:
        raise HTTPException(status_code=400, detail="Invalid role")

    assign_user_to_customer(user_id, customer_id, role)
    return {"message": "User assigned"}


@router.post("/{customer_id}/upload")
async def upload_customer_file(
    customer_id: int,
    file: UploadFile = File(...),
    organization_password: str = Form(...),
    current_user: dict = Depends(get_current_user),
):
    if current_user["role"] in READ_ONLY_ROLES:
        raise HTTPException(status_code=403, detail="Customer accounts cannot upload or modify files")

    if current_user["role"] not in WRITE_ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="You do not have file-write permission")

    require_org_password(customer_id, current_user, organization_password)

    original_name = file.filename or "uploaded_file"
    file_bytes = await file.read()
    file_id = hashlib.sha256(file_bytes).hexdigest()[:32]

    extension = Path(original_name).suffix.lower().lstrip(".")
    tmp_path = None
    metadata = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{extension or 'bin'}") as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        from index import register_file
        metadata = register_file(file_path=tmp_path, file_id=file_id, original_name=original_name)

        save_file_record(
            file_id=file_id,
            customer_id=customer_id,
            user_id=current_user["id"],
            original_name=original_name,
            storage_path=f"db://{file_id}",
            file_type=extension if extension else "file",
            status="uploaded",
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except (OSError, PermissionError) as e:
                # Windows may lock files temporarily; allow the OS to clean up
                logger.warning(f"Could not delete temp file {tmp_path}: {e}")

    return {
        "file_id": file_id,
        "customer_id": customer_id,
        "status": "uploaded",
        "chunks": metadata.get("chunks") if metadata else None,
        "file_type": metadata.get("file_type") if metadata else extension,
    }


@router.get("/{customer_id}/files")
def list_customer_files(
    customer_id: int,
    organization_password: str | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
):
    require_org_password(customer_id, current_user, organization_password)
    return {"files": get_files_for_customer(customer_id)}


@router.post("/{customer_id}/ask")
def ask_customer_question(
    customer_id: int,
    question: str = Form(...),
    organization_password: str = Form(...),
    current_user: dict = Depends(get_current_user),
):
    require_org_password(customer_id, current_user, organization_password)

    file_ids = get_file_ids_for_customer(customer_id)
    if not file_ids:
        # This is the #1 cause of "always answer not found": the customer
        # has no files linked in the `files` table, usually because the
        # file was uploaded through /rag/upload instead of
        # /customer/{customer_id}/upload. Say so explicitly instead of
        # returning a generic "not found".
        answer = (
            "No files are linked to this organization yet. "
            "Upload a document via /customer/{customer_id}/upload first."
        )
        save_chat(customer_id, current_user["id"], question, answer)
        return {"answer": answer, "customer_id": customer_id}

    customer_docs = []
    retrieval_errors = []
    for file_id in file_ids:
        try:
            customer_docs.extend(search_all_files(query=question, top_k=8, file_id=file_id))
        except Exception as exc:
            logger.exception("Retrieval failed for file_id=%s customer_id=%s", file_id, customer_id)
            retrieval_errors.append((file_id, str(exc)))

    if not customer_docs:
        if retrieval_errors and len(retrieval_errors) == len(file_ids):
            # Every file failed — this is a broken pipeline, not "no match".
            # Surface it as a real error so it doesn't look identical to a
            # genuinely empty result.
            raise HTTPException(
                status_code=500,
                detail=f"Retrieval failed for all {len(retrieval_errors)} file(s). "
                       f"First error: {retrieval_errors[0][1]}",
            )
        answer = "Answer not found in the available documents."
    else:
        from app import answer_query

        # Scoped strictly to this customer_id (see get_file_owner_map's
        # docstring) — this is what lets the LLM attribute results to
        # "who uploaded what" without leaking ownership info from other orgs.
        owner_map = get_file_owner_map(customer_id)

        try:
            result = answer_query(
                query=question,
                file_id=None,
                top_k=8,
                docs_override=customer_docs,
                owner_map=owner_map,
            )
        except HTTPException:
            raise
        except Exception as exc:
            # Retrieval succeeded (we have docs) but the LLM call itself
            # failed — bad GEMINI_API_KEY, rate limit, network error, etc.
            # This used to be an unhandled 500 with no useful message.
            logger.exception("answer_query failed for customer_id=%s", customer_id)
            raise HTTPException(status_code=502, detail=f"Answer generation failed: {exc}")
        answer = result.get("answer", "Answer not found in the available documents.")

    save_chat(customer_id, current_user["id"], question, answer)
    return {"answer": answer, "customer_id": customer_id}