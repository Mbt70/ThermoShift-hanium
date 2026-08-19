import base64
from pathlib import Path

import streamlit as st

from app.components.auth_store import (
    current_user_email,
    current_user_id,
    current_user_name,
    delete_user,
    is_logged_in,
    log_out,
    update_user_name,
)
from app.components.mobile_ui import apply_mobile_styles, bottom_tab_bar, page_header
from app.components.room_store import delete_room, list_rooms
from app.components.sensor_store import list_sensors, set_sensor_enabled

ICONS_DIR = Path(__file__).resolve().parents[1] / "assets" / "icons"

_PERSON_ICON = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
    'stroke-width="1.95" stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.5-7 8-7s8 3 8 7"/></svg>'
)
_MAIL_ICON = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
    'stroke-width="1.95" stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M4 7l8 6 8-6"/></svg>'
)
_LOCK_ICON = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
    'stroke-width="1.95" stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="4.5" y="10.5" width="15" height="10" rx="2"/><path d="M8 10.5V7a4 4 0 0 1 8 0v3.5"/></svg>'
)
_LOGOUT_ICON = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
    'stroke-width="1.95" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M9 20H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/></svg>'
)
_CHEVRON_ICON = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
    'stroke-width="1.95" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M9 6l6 6-6 6"/></svg>'
)
_SENSOR_ICON_FILES = {
    "env": "device_thermostat.svg",
    "pir": "sensors.svg",
    "ir": "settings_remote.svg",
    "plug": "plug.svg",
    "door": "door.svg",
}


def _icon_data_uri(file_name: str) -> str:
    encoded = base64.b64encode((ICONS_DIR / file_name).read_bytes()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _row_left(icon: str, label: str, *, extra_class: str = "") -> str:
    css_class = f"ts-settings-label-text {extra_class}".strip()
    return (
        '<div class="ts-settings-row-left">'
        f'<span class="ts-settings-icon-wrapper">{icon}</span>'
        f'<span class="{css_class}">{label}</span>'
        "</div>"
    )


@st.dialog("이름 변경")
def _edit_name_dialog(email: str, current_name: str) -> None:
    new_name = st.text_input(
        "이름", value=current_name, key="settings_name_input", label_visibility="collapsed"
    )
    if st.button("저장", key="settings_name_save", use_container_width=True):
        if new_name.strip():
            update_user_name(email, new_name.strip())
        st.rerun()


@st.dialog("공간을 삭제할까요?")
def _confirm_delete_room(room_id: str, room_name: str) -> None:
    st.markdown(
        f'<p class="ts-settings-dialog-desc">"{room_name}"을(를) 삭제하면 '
        "되돌릴 수 없어요.</p>",
        unsafe_allow_html=True,
    )
    keep_col, delete_col = st.columns(2, gap="small")
    with keep_col:
        if st.button("유지하기", key="settings_room_keep", use_container_width=True):
            st.rerun()
    with delete_col:
        if st.button(
            "삭제", key="settings_room_delete_confirm", use_container_width=True
        ):
            delete_room(room_id)
            st.rerun()


@st.dialog("로그아웃 하시겠어요?")
def _confirm_logout() -> None:
    st.markdown(
        '<p class="ts-settings-dialog-desc">'
        "로그아웃하면 다시 로그인해야 접속할 수 있어요.</p>",
        unsafe_allow_html=True,
    )
    keep_col, logout_col = st.columns(2, gap="small")
    with keep_col:
        if st.button("유지하기", key="settings_logout_keep", use_container_width=True):
            st.rerun()
    with logout_col:
        if st.button(
            "로그아웃", key="settings_logout_confirm", use_container_width=True
        ):
            log_out()
            st.switch_page("pages/login.py")


@st.dialog("탈퇴하시겠어요?")
def _confirm_delete_account(email: str) -> None:
    st.markdown(
        '<p class="ts-settings-dialog-desc">탈퇴하면 계정과 등록된 모든 정보가 '
        "삭제되고 되돌릴 수 없어요.</p>",
        unsafe_allow_html=True,
    )
    keep_col, delete_col = st.columns(2, gap="small")
    with keep_col:
        if st.button("유지하기", key="settings_account_keep", use_container_width=True):
            st.rerun()
    with delete_col:
        if st.button(
            "탈퇴", key="settings_account_delete_confirm", use_container_width=True
        ):
            delete_user(email)
            log_out()
            st.switch_page("pages/login.py")


apply_mobile_styles("settings")

if not is_logged_in():
    st.switch_page("pages/login.py")

user_email = current_user_email()
user_name = current_user_name()

page_header("설정", back_page="pages/home.py")

st.markdown('<p class="ts-settings-section-label">내 계정</p>', unsafe_allow_html=True)
with st.container(key="ts_account_card", border=True):
    name_left, name_right = st.columns([1, 1], vertical_alignment="center")
    with name_left:
        st.markdown(_row_left(_PERSON_ICON, "이름"), unsafe_allow_html=True)
    with name_right:
        st.markdown(
            f'<p class="ts-settings-row-value">{user_name}</p>', unsafe_allow_html=True
        )
        if st.button("", key="settings_edit_name", icon=":material/edit:"):
            _edit_name_dialog(user_email, user_name)

    email_left, email_right = st.columns([1, 1], vertical_alignment="center")
    with email_left:
        st.markdown(_row_left(_MAIL_ICON, "이메일"), unsafe_allow_html=True)
    with email_right:
        st.markdown(
            f'<p class="ts-settings-row-value">{user_email}</p>', unsafe_allow_html=True
        )

    with st.container(key="ts_settings_password_row"):
        password_clicked = st.button(
            "비밀번호 변경",
            key="settings_password_open",
            use_container_width=True,
        )
        pw_left, pw_right = st.columns([1, 1], vertical_alignment="center")
        with pw_left:
            st.markdown(_row_left(_LOCK_ICON, "비밀번호 변경"), unsafe_allow_html=True)
        with pw_right:
            st.markdown(
                f'<div class="ts-settings-chevron">{_CHEVRON_ICON}</div>',
                unsafe_allow_html=True,
            )
    if password_clicked:
        st.switch_page("pages/password.py")

    with st.container(key="ts_settings_logout_row"):
        logout_clicked = st.button(
            "로그아웃",
            key="settings_logout",
            use_container_width=True,
        )
        logout_left, logout_right = st.columns([1, 1], vertical_alignment="center")
        with logout_left:
            st.markdown(
                _row_left(_LOGOUT_ICON, "로그아웃", extra_class="ts-settings-logout"),
                unsafe_allow_html=True,
            )
        with logout_right:
            st.markdown("", unsafe_allow_html=True)
    if logout_clicked:
        _confirm_logout()

st.markdown('<p class="ts-settings-section-label">공간 설정</p>', unsafe_allow_html=True)
rooms = list_rooms(current_user_id())
room_icon_uri = _icon_data_uri("meeting_room.svg")
with st.container(key="ts_rooms_card", border=True):
    for room in rooms:
        room_left, room_right = st.columns([1, 1], vertical_alignment="center")
        with room_left:
            st.markdown(
                _row_left(f'<img src="{room_icon_uri}" alt="" />', room["name"]),
                unsafe_allow_html=True,
            )
        with room_right:
            if st.button(
                "", key=f"settings_room_iconedit_{room['id']}", icon=":material/edit:"
            ):
                st.session_state["_ts_selected_room"] = room["id"]
                st.session_state["_ts_room_settings_return"] = "pages/settings.py"
                st.switch_page("pages/room_settings.py")
            if st.button(
                "", key=f"settings_room_icondel_{room['id']}", icon=":material/delete:"
            ):
                _confirm_delete_room(room["id"], room["name"])

st.markdown('<p class="ts-settings-section-label">센서 설정</p>', unsafe_allow_html=True)
selected_room_id = st.session_state.get("_ts_selected_room") or (
    rooms[0]["id"] if rooms else None
)
with st.container(key="ts_sensor_card", border=True):
    sensors = list_sensors(selected_room_id) if selected_room_id else []
    for sensor in sensors:
        icon_uri = _icon_data_uri(_SENSOR_ICON_FILES.get(sensor["type"], "sensor.svg"))
        sensor_left, sensor_right = st.columns([1, 1], vertical_alignment="center")
        with sensor_left:
            st.markdown(
                _row_left(f'<img src="{icon_uri}" alt="" />', sensor["name"]),
                unsafe_allow_html=True,
            )
        with sensor_right:
            if sensor["type"] == "env":
                st.markdown(
                    '<div class="ts-settings-toggle-placeholder"></div>',
                    unsafe_allow_html=True,
                )
            else:
                enabled = st.toggle(
                    sensor["name"],
                    value=sensor["enabled"],
                    key=f"settings_sensor_{sensor['id']}",
                    label_visibility="collapsed",
                )
                if enabled != sensor["enabled"]:
                    set_sensor_enabled(sensor["id"], enabled)
                    st.rerun()

with st.container(key="ts_settings_delete_account_wrap"):
    bottom_logout_col, bottom_delete_col = st.columns([1, 1])
    with bottom_logout_col:
        bottom_logout_clicked = st.button("로그아웃", key="settings_bottom_logout")
    with bottom_delete_col:
        delete_account_clicked = st.button("회원탈퇴", key="settings_delete_account")
if bottom_logout_clicked:
    _confirm_logout()
if delete_account_clicked:
    _confirm_delete_account(user_email)

bottom_tab_bar(active="settings")
