import streamlit as st

from components.auth_store import (
    check_credentials,
    is_registered,
    register_user,
    set_current_user,
    start_demo_session,
)
from components.mobile_ui import ICONS_DIR, apply_mobile_styles, icon_data_uri, inline_error

apply_mobile_styles("login")

# The auth_mode pills widget below owns st.session_state["auth_mode"] once it
# renders, so it can't be reassigned later in the same run (Streamlit raises
# StreamlitAPIException). To force-switch tabs (e.g. after a successful
# signup) a handler stashes the target in _pending_auth_mode and reruns; this
# consumes it before the widget is instantiated, which is the one point a
# rerun is allowed to change it.
if "_pending_auth_mode" in st.session_state:
    st.session_state["auth_mode"] = st.session_state.pop("_pending_auth_mode")


def _inline_vector(file_name: str, css_class: str) -> str:
    # Inlined (not <img src>) so CSS can control stroke-width - the source
    # files don't set one, so the 1px default becomes near-invisible once
    # scaled down as a rasterized image.
    svg = (ICONS_DIR / file_name).read_text(encoding="utf-8")
    return svg.replace("<svg ", f'<svg class="ts-auth-vector {css_class}" ', 1)


def _inline_feature_icon(file_name: str) -> str:
    # The source icons are all fill="#00696D" (dark teal) - fine on a white
    # settings row, invisible against this panel's teal background, so
    # recolor to white on the way in.
    svg = (ICONS_DIR / file_name).read_text(encoding="utf-8")
    return svg.replace('fill="#00696D"', 'fill="#fff"')


_FEATURES = [
    ("predictive.svg", "AI 예측 자동제어", "실내 환경 최적화 / 쾌적도 유지"),
    ("deployed_code.svg", "디지털 트윈", "실시간 공간 모니터링"),
    ("bolt.svg", "스마트 HVAC 운영", "에너지 절감 및 효율 향상"),
]


def _feature_row(icon_file: str, title: str, desc: str) -> str:
    return (
        '<div class="ts-auth-feature">'
        f'<div class="ts-auth-feature-icon">{_inline_feature_icon(icon_file)}</div>'
        "<div>"
        f'<p class="ts-auth-feature-title">{title}</p>'
        f'<p class="ts-auth-feature-desc">{desc}</p>'
        "</div>"
        "</div>"
    )


feature_rows = "".join(_feature_row(icon, title, desc) for icon, title, desc in _FEATURES)

hero_html = (
    '<div class="ts-auth-hero">'
    + _inline_vector("Vector 2.svg", "ts-auth-vector-2")
    + _inline_vector("Vector 3.svg", "ts-auth-vector-3")
    + '<div class="ts-auth-hero-content">'
    + '<div class="ts-auth-brand">'
    + f'<img class="ts-auth-logo" src="{icon_data_uri("logo.svg")}" alt="" />'
    + '<span class="ts-auth-brand-name">Thermoshift</span>'
    + "</div>"
    + '<h1 class="ts-auth-heading">공간을 이해하고<br />미래를 제어합니다</h1>'
    + '<p class="ts-auth-subheading">'
    + "AI 기반 실내 환경 제어, 디지털 트윈 모니터링,<br />"
    + "스마트 HVAC 운영으로 더 쾌적하고 효율적인 공간을 실현합니다"
    + "</p>"
    + f'<div class="ts-auth-features">{feature_rows}</div>'
    + "</div>"
    + f'<img class="ts-auth-hero-image" src="{icon_data_uri("image 27.png")}" alt="" />'
    + "</div>"
)

left_col, right_col = st.columns([3, 2], gap="small")

with left_col:
    st.markdown(hero_html, unsafe_allow_html=True)

with right_col:
    with st.container(key="ts_auth_form_col"):
        with st.container(key="ts_auth_tabs"):
            mode = st.pills(
                "모드",
                options=["로그인", "회원가입"],
                default="로그인",
                key="auth_mode",
                label_visibility="collapsed",
            )

        if mode == "로그인":
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
                submitted = st.form_submit_button(
                    "로그인", key="login_submit", width="stretch"
                )

            if submitted:
                email_registered = bool(email) and is_registered(email)
                credentials_ok = (
                    email_registered
                    and bool(password)
                    and check_credentials(email, password)
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
                    st.switch_page("pages/home.py")

            st.markdown(
                "<div style='text-align:center; margin:10px 0 6px 0; "
                "color:#94a3b8; font-size:12px;'>또는</div>",
                unsafe_allow_html=True,
            )
            if st.button(
                "🚀 심사위원 시연 화면으로 이동",
                key="demo_guest_login",
                type="primary",
                use_container_width=True,
            ):
                if start_demo_session():
                    st.switch_page("pages/home.py")
                else:
                    inline_error("DB에 시연 계정이 지정되지 않았습니다")

        else:
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
                    placeholder="8자 이상 입력해주세요",
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
                signup_submitted = st.button(
                    "가입하기", key="signup_submit", width="stretch"
                )

            email_format_ok = (
                bool(email) and "@" in email and "." in email.rsplit("@", 1)[-1]
            )
            email_taken = email_format_ok and is_registered(email)
            password_length_ok = len(password) >= 8
            password_match_ok = password == password_confirm

            if (email or signup_submitted) and not email_format_ok:
                with email_error:
                    inline_error("이메일 형식이 올바르지 않습니다")
            elif (email or signup_submitted) and email_taken:
                with email_error:
                    inline_error("이미 가입된 이메일입니다")

            if (password or signup_submitted) and not password_length_ok:
                with password_length_error:
                    inline_error("비밀번호는 8자 이상이어야 합니다")

            if (password_confirm or signup_submitted) and not password_match_ok:
                with password_match_error:
                    inline_error("비밀번호가 일치하지 않습니다")

            if signup_submitted:
                valid = (
                    bool(name)
                    and email_format_ok
                    and not email_taken
                    and password_length_ok
                    and password_match_ok
                )
                if valid:
                    register_user(name, email, password)
                    st.session_state["_pending_auth_mode"] = "로그인"
                    st.toast("회원가입이 완료됐어요! 로그인해주세요", icon="✅")
                    st.rerun()
