import bcrypt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

from api.db import get_conn

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UpdateNameRequest(BaseModel):
    name: str


class UpdatePasswordRequest(BaseModel):
    password: str


def _user_out(row: dict) -> dict:
    return {"user_id": row["user_id"], "name": row["name"], "email": row["email"]}


@router.post("/register")
def register(body: RegisterRequest):
    """POST /auth/register

    Response: {"user_id": int, "name": str, "email": str}
    409 if the email is already registered (active account).
    """
    password_hash = bcrypt.hashpw(body.password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT user_id FROM users WHERE email = %s AND deleted_at IS NULL",
            (body.email,),
        )
        if cur.fetchone() is not None:
            raise HTTPException(status_code=409, detail="email already registered")
        cur.execute(
            """
            INSERT INTO users (name, email, password_hash)
            VALUES (%s, %s, %s)
            RETURNING user_id, name, email
            """,
            (body.name, body.email, password_hash),
        )
        row = cur.fetchone()
        conn.commit()
    return _user_out(row)


@router.post("/login")
def login(body: LoginRequest):
    """POST /auth/login

    Response: {"user_id": int, "name": str, "email": str}
    401 if the email/password combination doesn't match an active account.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT user_id, name, email, password_hash FROM users "
            "WHERE email = %s AND deleted_at IS NULL",
            (body.email,),
        )
        row = cur.fetchone()
    if row is None or not bcrypt.checkpw(
        body.password.encode("utf-8"), row["password_hash"].encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="invalid email or password")
    return _user_out(row)


@router.get("/exists")
def check_email_exists(email: EmailStr):
    """GET /auth/exists?email=... - Response: {"exists": bool}

    Registered before /auth/{user_id} below - without that ordering, this
    path would match the {user_id} route first and 422 on failing to parse
    "exists" as an int.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM users WHERE email = %s AND deleted_at IS NULL", (email,)
        )
        return {"exists": cur.fetchone() is not None}


@router.get("/{user_id}")
def get_user(user_id: int):
    """GET /auth/{user_id} - Response: {"user_id": int, "name": str, "email": str}"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT user_id, name, email FROM users WHERE user_id = %s AND deleted_at IS NULL",
            (user_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="user not found")
    return _user_out(row)


@router.patch("/{user_id}/name")
def update_name(user_id: int, body: UpdateNameRequest):
    """PATCH /auth/{user_id}/name - Response: {"user_id": int, "name": str, "email": str}"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET name = %s WHERE user_id = %s AND deleted_at IS NULL "
            "RETURNING user_id, name, email",
            (body.name, user_id),
        )
        row = cur.fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(status_code=404, detail="user not found")
    return _user_out(row)


@router.patch("/{user_id}/password")
def update_password(user_id: int, body: UpdatePasswordRequest):
    """PATCH /auth/{user_id}/password - Response: {"status": "ok"}"""
    password_hash = bcrypt.hashpw(body.password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET password_hash = %s WHERE user_id = %s AND deleted_at IS NULL "
            "RETURNING user_id",
            (password_hash, user_id),
        )
        row = cur.fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(status_code=404, detail="user not found")
    return {"status": "ok"}


@router.delete("/{user_id}")
def delete_user(user_id: int):
    """DELETE /auth/{user_id} - soft delete. Response: {"status": "ok"}"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET deleted_at = now() WHERE user_id = %s RETURNING user_id",
            (user_id,),
        )
        row = cur.fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(status_code=404, detail="user not found")
    return {"status": "ok"}
