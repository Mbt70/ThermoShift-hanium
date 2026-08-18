import sys
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = WEB_ROOT.parent
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import streamlit as st


def page(source: str, *, title: str, url_path: str, default: bool = False):
    return st.Page(source, title=title, url_path=url_path, default=default)


st.set_page_config(
    page_title="ThermoShift",
    layout="wide",
    initial_sidebar_state="collapsed",
)

pages = [
    page("pages/login.py", title="로그인", url_path="login", default=True),
    page("pages/home.py", title="대시보드", url_path="home"),
    page("pages/room_detail.py", title="공간 상세", url_path="room-detail"),
    page("pages/digital_twin.py", title="디지털 트윈·3D", url_path="digital-twin"),
    page("pages/devices.py", title="공간·디바이스", url_path="devices"),
    page("pages/my_page.py", title="마이페이지", url_path="my-page"),
    page("pages/control_log.py", title="제어 로그", url_path="control-log"),
]

navigation = st.navigation(pages, position="hidden")
navigation.run()
