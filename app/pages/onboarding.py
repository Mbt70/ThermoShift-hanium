import base64
from pathlib import Path

import streamlit as st

from app.components.mobile_ui import apply_mobile_styles, auth_switch_link

LOGO = Path(__file__).resolve().parents[1] / "assets" / "icons" / "logo.svg"


def brand_logo() -> None:
    encoded_logo = base64.b64encode(LOGO.read_bytes()).decode("ascii")
    st.markdown(
        f"""
        <div class="ts-logo" aria-label="ThermoShift 로고">
          <img src="data:image/svg+xml;base64,{encoded_logo}"
               alt="ThermoShift 로고">
        </div>
        """,
        unsafe_allow_html=True,
    )


apply_mobile_styles("onboarding")

st.markdown('<div class="ts-onboarding-space-top"></div>', unsafe_allow_html=True)
brand_logo()
st.markdown(
    """
    <div class="ts-brand-copy">
      <h1>ThermoShift</h1>
      <p>스마트 HVAC 운영으로<br>더 쾌적하고 효율적인 공간을 실현합니다</p>
    </div>
    <div class="ts-onboarding-space-action"></div>
    """,
    unsafe_allow_html=True,
)

if st.button("로그인", key="onboarding_login", use_container_width=True):
    st.switch_page("pages/login.py")

auth_switch_link(
    "pages/signup.py",
    "회원가입",
    key="onboarding_signup_link",
    prompt="아직 계정이 없으신가요?",
)
