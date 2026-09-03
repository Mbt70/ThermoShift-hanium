"""서명 세션과 자원 소유권 검증.

브라우저의 로그인 화면은 보안 경계가 아니다. 모든 비공개 API는 이 모듈이
검증한 Bearer token과 DB 소유권을 함께 확인한다.
"""

import logging
import os
import secrets

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from api.db import get_conn

logger = logging.getLogger(__name__)
TOKEN_MAX_AGE_SEC = int(os.getenv("AUTH_TOKEN_MAX_AGE_SEC", "86400"))
_secret = os.getenv("AUTH_SECRET")
if not _secret:
    _secret = secrets.token_urlsafe(32)
    logger.warning(
        "AUTH_SECRET가 없어 이번 프로세스에서만 유효한 임시 키를 사용합니다. "
        "배포 환경에서는 AUTH_SECRET를 반드시 설정하세요."
    )
_serializer = URLSafeTimedSerializer(_secret, salt="thermoshift-session-v1")
_bearer = HTTPBearer(auto_error=False)


def create_access_token(user_id: int, scope: str = "user") -> str:
    if scope not in {"user", "demo"}:
        raise ValueError("unsupported token scope")
    return _serializer.dumps({"user_id": int(user_id), "scope": scope})


def get_current_user_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> int:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="authentication required")
    try:
        payload = _serializer.loads(
            credentials.credentials, max_age=TOKEN_MAX_AGE_SEC
        )
        user_id = int(payload["user_id"])
        scope = str(payload.get("scope", "user"))
    except SignatureExpired:
        raise HTTPException(status_code=401, detail="session expired") from None
    except (BadSignature, KeyError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="invalid session") from None

    # 비로그인 시연 세션은 대시보드 조회만 가능하다. 버튼 하나로 실제 장치
    # 제어나 사용자 데이터 변경까지 허용되는 인증 우회가 되면 안 된다.
    if scope == "demo" and request.method not in {"GET", "HEAD", "OPTIONS"}:
        raise HTTPException(status_code=403, detail="demo session is read-only")
    if scope not in {"user", "demo"}:
        raise HTTPException(status_code=401, detail="invalid session scope")

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM users WHERE user_id = %s AND deleted_at IS NULL",
            (user_id,),
        )
        if cur.fetchone() is None:
            raise HTTPException(status_code=401, detail="inactive user")
    return user_id


def require_self(user_id: int, current_user_id: int) -> None:
    if user_id != current_user_id:
        raise HTTPException(status_code=403, detail="not allowed for this user")


def require_room_owner(room_id: int, current_user_id: int) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM rooms WHERE room_id = %s AND owner_user_id = %s",
            (room_id, current_user_id),
        )
        if cur.fetchone() is None:
            # 다른 사용자의 자원 존재 여부도 노출하지 않는다.
            raise HTTPException(status_code=404, detail="room not found")


def require_owned_resource(
    table: str, id_column: str, resource_id: int, current_user_id: int,
) -> None:
    allowed = {
        ("devices", "device_id"),
        ("schedules", "schedule_id"),
        ("hvac_commands", "command_id"),
        ("event_logs", "event_id"),
        ("control_decisions", "decision_id"),
    }
    if (table, id_column) not in allowed:
        raise ValueError("unsupported ownership lookup")
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT 1 FROM {table} x JOIN rooms r ON r.room_id = x.room_id "
            f"WHERE x.{id_column} = %s AND r.owner_user_id = %s",
            (resource_id, current_user_id),
        )
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="resource not found")
