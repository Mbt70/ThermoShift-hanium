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


def _password_matches(password: str, stored_hash: str) -> bool:
    """저장된 해시와 대조한다. 해시를 읽을 수 없으면 False.

    bcrypt.checkpw 는 bcrypt 형식이 아닌 문자열을 받으면 False 를 돌려주는
    게 아니라 ValueError 를 던진다. 구 SQLite 에서 이관해 온 계정은
    pbkdf2_sha256$... 형식이라 여기서 예외가 나 로그인이 401 이 아니라
    500 으로 끝났다. 인증 실패는 인증 실패로 끝나야 한다 — 서버 오류로
    새면 "비밀번호가 틀렸다" 와 "시스템이 고장났다" 를 구분할 수 없고,
    깨진 해시 한 줄이 로그인 전체를 무너뜨린다.
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"),
                              stored_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


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
    if row is None or not _password_matches(body.password, row["password_hash"]):
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
