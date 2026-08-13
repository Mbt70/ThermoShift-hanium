import streamlit as st

from app.components.auth_store import is_logged_in
from app.components.control_log_store import get_log
from app.components.inquiry_store import ADMIN_PHONE, submit_inquiry
from app.components.mobile_ui import apply_mobile_styles, page_header
from app.components.room_store import get_room

_WARNING_ICON = (
    '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="12" cy="12" r="9"/><path d="M12 8v5"/><circle cx="12" cy="16" r="0.5" fill="currentColor"/></svg>'
)
_QUESTION_ICON = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 0 1 4.9.8c0 1.7-2.4 1.7-2.4 3.4"/>'
    '<circle cx="12" cy="16.5" r="0.5" fill="currentColor"/></svg>'
)
@st.dialog("관리자에게 문의")
def _show_inquiry_dialog(room_id: str, log: dict) -> None:
    st.markdown(
        f"""
        <p class="ts-inquiry-label">문의 내용</p>
        <p class="ts-inquiry-summary">{log["content"]} · {log["failure_title"]}</p>
        """,
        unsafe_allow_html=True,
    )
    message = st.text_area(
        "문의 메시지",
        placeholder="문의하실 내용을 입력해 주세요",
        key="inquiry_message",
        label_visibility="collapsed",
    )
    st.markdown(
        f'<p class="ts-inquiry-phone">관리자 연락처 · {ADMIN_PHONE}</p>',
        unsafe_allow_html=True,
    )
    if st.button("문의 보내기", key="inquiry_submit", use_container_width=True):
        if not message.strip():
            st.warning("문의 내용을 입력해 주세요")
        else:
            submit_inquiry(room_id=room_id, log_id=log["id"], message=message)
            st.toast("문의가 접수됐어요")
            st.rerun()


apply_mobile_styles("log_detail", shared=("log",))

if not is_logged_in():
    st.switch_page("pages/login.py")

room_id = st.session_state.get("_ts_selected_room")
room = get_room(room_id) if room_id else None

if room is None:
    st.switch_page("pages/room_list.py")

log_id = st.session_state.get("_ts_selected_log")
log = get_log(log_id) if log_id else None

if log is None or log["success"]:
    st.switch_page("pages/log_list.py")

page_header("제어 로그 상세", back_page="pages/log_list.py")

st.markdown(
    f"""
    <div class="ts-log-fail-card">
      <div class="ts-log-fail-icon-chip">{_WARNING_ICON}</div>
      <p class="ts-log-fail-title">{log["failure_title"]}</p>
      <p class="ts-log-fail-desc">{log["failure_reason"]}</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.container(key="ts_log_cause_card", border=True):
    st.markdown(
        f'<p class="ts-log-card-title">{_QUESTION_ICON}원인 추정</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p class="ts-log-cause-desc">{log["cause_guess"]}</p>',
        unsafe_allow_html=True,
    )

checklist_items = "".join(f"<li>{item}</li>" for item in log["checklist"])
st.markdown(
    f"""
    <div class="ts-log-checklist-card">
      <p class="ts-log-card-title">확인해 주세요</p>
      <ul class="ts-log-checklist">{checklist_items}</ul>
    </div>
    """,
    unsafe_allow_html=True,
)

if st.button(
    "수동 제어로 이동",
    key="log_go_manual",
    use_container_width=True,
):
    st.switch_page("pages/home.py")

if st.button("관리자에게 문의", key="log_contact_admin", use_container_width=True):
    _show_inquiry_dialog(room["id"], log)
