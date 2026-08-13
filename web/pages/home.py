import streamlit as st

from components.mobile_ui import apply_mobile_styles

apply_mobile_styles("home")

st.markdown(
    """
    <p class="ts-single-link-prompt">기본 세팅 완료</p>
    <h1>web 👋</h1>
    """,
    unsafe_allow_html=True,
)
st.write("여기에 페이지를 추가하면 됩니다. `web/pages/`에 파일을 만들고 `main.py`의 `pages` 목록에 등록하세요.")
