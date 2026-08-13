import sys
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parent
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

import streamlit as st


def page(source: str, *, title: str, url_path: str, default: bool = False):
    return st.Page(source, title=title, url_path=url_path, default=default)


st.set_page_config(
    page_title="ThermoShift",
    layout="wide",
    initial_sidebar_state="collapsed",
)

pages = [
    page("pages/home.py", title="홈", url_path="home", default=True),
]

navigation = st.navigation(pages, position="hidden")
navigation.run()
