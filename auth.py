import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, Header, HTTPException
from passlib.context import CryptContext
import jwt

# SECURITY: no hardcoded fallback. The app must fail to start rather than
# silently run with a secret that's sitting in source control / chat history.
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY is not set. Set it as an environment variable "
        "(e.g. in Render's dashboard) before starting the app. "
        "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
    )

ALGORITHM = "HS256"

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# Role hierarchy: higher number = more privilege. Used by require_role() so
# a single dependency can express "this endpoint needs at least manager".
ROLE_RANK = {
    "customer": 0,
    "employee": 1,
    "manager": 2,
    "owner": 3,
}


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return pwd_context.verify(password, hashed_password)


def create_token(user_id: int, role: str):
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": datetime.utcnow() + timedelta(days=7),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("sub") is not None:
            payload["sub"] = int(payload["sub"])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    except Exception:
        return None


def get_current_user(authorization: str | None = Header(None)) -> dict:
    """Single source of truth for 'who is calling this endpoint'.

    Both app.py and customer_api.py depend on this so there is exactly one
    place that validates tokens and loads the user row.
    """
    # Imported lazily to avoid a circular import (database.py imports auth.py).
    from database import get_user_by_id

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = authorization.replace("Bearer ", "", 1)
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = get_user_by_id(payload.get("sub"))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def require_role(minimum_role: str):
    """FastAPI dependency factory for role-based access control.

    Usage:
        @router.post("/admin-only")
        def do_thing(current_user: dict = Depends(require_role("manager"))):
            ...

    Any role ranked >= minimum_role in ROLE_RANK is allowed. Unknown roles
    are rejected rather than silently allowed.
    """
    required_rank = ROLE_RANK.get(minimum_role)
    if required_rank is None:
        raise ValueError(f"Unknown role in require_role(): {minimum_role}")

    def dependency(current_user: dict = Depends(get_current_user)) -> dict:
        user_rank = ROLE_RANK.get(current_user.get("role"), -1)
        if user_rank < required_rank:
            raise HTTPException(
                status_code=403,
                detail=f"This action requires '{minimum_role}' role or higher.",
            )
        return current_user

    return dependency