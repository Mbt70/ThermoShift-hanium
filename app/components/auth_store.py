import json
from pathlib import Path

import streamlit as st

from . import backend

_STORE_PATH = Path(__file__).resolve().parents[2] / ".data" / "users.json"
_CURRENT_USER_KEY = "_ts_current_user"


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
    code = backend.status_code("GET", f"/api/auth/users/{email.strip().lower()}")
    if code is not None:
        return code == 200
    return email.strip().lower() in _load_users()


def check_credentials(email: str, password: str) -> bool:
    # 인증은 성공/실패를 구분해야 하므로 본문 대신 상태 코드를 본다.
    # (None 은 API 불통이라는 뜻이고, 이때만 로컬 저장소로 폴백한다.)
    code = backend.status_code(
        "POST",
        "/api/auth/login",
        json={"email": email.strip().lower(), "password": password},
    )
    if code is not None:
        return code == 200
    user = _load_users().get(email.strip().lower())
    return user is not None and user["password"] == password


def set_current_user(email: str) -> None:
    st.session_state[_CURRENT_USER_KEY] = email.strip().lower()


def is_logged_in() -> bool:
    return _CURRENT_USER_KEY in st.session_state


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
