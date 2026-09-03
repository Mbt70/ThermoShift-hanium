import sys
from pathlib import Path

import streamlit as st

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from shared.api_client import (
    ApiError, api_delete, api_get, api_patch, api_post, set_access_token,
)

_CURRENT_USER_KEY = "_ts_current_user"  # {"user_id": int, "name": str, "email": str}
_PENDING_LOGIN_KEY = "_ts_pending_login_result"


def register_user(name: str, email: str, password: str) -> None:
    api_post("/auth/register", json={"name": name, "email": email, "password": password})


def is_registered(email: str) -> bool:
    result = api_get("/auth/exists", params={"email": email})
    return bool(result and result.get("exists"))


def check_credentials(email: str, password: str) -> bool:
    try:
        user = api_post("/auth/login", json={"email": email, "password": password})
    except ApiError:
        return False
    # Stashed for set_current_user (called right after, in the same login
    # flow) so it doesn't need a second /auth/login round trip just to learn
    # the user_id.
    st.session_state[_PENDING_LOGIN_KEY] = user
    return True


def start_demo_session() -> bool:
    """DB에 지정된 조회 전용 시연 계정으로 세션을 시작한다."""
    try:
        user = api_post("/auth/demo")
    except ApiError:
        return False
    st.session_state[_PENDING_LOGIN_KEY] = user
    set_current_user(user["email"])
    return is_logged_in()


def set_current_user(email: str) -> None:
    pending = st.session_state.pop(_PENDING_LOGIN_KEY, None)
    if pending and pending["email"] == email:
        st.session_state[_CURRENT_USER_KEY] = pending
        set_access_token(pending.get("access_token"))


def is_logged_in() -> bool:
    return _CURRENT_USER_KEY in st.session_state


def current_user_name() -> str:
    user = st.session_state.get(_CURRENT_USER_KEY)
    return user["name"] if user else "Thermo"


def current_user_email() -> str | None:
    user = st.session_state.get(_CURRENT_USER_KEY)
    return user["email"] if user else None


def current_user_id() -> int | None:
    user = st.session_state.get(_CURRENT_USER_KEY)
    return user["user_id"] if user else None


def update_user_name(email: str, name: str) -> None:
    user_id = current_user_id()
    if user_id is None:
        return
    updated = api_patch(f"/auth/{user_id}/name", json={"name": name})
    if updated and st.session_state.get(_CURRENT_USER_KEY, {}).get("email") == email:
        st.session_state[_CURRENT_USER_KEY] = updated


def update_password(email: str, new_password: str) -> None:
    user_id = current_user_id()
    if user_id is None:
        return
    api_patch(f"/auth/{user_id}/password", json={"password": new_password})


def delete_user(email: str) -> None:
    user_id = current_user_id()
    if user_id is None:
        return
    api_delete(f"/auth/{user_id}")


def log_out() -> None:
    st.session_state.pop(_CURRENT_USER_KEY, None)
    set_access_token(None)
