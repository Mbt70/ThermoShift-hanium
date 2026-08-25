"""세션 토큰 발급·검증.

API를 인터넷에 노출하면 URL을 아는 누구나 에어컨을 켤 수 있게 된다.
로그인한 사용자만 자기 공간을 읽고 제어할 수 있도록 토큰을 요구한다.

토큰은 서버 비밀키로 서명한 값이라 위조할 수 없고, 저장소가 필요 없다.
프론트(stlite)는 브라우저에서 돌지만 토큰은 그 사용자 본인의 것이므로
브라우저에 있어도 문제되지 않는다. (API 키와 다른 점)
"""

import base64
import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path
from typing import Optional

from fastapi import Depends, Header, HTTPException

from .db import DB_PATH, get_conn

TOKEN_TTL_SEC = int(os.environ.get("THERMOSHIFT_TOKEN_TTL_SEC", 7 * 24 * 3600))


def _load_secret() -> bytes:
    """서명 비밀키. 재시작해도 토큰이 살아 있도록 파일에 보존한다."""
    from_env = os.environ.get("THERMOSHIFT_SECRET_KEY")
    if from_env:
        return from_env.encode("utf-8")

    key_path = Path(DB_PATH).parent / "secret.key"
    if key_path.exists():
        return key_path.read_bytes().strip()

    key_path.parent.mkdir(parents=True, exist_ok=True)
    generated = secrets.token_hex(32).encode("ascii")
    key_path.write_bytes(generated)
    # 다른 사용자가 읽으면 토큰을 위조할 수 있다.
    key_path.chmod(0o600)
    return generated


_SECRET = _load_secret()


def _sign(payload: str) -> str:
    digest = hmac.new(_SECRET, payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def issue_token(email: str) -> str:
    payload = f"{email}|{int(time.time())}"
    encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{encoded}.{_sign(payload)}"


def verify_token(token: str) -> Optional[str]:
    """유효하면 이메일, 아니면 None."""
    encoded, _, signature = token.partition(".")
    if not encoded or not signature:
        return None
    try:
        padding = "=" * (-len(encoded) % 4)
        payload = base64.urlsafe_b64decode(encoded + padding).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None

    # 위조 판별은 상수 시간 비교로 한다.
    if not hmac.compare_digest(_sign(payload), signature):
        return None

    email, _, issued_at = payload.rpartition("|")
    try:
        age = time.time() - int(issued_at)
    except ValueError:
        return None
    if age > TOKEN_TTL_SEC:
        return None
    return email


def current_user(authorization: Optional[str] = Header(default=None)) -> str:
    """인증 필수 엔드포인트용 의존성."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    email = verify_token(authorization[7:].strip())
    if email is None:
        raise HTTPException(status_code=401, detail="로그인이 만료되었습니다. 다시 로그인해 주세요.")
    return email


def require_room_access(room_id: str, email: str) -> None:
    """남의 공간을 읽거나 제어하지 못하게 막는다."""
    with get_conn() as conn:
        row = conn.execute("SELECT owner_email FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="공간을 찾을 수 없습니다.")
    if row["owner_email"] and row["owner_email"] != email:
        # 존재 여부를 흘리지 않도록 404 로 통일한다.
        raise HTTPException(status_code=404, detail="공간을 찾을 수 없습니다.")


def room_guard(room_id: str, email: str = Depends(current_user)) -> str:
    """room_id 쿼리/경로 파라미터를 쓰는 엔드포인트용 의존성."""
    require_room_access(room_id, email)
    return email
