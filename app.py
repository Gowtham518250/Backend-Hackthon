import hashlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

from auth import get_current_user
from customer_api import router as customer_router
from database import get_file_ids_for_customer, save_file_record, user_has_access, init_db
from index import (
    RetrievalError,
    SUPPORTED_EXTENSIONS,
    file_exists,
    register_file,
    search_all_files,
)

load_dotenv()
logger = logging.getLogger("deepfind.app")

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "AI_AGENT"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

router = APIRouter(prefix="/rag", tags=["DeepFind RAG"])


PDF_PROMPT_TEMPLATE = """
You are DeepFind AI for PDF and document analysis.

Answer the question using ONLY the retrieved document evidence below.

Rules:
- Use exact facts from the provided text only.
- If a page number is present, cite it in the answer when relevant.
- Never invent values, pages, sections, or file names.
- If evidence is insufficient, reply exactly:
  "Answer not found in the available documents."
- Keep the answer concise but complete.

Evidence:
{context}

Question:
{question}

Answer:
"""

EXCEL_SQL_PROMPT_TEMPLATE = """
You are DeepFind AI for spreadsheet analysis.

The user asks a question about structured table data. Use the spreadsheet rows below as the only source of truth.

Important rules:
- Generate a valid SQLite SQL query that answers the question.
- Use only the column names and rows shown below.
- Every row includes a "uploaded_by" column naming who uploaded that file, and
  a "source_file" column naming which file it came from — use these if the
  question asks about a specific person or file (e.g. "what did Priya upload").
- Return the answer from the query result, not from assumptions.
- If the data does not support the question, answer exactly:
  "Answer not found in the available spreadsheet data."
- Keep the final answer short, clear, and factual.

Table schema:
{schema}

Rows:
{rows}

Question:
{question}

SQL:
"""

PDF_PROMPT = PromptTemplate(
    template=PDF_PROMPT_TEMPLATE,
    input_variables=["context", "question"],
)

EXCEL_SQL_PROMPT = PromptTemplate(
    template=EXCEL_SQL_PROMPT_TEMPLATE,
    input_variables=["schema", "rows", "question"],
)


def get_llm() -> ChatGoogleGenerativeAI:
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API_KEY is not configured",
        )

    return ChatGoogleGenerativeAI(
        # NOTE: this previously defaulted to "gemini-3.6-flash", which
        # doesn't match the model name used in llm_setup.py
        # ("gemini-2.0-flash") and isn't a valid Gemini model — any call
        # relying on this default would fail. Aligned the default here.
        model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
        temperature=0,
        google_api_key=api_key,
    )


def build_context(docs):
    blocks = []

    for i, doc in enumerate(docs, start=1):
        metadata = doc.metadata or {}

        file_name = metadata.get(
            "file_name",
            metadata.get("source", "unknown"),
        )

        location = [file_name]

        if metadata.get("file_type"):
            location.append(str(metadata["file_type"]).upper())

        if metadata.get("page") is not None:
            location.append(f"Page {metadata['page']}")

        if metadata.get("sheet"):
            location.append(f"Sheet {metadata['sheet']}")

        if metadata.get("row") is not None:
            location.append(f"Row {metadata['row']}")

        if metadata.get("section"):
            location.append(str(metadata["section"]))

        if metadata.get("uploaded_by"):
            location.append(f"Uploaded by {metadata['uploaded_by']}")

        blocks.append(
            f"[SOURCE {i}]\n"
            f"Location: {' · '.join(location)}\n"
            f"Content:\n{doc.page_content}"
        )

    return "\n\n".join(blocks)


def build_sources(docs):
    sources = []

    for doc in docs:
        metadata = doc.metadata or {}

        source = metadata.get(
            "file_name",
            metadata.get("source", "unknown"),
        )

        if metadata.get("page") is not None:
            source += f" · Page {metadata['page']}"

        if metadata.get("sheet"):
            source += f" · Sheet {metadata['sheet']}"

        if metadata.get("row") is not None:
            source += f" · Row {metadata['row']}"

        if source not in sources:
            sources.append(source)

    return sources


def build_result(doc, score=None):
    metadata = dict(doc.metadata or {})

    file_name = metadata.get(
        "file_name",
        metadata.get("source", "unknown"),
    )

    citation = file_name

    if metadata.get("page") is not None:
        citation += f" · Page {metadata['page']}"

    if metadata.get("sheet"):
        citation += f" · Sheet {metadata['sheet']}"

    if metadata.get("row") is not None:
        citation += f" · Row {metadata['row']}"

    reasons = ["semantic/keyword relevance"]

    if metadata.get("sheet") or metadata.get("row") is not None:
        reasons.append("structured-data match")

    if metadata.get("ocr"):
        reasons.append("OCR content match")

    if metadata.get("chunk_type") == "structured_row":
        reasons.append("row-level metadata match")

    if metadata.get("invoice_number"):
        reasons.append("document identifier available")

    relevance = float(score) if score is not None else 0.0

    return {
        "chunk_id": metadata.get("chunk_id", ""),
        "file_id": metadata.get("file_id", ""),
        "file_name": file_name,
        "file_type": metadata.get("file_type", ""),
        "text": doc.page_content,
        "citation": citation,
        "metadata": metadata,
        "match_reasons": reasons[:4],
        "relevance_score": relevance,
        "relevance_percent": round(max(0.0, min(1.0, relevance)) * 100),
    }


def build_structured_rows(docs):
    grouped = {}

    for doc in docs:
        metadata = doc.metadata or {}
        row_data = metadata.get("row_data")
        if not row_data:
            continue

        file_id = metadata.get("file_id") or "unknown"
        file_name = metadata.get("file_name") or file_id
        entry = grouped.setdefault(file_id, {"file_name": file_name, "rows": [], "headers": set()})
        entry["rows"].append({str(key): value for key, value in row_data.items()})
        entry["headers"].update(str(key) for key in row_data.keys())

    return grouped


def execute_sql_answer(query: str, docs, owner_map: Optional[dict] = None):
    """Generate ONE SQL query with the LLM and execute it ONCE against a
    single in-memory table combining rows from every matching file the
    caller has access to (owner_map). Returns one unified answer rather
    than a separate answer per file — this is the 'run the same query
    across all files' flow.
    """
    owner_map = owner_map or {}
    grouped = build_structured_rows(docs)
    if not grouped:
        return None

    import sqlite3

    all_rows = []
    global_headers = set()

    for file_id, info in grouped.items():
        owner = owner_map.get(file_id, {})
        headers = sorted(info["headers"])
        for row in info["rows"]:
            normalized = {key: row.get(key, "") for key in headers}
            normalized["source_file"] = info["file_name"]
            # Attribution column — lets a question like "how much did
            # Priya bill last month" resolve directly in SQL instead of
            # needing a second lookup step.
            normalized["uploaded_by"] = owner.get("uploader_name", "unknown")
            all_rows.append(normalized)
            global_headers.update(normalized.keys())

    if not all_rows:
        return None

    sql_headers = sorted(global_headers)
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    create_columns = ", ".join(f'"{header}" TEXT' for header in sql_headers)
    cursor.execute(f"CREATE TABLE spreadsheet ({create_columns})")

    placeholders = ", ".join("?" for _ in sql_headers)
    for row in all_rows:
        values = [row.get(header, "") for header in sql_headers]
        cursor.execute(f"INSERT INTO spreadsheet VALUES ({placeholders})", values)

    schema = ", ".join(sql_headers)
    llm = get_llm()
    sql_prompt = EXCEL_SQL_PROMPT.format(
        schema=schema,
        rows=str(all_rows[:20]),
        question=query,
    )

    files_included = sorted({info["file_name"] for info in grouped.values()})

    try:
        sql_response = llm.invoke(sql_prompt)
        # Extract text from Gemini response - handle both structured and string formats
        content_str = str(sql_response.content).strip()
        
        # If content looks like it's still in array format with nested 'text' field
        if content_str.startswith("[{") and "'text':" in content_str:
            import ast
            import re
            try:
                # Try to parse as Python literal
                content_list = ast.literal_eval(content_str)
                if isinstance(content_list, list) and len(content_list) > 0:
                    if isinstance(content_list[0], dict) and 'text' in content_list[0]:
                        sql_text = content_list[0]['text']
                    else:
                        sql_text = str(content_list[0])
                else:
                    sql_text = content_str
            except (ValueError, SyntaxError):
                # Fallback: extract first SELECT...semicolon pattern
                match = re.search(r"SELECT.*?;", content_str, re.IGNORECASE | re.DOTALL)
                sql_text = match.group(0) if match else content_str
        else:
            sql_text = content_str
            
        sql_text = sql_text.replace("```sql", "").replace("```", "").strip()
        
        # Extract only the first SQL statement (before any newlines + non-SQL content)
        # Find the first complete SELECT statement ending with semicolon
        import re
        match = re.search(r"SELECT.*?;", sql_text, re.IGNORECASE | re.DOTALL)
        if match:
            sql_text = match.group(0)

        if "SELECT" not in sql_text.upper():
            raise ValueError(f"Model did not return a SQL query. Raw response: {sql_text[:200]!r}")

        result = cursor.execute(sql_text).fetchall()
        column_names = [description[0] for description in cursor.description] if cursor.description else sql_headers

        if not result:
            return {
                "answer": "Answer not found in the available spreadsheet data.",
                "sql": sql_text,
                "rows": [],
                "files_included": files_included,
            }

        row_dicts = [dict(zip(column_names, record)) for record in result]

        return {
            "answer": str(row_dicts[:20]),
            "sql": sql_text,
            "rows": row_dicts[:20],
            "files_included": files_included,
        }
    except Exception as exc:
        # Logged (not swallowed) so a bad API key, rate limit, or invalid
        # generated SQL is distinguishable from a genuinely empty result.
        logger.exception("execute_sql_answer failed for query=%r", query)
        return {
            "answer": "Answer not found in the available spreadsheet data.",
            "error": str(exc),
            "files_included": files_included,
        }
    finally:
        conn.close()


def answer_text_docs(query: str, docs, owner_map: Optional[dict] = None):
    """Generate ONE answer from a single LLM call whose context spans every
    matching text chunk across every file — the text-document counterpart
    to execute_sql_answer's single combined SQL query. Replaces the old
    per-file loop that made a separate LLM call per file and stitched the
    answers together with semicolons.
    """
    owner_map = owner_map or {}
    if not docs:
        return None

    # Stamp uploader attribution onto each doc's metadata (without mutating
    # the originals) so build_context can surface "Uploaded by X" per source.
    annotated = []
    files_included = set()
    for doc in docs:
        metadata = dict(doc.metadata or {})
        file_id = metadata.get("file_id")
        owner = owner_map.get(file_id, {})
        if owner.get("uploader_name"):
            metadata["uploaded_by"] = owner["uploader_name"]
        files_included.add(metadata.get("file_name") or metadata.get("source") or "unknown")
        annotated.append(Document(page_content=doc.page_content, metadata=metadata))

    llm = get_llm()
    try:
        message = llm.invoke(
            PDF_PROMPT.format(
                context=build_context(annotated),
                question=query,
            )
        )
    except Exception as exc:
        logger.exception("answer_text_docs LLM call failed for query=%r", query)
        return {
            "answer": "Answer not found in the available documents.",
            "error": str(exc),
            "files_included": sorted(files_included),
        }

    # Extract text from Gemini response
    content_str = str(message.content).strip()
    
    # If content looks like it's still in array format with nested 'text' field
    if content_str.startswith("[{") and "'text':" in content_str:
        import ast
        import re
        try:
            # Try to parse as Python literal
            content_list = ast.literal_eval(content_str)
            if isinstance(content_list, list) and len(content_list) > 0:
                if isinstance(content_list[0], dict) and 'text' in content_list[0]:
                    answer = content_list[0]['text']
                else:
                    answer = str(content_list[0])
            else:
                answer = content_str
        except (ValueError, SyntaxError):
            # Fallback: just use content_str as-is
            answer = content_str
    else:
        answer = content_str
    
    if not answer:
        answer = "Answer not found in the available documents."

    return {
        "answer": answer,
        "files_included": sorted(files_included),
    }


def answer_query(query: str, file_id: Optional[str], top_k: int, docs_override=None, owner_map: Optional[dict] = None):
    if docs_override is not None:
        docs = docs_override
    else:
        try:
            docs = search_all_files(query=query, top_k=top_k, file_id=file_id)
        except RetrievalError as exc:
            # Every candidate file failed during retrieval (e.g. embedding
            # model couldn't load) — this is a real failure, not "no match".
            logger.error("RetrievalError in answer_query: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

    if not docs:
        return {
            "query": query,
            "query_type": "search",
            "answer": "Answer not found in the available documents.",
            "answer_type": "insufficient_evidence",
            "sources": [],
            "results": [],
            "retrieved_chunks": 0,
            "insufficient_evidence": True,
        }

    text_docs = []
    structured_docs = []
    for doc in docs:
        metadata = doc.metadata or {}
        if metadata.get("row_data") is not None or metadata.get("sheet") is not None:
            structured_docs.append(doc)
        else:
            text_docs.append(doc)

    structured_result = execute_sql_answer(query, structured_docs, owner_map=owner_map) if structured_docs else None
    text_result = answer_text_docs(query, text_docs, owner_map=owner_map) if text_docs else None

    parts = []
    if text_result:
        parts.append(text_result["answer"])
    if structured_result:
        parts.append(structured_result["answer"])

    if not parts:
        answer = "Answer not found in the available documents."
        answer_type = "insufficient_evidence"
        query_type = "search"
    else:
        answer = " | ".join(parts)
        answer_type = "grounded_mixed_sources" if (text_result and structured_result) else "grounded"
        query_type = "mixed_sources" if (text_result and structured_result) else "search"

    return {
        "query": query,
        "query_type": query_type,
        "answer": answer,
        "answer_type": answer_type,
        "sources": build_sources(docs),
        "results": [
            build_result(
                doc,
                score=1.0 - (index * 0.08),
            )
            for index, doc in enumerate(docs)
        ],
        "retrieved_chunks": len(docs),
        "insufficient_evidence": not parts,
        "text_answer": text_result,
        "structured_answer": structured_result,
    }


async def _save_and_index(
    file: UploadFile,
    current_user: Optional[dict] = None,
    customer_id: Optional[int] = None,
):
    original_name = file.filename or "upload.bin"
    extension = Path(original_name).suffix.lower().lstrip(".")

    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: .{extension or 'unknown'}",
        )

    file_bytes = await file.read()

    if not file_bytes:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty.",
        )

    file_id = hashlib.sha256(file_bytes).hexdigest()[:32]

    already_indexed = file_exists(file_id)

    tmp_path = None
    metadata = None
    if not already_indexed:
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{extension or 'bin'}") as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name

            metadata = register_file(
                file_path=tmp_path,
                file_id=file_id,
                original_name=original_name,
            )
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    # This is the fix for the #1 cause of "always answer not found": a file
    # indexed via /rag/upload used to be invisible to /customer/{id}/ask
    # because it was never written to the `files` table. If the caller is
    # authenticated and gives us a customer_id they actually have access
    # to, link it here so both query paths see the same data.
    if customer_id is not None and current_user is not None:
        if not user_has_access(current_user["id"], customer_id):
            raise HTTPException(
                status_code=403,
                detail="You do not have access to this customer organization.",
            )
        save_file_record(
            file_id=file_id,
            customer_id=customer_id,
            user_id=current_user["id"],
            original_name=original_name,
            storage_path=f"db://{file_id}",
            file_type=extension if extension else "file",
            status="uploaded",
        )

    if already_indexed:
        return {
            "file_name": original_name,
            "status": "already_indexed",
            "file_id": file_id,
            "file_type": extension,
            "customer_id": customer_id,
            "message": "File was already indexed.",
        }

    return {
        "file_name": original_name,
        "status": "ready",
        "file_id": file_id,
        "file_type": metadata["file_type"],
        "chunks": metadata["chunks"],
        "customer_id": customer_id,
        "saved_path": "db://" + file_id,
        "message": "File indexed successfully.",
    }


@router.post("/upload")
async def upload_one_file(
    file: UploadFile = File(
        ...,
        description="Select one PDF, DOCX, XLSX, CSV, or image file.",
    ),
    query: str = Form(
        default="",
        description="Optional question to ask immediately after indexing.",
    ),
    customer_id: Optional[int] = Form(
        default=None,
        description="Link this file to a customer org so /customer/{id}/ask can see it. "
                    "Omit only for one-off, non-customer-scoped testing.",
    ),
    current_user: dict = Depends(get_current_user),
):
    """
    Swagger-friendly single-file endpoint:
    a real file picker + a visible question text box.
    """
    start = time.perf_counter()

    try:
        result = await _save_and_index(file, current_user=current_user, customer_id=customer_id)

        response = {
            "total_files": 1,
            "successful": 1,
            "failed": 0,
            "files": [result],
        }

        if query.strip():
            response["search"] = answer_query(
                query=query.strip(),
                file_id=result.get("file_id"),
                top_k=8,
            )

        response["execution_time"] = round(
            time.perf_counter() - start,
            4,
        )

        return response

    except HTTPException:
        raise
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "total_files": 1,
                "successful": 0,
                "failed": 1,
                "files": [
                    {
                        "file_name": file.filename or "unknown",
                        "status": "failed",
                        "error": str(exc),
                    }
                ],
                "message": "Upload failed",
            },
        )


@router.post("/upload-many")
async def upload_many_files(
    files: list[UploadFile] = File(
        ...,
        description="Select multiple documents for Flutter/folder upload.",
    ),
    customer_id: Optional[int] = Form(
        default=None,
        description="Link these files to a customer org so /customer/{id}/ask can see them.",
    ),
    current_user: dict = Depends(get_current_user),
):
    """Multi-file endpoint used by the Flutter client."""
    start = time.perf_counter()

    if not files:
        raise HTTPException(
            status_code=400,
            detail="At least one file is required.",
        )

    results = []

    for file in files:
        try:
            results.append(await _save_and_index(file, current_user=current_user, customer_id=customer_id))
        except Exception as exc:
            results.append({
                "file_name": file.filename or "unknown",
                "status": "failed",
                "error": str(exc),
            })

    successful = sum(
        1
        for item in results
        if item.get("status") in {"ready", "already_indexed"}
    )

    failed = sum(
        1
        for item in results
        if item.get("status") == "failed"
    )

    return {
        "total_files": len(files),
        "successful": successful,
        "failed": failed,
        "files": results,
        "execution_time": round(
            time.perf_counter() - start,
            4,
        ),
    }


@router.get("/search")
async def search(
    query: str,
    file_id: Optional[str] = None,
    top_k: int = 8,
    current_user: dict = Depends(get_current_user),
):
    if not query.strip():
        raise HTTPException(
            status_code=400,
            detail="Query is required",
        )

    top_k = max(1, min(top_k, 20))

    start = time.perf_counter()

    try:
        result = answer_query(
            query=query.strip(),
            file_id=file_id,
            top_k=top_k,
        )

        result["execution_time"] = round(
            time.perf_counter() - start,
            4,
        )

        return result

    except HTTPException:
        raise

    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "error": str(exc),
                "message": "Search failed",
            },
        )


app = FastAPI(
    title="DeepFind AI",
    description="Multimodal multilingual intelligent file search",
    version="1.0.0",
)


@app.on_event("startup")
def startup_event():
    init_db()


app.include_router(router)
app.include_router(customer_router)


@app.get("/")
def root():
    return {
        "service": "DeepFind AI",
        "status": "running",
        "docs": "/docs",
        "upload_endpoint": "/rag/upload",
        "multi_upload_endpoint": "/rag/upload-many",
        "search_endpoint": "/rag/search",
    }


@app.get("/health")
def health():
    return {
        "service": "DeepFind AI",
        "status": "healthy",
    }