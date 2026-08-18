import sys
from pathlib import Path

import streamlit as st

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from components.auth_store import (
    current_user_email,
    current_user_name,
    delete_user,
    is_logged_in,
    log_out,
    update_password,
    update_user_name,
)
from components.dash_shell import render_sidebar
from components.mobile_ui import apply_mobile_styles

_PERSON_ICON = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="12" cy="8.5" r="3.5"/><path d="M5 20c0-3.5 3-6 7-6s7 2.5 7 6"/></svg>'
)

apply_mobile_styles("my_page", shared=("dash_shell",))

if not is_logged_in():
    st.switch_page("pages/login.py")

email = current_user_email()


@st.dialog("로그아웃")
def _confirm_logout() -> None:
    st.write("정말 로그아웃 하시겠습니까?")
    cancel_col, confirm_col = st.columns(2)
    with cancel_col:
        if st.button("취소", key="mypage_logout_cancel", width="stretch"):
            st.rerun()
    with confirm_col:
        if st.button("로그아웃", key="mypage_logout_confirm", width="stretch"):
            log_out()
            st.switch_page("pages/login.py")


@st.dialog("회원탈퇴")
def _confirm_delete() -> None:
    st.write("정말 탈퇴하시겠습니까? 이 작업은 되돌릴 수 없습니다.")
    cancel_col, confirm_col = st.columns(2)
    with cancel_col:
        if st.button("취소", key="mypage_delete_cancel", width="stretch"):
            st.rerun()
    with confirm_col:
        if st.button("탈퇴하기", key="mypage_delete_confirm", width="stretch"):
            delete_user(email)
            log_out()
            st.switch_page("pages/login.py")

sidebar_col, main_col = st.columns([1, 4], gap="small")

with sidebar_col:
    render_sidebar(None)

with main_col:
    st.markdown('<h1 class="ts-dash-topbar-title">내 정보</h1>', unsafe_allow_html=True)

    with st.container(key="ts_dash_mypage_account_card", border=True):
        st.markdown(f'<p class="ts-dash-card-title">{_PERSON_ICON}계정 정보</p>', unsafe_allow_html=True)
        new_name = st.text_input("이름", value=current_user_name(), key="mypage_name")
        st.text_input("이메일", value=email or "", key="mypage_email", disabled=True)
        _acc_spacer, _acc_save = st.columns([4, 1])
        with _acc_save:
            if st.button("저장", key="mypage_save_name", width="stretch"):
                update_user_name(email, new_name.strip() or current_user_name())
                st.toast("이름을 저장했습니다")

    with st.container(key="ts_dash_mypage_password_card", border=True):
        st.markdown('<p class="ts-dash-card-title">비밀번호 변경</p>', unsafe_allow_html=True)
        new_password = st.text_input("비밀번호", type="password", key="mypage_password")
        confirm_password = st.text_input("비밀번호 확인", type="password", key="mypage_password_confirm")
        _pw_spacer, _pw_save = st.columns([4, 1])
        with _pw_save:
            if st.button("저장", key="mypage_save_password", width="stretch"):
                if not new_password:
                    st.toast("비밀번호를 입력해주세요")
                elif new_password != confirm_password:
                    st.toast("비밀번호가 일치하지 않습니다")
                else:
                    update_password(email, new_password)
                    st.session_state["mypage_password"] = ""
                    st.session_state["mypage_password_confirm"] = ""
                    st.toast("비밀번호를 변경했습니다")

    with st.container(key="ts_dash_mypage_footer"):
        logout_col, spacer_col2, delete_col = st.columns([1, 5, 1])
        with logout_col:
            if st.button("로그아웃", key="mypage_logout_link", width="content"):
                _confirm_logout()
        with delete_col:
            if st.button("회원탈퇴", key="mypage_delete_link", width="content"):
                _confirm_delete()
