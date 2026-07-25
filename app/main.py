import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import streamlit as st


def page(
    source: str, *, title: str, url_path: str, default: bool = False
):
    configured_page = st.Page(
        source,
        title=title,
        url_path=url_path.replace("/", "-"),
        default=default,
    )
    configured_page._url_path = url_path
    return configured_page


st.set_page_config(
    page_title="ThermoShift",
    layout="centered",
    initial_sidebar_state="collapsed",
)

pages = [
    page(
        "pages/onboarding.py",
        title="온보딩",
        url_path="onboarding",
        default=True,
    ),
    page("pages/signup.py", title="회원가입", url_path="signup"),
    page("pages/login.py", title="로그인", url_path="login"),
    page("pages/room_list.py", title="방 목록", url_path="rooms"),
    page("pages/room_create.py", title="방 만들기", url_path="rooms/new"),
    page("pages/home.py", title="홈", url_path="home"),
    page("pages/schedule_list.py", title="일정 목록", url_path="schedule"),
    page("pages/schedule_create.py", title="일정 만들기", url_path="schedule/new"),
    page(
        "pages/schedule_detail.py",
        title="일정 상세",
        url_path="schedule/detail",
    ),
    page("pages/log_list.py", title="로그 목록", url_path="log"),
    page("pages/log_detail.py", title="로그 상세", url_path="log/detail"),
    page("pages/alert.py", title="알림", url_path="alert"),
    page("pages/settings.py", title="설정", url_path="settings"),
    page(
        "pages/password.py",
        title="비밀번호 설정",
        url_path="settings/password",
    ),
    page("pages/room_settings.py", title="방 설정", url_path="settings/room"),
]

navigation = st.navigation(pages, position="hidden")
navigation.run()
