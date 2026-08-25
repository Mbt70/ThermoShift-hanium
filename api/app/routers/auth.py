"""사용자 계정 API."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import current_user, issue_token
from ..db import get_conn
from ..schemas import LoginRequest, RegisterRequest, UserUpdateRequest
from ..security import hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _normalize(email: str) -> str:
    return email.strip().lower()


@router.post("/register", status_code=201)
def register(req: RegisterRequest):
    email = _normalize(req.email)
    with get_conn() as conn:
        exists = conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone()
        if exists:
            raise HTTPException(status_code=409, detail="이미 가입된 이메일입니다.")
        conn.execute(
            "INSERT INTO users (email, name, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (email, req.name, hash_password(req.password), datetime.now(timezone.utc).isoformat()),
        )
    return {"email": email, "name": req.name}


@router.post("/login")
def login(req: LoginRequest):
    email = _normalize(req.email)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT name, password_hash FROM users WHERE email = ?", (email,)
        ).fetchone()
    if row is None or not verify_password(req.password, row["password_hash"]):
        # 계정 존재 여부를 노출하지 않기 위해 두 경우를 같은 메시지로 처리한다.
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")
    # 이후 요청은 이 토큰으로 인증한다. Authorization: Bearer <token>
    return {"email": email, "name": row["name"], "token": issue_token(email)}


def _assert_self(email: str, actor: str) -> str:
    """남의 계정을 건드리지 못하게 막는다."""
    normalized = _normalize(email)
    if normalized != actor:
        raise HTTPException(status_code=403, detail="본인 계정만 조회·수정할 수 있습니다.")
    return normalized


@router.get("/exists")
def user_exists(email: str = Query(...)):
    """가입 여부만 확인한다. 로그인·가입 화면이 토큰 없이 부르므로 공개다.

    이메일 존재 여부가 드러나지만, 가입 API 가 중복을 409 로 알려주는 이상
    같은 정보는 이미 노출된다. 프론트의 '가입되지 않은 이메일입니다' /
    '이미 가입된 이메일입니다' 안내를 유지하기 위한 최소 공개 엔드포인트다.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM users WHERE email = ?", (_normalize(email),)
        ).fetchone()
    return {"email": _normalize(email), "exists": row is not None}


@router.get("/users/{email}")
def get_user(email: str, actor: str = Depends(current_user)):
    _assert_self(email, actor)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT email, name, created_at FROM users WHERE email = ?", (_normalize(email),)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    return dict(row)


@router.patch("/users/{email}")
def update_user(email: str, req: UserUpdateRequest, actor: str = Depends(current_user)):
    email = _assert_self(email, actor)
    updates: list[str] = []
    params: list = []
    if req.name is not None:
        updates.append("name = ?")
        params.append(req.name)
    if req.password is not None:
        updates.append("password_hash = ?")
        params.append(hash_password(req.password))
    if not updates:
        raise HTTPException(status_code=400, detail="변경할 항목이 없습니다.")

    params.append(email)
    with get_conn() as conn:
        cur = conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE email = ?", params)
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    return {"email": email, "updated": True}


@router.delete("/users/{email}", status_code=204)
def delete_user(email: str, actor: str = Depends(current_user)):
    email = _assert_self(email, actor)
    with get_conn() as conn:
        conn.execute("DELETE FROM users WHERE email = ?", (email,))
    return None
