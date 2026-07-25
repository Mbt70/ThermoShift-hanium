import streamlit as st

from app.components.auth_store import is_registered, register_user
from app.components.mobile_ui import (
    apply_mobile_styles,
    auth_switch_link,
    inline_error,
    page_header,
)

apply_mobile_styles("signup")
page_header("회원가입")

with st.container(key="signup_fields", border=False):
    name = st.text_input(
        "이름",
        placeholder="Thermo",
        icon=":material/person:",
        autocomplete="name",
    )
    email = st.text_input(
        "이메일",
        placeholder="thermoshift@thermo.com",
        icon=":material/mail:",
        autocomplete="email",
    )
    email_error = st.empty()
    password = st.text_input(
        "비밀번호",
        type="password",
        placeholder="6자 이상 입력해주세요",
        icon=":material/lock:",
        autocomplete="new-password",
    )
    password_length_error = st.empty()
    password_confirm = st.text_input(
        "비밀번호 확인",
        type="password",
        placeholder="비밀번호를 다시 입력해주세요",
        icon=":material/lock:",
        autocomplete="new-password",
    )
    password_match_error = st.empty()
    st.markdown('<div class="ts-form-submit-space"></div>', unsafe_allow_html=True)
    submitted = st.button(
        "가입하기",
        key="signup_submit",
        use_container_width=True,
    )

email_format_ok = bool(email) and "@" in email and "." in email.rsplit("@", 1)[-1]
email_taken = email_format_ok and is_registered(email)
password_length_ok = len(password) >= 6
password_match_ok = password == password_confirm

if (email or submitted) and not email_format_ok:
    with email_error:
        inline_error("이메일 형식이 올바르지 않습니다")
elif (email or submitted) and email_taken:
    with email_error:
        inline_error("이미 가입된 이메일입니다")

if (password or submitted) and not password_length_ok:
    with password_length_error:
        inline_error("비밀번호는 6자 이상이어야 합니다")

if (password_confirm or submitted) and not password_match_ok:
    with password_match_error:
        inline_error("비밀번호가 일치하지 않습니다")

if submitted:
    valid = (
        bool(name)
        and email_format_ok
        and not email_taken
        and password_length_ok
        and password_match_ok
    )
    if valid:
        register_user(name, email, password)
        st.switch_page("pages/login.py")

auth_switch_link(
    "pages/login.py",
    "로그인으로 이동",
    key="signup_login_link",
    prompt="이미 계정이 있으신가요?",
)
