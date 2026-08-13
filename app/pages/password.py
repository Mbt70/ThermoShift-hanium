import streamlit as st

from app.components.auth_store import (
    current_user_email,
    is_logged_in,
    update_password,
)
from app.components.mobile_ui import apply_mobile_styles, page_header

apply_mobile_styles("password", shared=("settings",))

if not is_logged_in():
    st.switch_page("pages/login.py")

page_header("비밀번호 변경", back_page="pages/settings.py")

st.markdown('<p class="ts-settings-field-label">비밀번호</p>', unsafe_allow_html=True)
password = st.text_input(
    "비밀번호",
    type="password",
    placeholder="6자 이상 입력해주세요",
    icon=":material/lock:",
    key="password_new",
    label_visibility="collapsed",
)

st.markdown('<p class="ts-settings-field-label">비밀번호 확인</p>', unsafe_allow_html=True)
password_confirm = st.text_input(
    "비밀번호 확인",
    type="password",
    icon=":material/lock:",
    key="password_confirm",
    label_visibility="collapsed",
)

error_slot = st.empty()

with st.container(key="ts_password_submit_wrap"):
    submitted = st.button("변경하기", key="password_submit", use_container_width=True)

password_length_ok = len(password) >= 6
password_match_ok = password == password_confirm

if submitted:
    if not password_length_ok:
        error_slot.markdown(
            '<p class="ts-settings-error">비밀번호는 6자 이상이어야 합니다</p>',
            unsafe_allow_html=True,
        )
    elif not password_match_ok:
        error_slot.markdown(
            '<p class="ts-settings-error">비밀번호가 일치하지 않습니다</p>',
            unsafe_allow_html=True,
        )
    else:
        update_password(current_user_email(), password)
        st.toast("비밀번호가 변경됐어요")
        st.switch_page("pages/settings.py")
