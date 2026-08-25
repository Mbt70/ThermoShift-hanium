import json
from pathlib import Path

import streamlit as st

from . import backend

_STORE_PATH = Path(__file__).resolve().parents[2] / ".data" / "users.json"
_CURRENT_USER_KEY = "_ts_current_user"
_TOKEN_KEY = "_ts_session_token"
_VERIFIED_KEY = "_ts_token_verified"


def _load_users() -> dict[str, dict[str, str]]:
    if not _STORE_PATH.exists():
        return {}
    return json.loads(_STORE_PATH.read_text(encoding="utf-8"))


def _save_users(users: dict[str, dict[str, str]]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(
        json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def register_user(name: str, email: str, password: str) -> None:
    code = backend.status_code(
        "POST",
        "/api/auth/register",
        json={"name": name, "email": email.strip().lower(), "password": password},
    )
    if code is not None:
        return

    users = _load_users()
    users[email.strip().lower()] = {"name": name, "password": password}
    _save_users(users)


def is_registered(email: str) -> bool:
    """가입 여부. 로그인 화면이 토큰을 갖기 전에 부르므로 공개 엔드포인트를 쓴다.

    /api/auth/users/{email} 는 인증이 필요해 여기서 쓸 수 없다.
    (썼더니 로그인 전에는 항상 401 → '가입되지 않은 이메일' 로 보였다)
    """
    result = backend.get("/api/auth/exists", {"email": email.strip().lower()})
    if result is not None:
        return bool(result.get("exists"))
    return email.strip().lower() in _load_users()


def check_credentials(email: str, password: str) -> bool:
    """로그인. 성공하면 세션 토큰을 받아 보관한다.

    None(연결 실패) 일 때만 로컬 저장소로 폴백한다. 401 은 폴백하지 않는다.
    """
    result = backend.send(
        "POST",
        "/api/auth/login",
        json={"email": email.strip().lower(), "password": password},
    )
    if result is not None:
        status, data = result
        if status == 200 and data:
            _store_token(data.get("token"))
            return True
        return False

    user = _load_users().get(email.strip().lower())
    return user is not None and user["password"] == password


def _store_token(token: str | None) -> None:
    """토큰은 세션에 둔다.

    모듈 전역에 두면 서버 렌더링 Streamlit 에서 여러 사용자가 한 프로세스를
    공유할 때 서로의 토큰을 쓰게 된다.
    """
    backend.clear_unauthorized()
    st.session_state[_TOKEN_KEY] = token
    st.session_state[_VERIFIED_KEY] = bool(token)
    backend.set_token(token)


def sync_token() -> None:
    """rerun 마다 세션의 토큰을 클라이언트에 다시 실어 준다."""
    backend.set_token(st.session_state.get(_TOKEN_KEY))


def set_current_user(email: str) -> None:
    st.session_state[_CURRENT_USER_KEY] = email.strip().lower()


def is_logged_in() -> bool:
    """로그인 여부. 모든 페이지가 가장 먼저 부르므로 토큰 관리 지점으로 쓴다."""
    sync_token()

    if backend.unauthorized_seen():
        # 직전 요청이 401이었다. 목데이터로 조용히 폴백하면 사용자가 가짜
        # 수치를 실제 값으로 오해하므로, 로그아웃시켜 재로그인을 받는다.
        backend.clear_unauthorized()
        log_out()
        return False

    email = st.session_state.get(_CURRENT_USER_KEY)
    if email is None:
        return False

    # 토큰이 이미 만료된 채로 앱을 열면, 위 검사는 첫 요청이 나간 뒤에야
    # 걸린다. 그 한 번의 렌더에서 목데이터가 보이는 것을 막기 위해
    # 세션당 딱 한 번 토큰을 확인한다.
    if backend.api_enabled() and not st.session_state.get(_VERIFIED_KEY):
        if backend.get(f"/api/auth/users/{email}") is None and backend.unauthorized_seen():
            backend.clear_unauthorized()
            log_out()
            return False
        st.session_state[_VERIFIED_KEY] = True

    return True


def current_user_name() -> str:
    email = st.session_state.get(_CURRENT_USER_KEY)
    if not email:
        return "Thermo"
    remote = backend.get(f"/api/auth/users/{email}")
    if remote is not None:
        return remote.get("name") or "Thermo"
    user = _load_users().get(email)
    return user["name"] if user else "Thermo"


def current_user_email() -> str | None:
    return st.session_state.get(_CURRENT_USER_KEY)


def update_user_name(email: str, name: str) -> None:
    if backend.patch(f"/api/auth/users/{email}", {"name": name}) is not None:
        return

    users = _load_users()
    user = users.get(email)
    if user is None:
        return
    user["name"] = name
    _save_users(users)


def update_password(email: str, new_password: str) -> None:
    if backend.patch(f"/api/auth/users/{email}", {"password": new_password}) is not None:
        return

    users = _load_users()
    user = users.get(email)
    if user is None:
        return
    user["password"] = new_password
    _save_users(users)


def delete_user(email: str) -> None:
    if backend.delete(f"/api/auth/users/{email}") is not None:
        return
    users = _load_users()
    users.pop(email, None)
    _save_users(users)


def log_out() -> None:
    st.session_state.pop(_CURRENT_USER_KEY, None)
    st.session_state.pop(_TOKEN_KEY, None)
    st.session_state.pop(_VERIFIED_KEY, None)
    backend.set_token(None)
