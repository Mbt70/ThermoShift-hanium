import streamlit as st

_STORE_KEY = "_ts_registered_users"


def _users() -> dict[str, str]:
    if _STORE_KEY not in st.session_state:
        st.session_state[_STORE_KEY] = {}
    return st.session_state[_STORE_KEY]


def register_user(email: str, password: str) -> None:
    _users()[email.strip().lower()] = password


def is_registered(email: str) -> bool:
    return email.strip().lower() in _users()


def check_credentials(email: str, password: str) -> bool:
    return _users().get(email.strip().lower()) == password
