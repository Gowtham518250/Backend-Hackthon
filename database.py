import json
import logging
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional, List, Dict, Any

from auth import hash_password

logger = logging.getLogger("deepfind.database")

# SECURITY: no hardcoded fallback here either — that Render Postgres
# password was previously committed in this file's default value.
# Rotate that password in the Render dashboard, then set DATABASE_URL
# as an environment variable only (never in code).
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Set it as an environment variable, e.g.:\n"
        "  postgresql://<user>:<password>@<host>/<dbname>?sslmode=require\n"
        "Never hardcode it as a default value in source."
    )


def get_connection():
    """Create a PostgreSQL connection with RealDictCursor for dict-like rows."""
    connect_kwargs = {"connect_timeout": 10}
    # Enforce TLS to the DB unless the URL itself already specifies sslmode.
    if "sslmode=" not in DATABASE_URL:
        connect_kwargs["sslmode"] = "require"

    conn = psycopg2.connect(DATABASE_URL, **connect_kwargs)
    conn.set_session(autocommit=False)
    return conn


def init_db() -> None:
    """Initialize the PostgreSQL database with all required tables."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        
        # Drop the old check constraint if it exists
        try:
            cursor.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
            conn.commit()
        except:
            conn.rollback()
        
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('owner', 'manager', 'employee', 'customer')),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS customers (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                owner_id INTEGER NOT NULL,
                access_password_hash TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )

        cursor.execute(
            "ALTER TABLE customers ADD COLUMN IF NOT EXISTS access_password_hash TEXT"
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS customer_users (
                id SERIAL PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('owner', 'manager', 'employee', 'customer')),
                assigned_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(customer_id, user_id),
                FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS files (
                id SERIAL PRIMARY KEY,
                file_id TEXT NOT NULL UNIQUE,
                customer_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                original_name TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                file_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'uploaded',
                uploaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                indexed_at TIMESTAMP,
                FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_history (
                id SERIAL PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                file_id TEXT,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_documents (
                id SERIAL PRIMARY KEY,
                file_id TEXT NOT NULL UNIQUE,
                file_name TEXT NOT NULL,
                file_type TEXT NOT NULL,
                content_json JSONB NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS spreadsheet_rows (
                id SERIAL PRIMARY KEY,
                file_id TEXT NOT NULL,
                file_name TEXT NOT NULL,
                sheet_name TEXT,
                headers JSONB NOT NULL,
                row_data JSONB NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(file_id, sheet_name, row_data)
            )
            """
        )

        conn.commit()
        print("✓ Database schema initialized successfully")
    except Exception as e:
        conn.rollback()
        print(f"✗ Database initialization error: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


def create_user(name: str, email: str, password_hash: str, role: str) -> int:
    """Create a new user and return their ID."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s) RETURNING id",
            (name, email, password_hash, role),
        )
        user_id = cursor.fetchone()[0]
        conn.commit()
        return user_id
    finally:
        cursor.close()
        conn.close()


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Fetch a user by email."""
    conn = get_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        cursor.close()
        conn.close()


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    """Fetch a user by ID."""
    conn = get_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        cursor.close()
        conn.close()


def create_customer(name: str, owner_id: int, access_password: str | None = None) -> int:
    """Create a new customer and store a separate org access password."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        password_hash = hash_password(access_password) if access_password else None
        cursor.execute(
            "INSERT INTO customers (name, owner_id, access_password_hash) VALUES (%s, %s, %s) RETURNING id",
            (name, owner_id, password_hash),
        )
        customer_id = cursor.fetchone()[0]

        cursor.execute(
            "INSERT INTO customer_users (customer_id, user_id, role) VALUES (%s, %s, %s)",
            (customer_id, owner_id, 'owner'),
        )
        conn.commit()
        return customer_id
    finally:
        cursor.close()
        conn.close()


def get_customer_by_id(customer_id: int) -> Optional[Dict[str, Any]]:
    """Fetch customer data by ID."""
    conn = get_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM customers WHERE id = %s", (customer_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        cursor.close()
        conn.close()


def verify_customer_access_password(customer_id: int, password: str) -> bool:
    """Verify the owner-set access password for a customer organization."""
    customer = get_customer_by_id(customer_id)
    if not customer or not customer.get("access_password_hash"):
        return False

    from auth import verify_password
    return verify_password(password, customer["access_password_hash"])


def assign_user_to_customer(user_id: int, customer_id: int, role: str) -> None:
    """Assign a user to a customer with a specific role."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO customer_users (customer_id, user_id, role) 
            VALUES (%s, %s, %s)
            ON CONFLICT (customer_id, user_id) DO UPDATE SET role = %s
            """,
            (customer_id, user_id, role, role),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def user_has_access(user_id: int, customer_id: int) -> bool:
    """Check if a user has access to a customer."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM customer_users WHERE user_id = %s AND customer_id = %s",
            (user_id, customer_id),
        )
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        conn.close()


def list_customers_for_user(user_id: int) -> List[Dict[str, Any]]:
    """List all customers accessible to a user."""
    conn = get_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT c.*
            FROM customers c
            JOIN customer_users cu ON cu.customer_id = c.id
            WHERE cu.user_id = %s
            ORDER BY c.id DESC
            """,
            (user_id,),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        cursor.close()
        conn.close()


def list_users_for_customer(customer_id: int) -> List[Dict[str, Any]]:
    """List all users assigned to a customer."""
    conn = get_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT u.*
            FROM users u
            JOIN customer_users cu ON cu.user_id = u.id
            WHERE cu.customer_id = %s
            ORDER BY u.id
            """,
            (customer_id,),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        cursor.close()
        conn.close()


def save_file_record(
    file_id: str,
    customer_id: int,
    user_id: int,
    original_name: str,
    storage_path: str,
    file_type: str,
    status: str = "uploaded"
) -> None:
    """Save or update a file record in the database."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO files (file_id, customer_id, user_id, original_name, storage_path, file_type, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (file_id) DO UPDATE SET
                customer_id = %s,
                user_id = %s,
                original_name = %s,
                storage_path = %s,
                file_type = %s,
                status = %s
            """,
            (file_id, customer_id, user_id, original_name, storage_path, file_type, status,
             customer_id, user_id, original_name, storage_path, file_type, status),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def get_files_for_customer(customer_id: int) -> List[Dict[str, Any]]:
    """Get all files for a customer."""
    conn = get_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT * FROM files WHERE customer_id = %s ORDER BY uploaded_at DESC",
            (customer_id,),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        cursor.close()
        conn.close()


def get_file_ids_for_customer(customer_id: int) -> List[str]:
    """Get all file IDs for a customer."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT file_id FROM files WHERE customer_id = %s",
            (customer_id,),
        )
        rows = cursor.fetchall()
        return [row[0] for row in rows]
    finally:
        cursor.close()
        conn.close()


def get_file_owner_map(customer_id: int) -> Dict[str, Dict[str, Any]]:
    """Map file_id -> uploader info, scoped to one customer org.

    Scoping by customer_id here (not just an arbitrary file_id list) is
    the security-relevant part: it guarantees the map can only ever
    contain files the caller has already been authorized to see via
    require_org_password, so this can't be used to leak ownership info
    about a file belonging to a different org.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT f.file_id, f.original_name, f.uploaded_at,
                   u.id AS uploader_id, u.name AS uploader_name, u.email AS uploader_email
            FROM files f
            JOIN users u ON u.id = f.user_id
            WHERE f.customer_id = %s
            """,
            (customer_id,),
        )
        rows = cursor.fetchall()
        return {
            row["file_id"]: {
                "uploader_id": row["uploader_id"],
                "uploader_name": row["uploader_name"],
                "uploader_email": row["uploader_email"],
                "original_name": row["original_name"],
                "uploaded_at": row["uploaded_at"].isoformat() if row["uploaded_at"] else None,
            }
            for row in rows
        }
    finally:
        cursor.close()
        conn.close()


def save_rag_documents(file_id: str, file_name: str, file_type: str, documents: List[Dict[str, Any]]) -> None:
    """Persist indexed document chunks in PostgreSQL instead of local files."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO rag_documents (file_id, file_name, file_type, content_json)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (file_id) DO UPDATE SET
                file_name = EXCLUDED.file_name,
                file_type = EXCLUDED.file_type,
                content_json = EXCLUDED.content_json,
                created_at = CURRENT_TIMESTAMP
            """,
            (file_id, file_name, file_type, json.dumps(documents)),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def save_spreadsheet_rows(file_id: str, file_name: str, sheet_name: str | None, headers: List[str], row_data: Dict[str, Any]) -> None:
    """Store each Excel/CSV row as a separate DB record for SQL-based analysis."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO spreadsheet_rows (file_id, file_name, sheet_name, headers, row_data)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (file_id, sheet_name, row_data) DO NOTHING
            """,
            (file_id, file_name, sheet_name, json.dumps(headers), json.dumps(row_data)),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def get_spreadsheet_rows(file_id: str | None = None) -> List[Dict[str, Any]]:
    """Load spreadsheet rows from PostgreSQL."""
    conn = get_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        if file_id:
            cursor.execute("SELECT * FROM spreadsheet_rows WHERE file_id = %s ORDER BY id", (file_id,))
        else:
            cursor.execute("SELECT * FROM spreadsheet_rows ORDER BY id")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        cursor.close()
        conn.close()


def get_rag_documents(file_id: str | None = None) -> List[Dict[str, Any]]:
    """Load all stored document chunks from PostgreSQL."""
    conn = get_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        if file_id:
            cursor.execute("SELECT * FROM rag_documents WHERE file_id = %s ORDER BY id", (file_id,))
        else:
            cursor.execute("SELECT * FROM rag_documents ORDER BY id")
        rows = cursor.fetchall()
        result = []
        for row in rows:
            payload = row["content_json"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            if isinstance(payload, list):
                result.extend(payload)
            elif payload is not None:
                result.append(payload)
        return result
    finally:
        cursor.close()
        conn.close()


def rag_file_exists(file_id: str) -> bool:
    """Check whether a file has indexed content stored in PostgreSQL."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM rag_documents WHERE file_id = %s LIMIT 1", (file_id,))
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        conn.close()


def save_chat(
    customer_id: int,
    user_id: int,
    question: str,
    answer: str,
    file_id: str | None = None
) -> None:
    """Save a chat message to the history."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO chat_history (customer_id, user_id, file_id, question, answer) VALUES (%s, %s, %s, %s, %s)",
            (customer_id, user_id, file_id, question, answer),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def get_chats_for_customer(customer_id: int) -> List[Dict[str, Any]]:
    """Get all chat messages for a customer."""
    conn = get_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT * FROM chat_history WHERE customer_id = %s ORDER BY created_at DESC",
            (customer_id,),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        cursor.close()
        conn.close()