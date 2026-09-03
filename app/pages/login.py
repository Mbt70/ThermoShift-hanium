import streamlit as st

from app.components.auth_store import (
    check_credentials,
    is_registered,
    set_current_user,
    start_demo_session,
)
from app.components.mobile_ui import (
    apply_mobile_styles,
    auth_switch_link,
    inline_error,
    page_header,
)

apply_mobile_styles("login")
page_header("로그인")
st.markdown('<div class="ts-form-space"></div>', unsafe_allow_html=True)

with st.form("login_form", border=False):
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
        placeholder="비밀번호를 입력해주세요",
        icon=":material/lock:",
        autocomplete="current-password",
    )
    password_error = st.empty()
    st.markdown('<div class="ts-form-submit-space"></div>', unsafe_allow_html=True)
    submitted = st.form_submit_button(
        "로그인",
        key="login_submit",
        use_container_width=True,
    )


if submitted:
    email_registered = bool(email) and is_registered(email)
    credentials_ok = email_registered and bool(password) and check_credentials(
        email, password
    )

    if not email:
        with email_error:
            inline_error("이메일을 입력해주세요")
    elif not email_registered:
        with email_error:
            inline_error("가입되지 않은 이메일입니다")

    if not password:
        with password_error:
            inline_error("비밀번호를 입력해주세요")
    elif email_registered and not credentials_ok:
        with password_error:
            inline_error("비밀번호가 올바르지 않습니다")

    if credentials_ok:
        set_current_user(email)
        st.switch_page("pages/room_list.py")

st.markdown('<div class="ts-form-submit-space"></div>', unsafe_allow_html=True)
if st.button(
    "로그인 없이 둘러보기",
    key="demo_guest_login",
    use_container_width=True,
):
    if start_demo_session():
        st.switch_page("pages/room_list.py")
    else:
        inline_error("DB에 시연 계정이 지정되지 않았습니다")

auth_switch_link("pages/signup.py", "회원가입", key="login_signup_link")
