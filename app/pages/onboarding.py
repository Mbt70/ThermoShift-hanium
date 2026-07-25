import streamlit as st

from app.components.mobile_ui import apply_mobile_styles, auth_switch_link, brand_logo

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
