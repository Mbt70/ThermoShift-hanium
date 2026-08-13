import base64
import re
from datetime import date
from pathlib import Path

import streamlit as st

from app.components.auth_store import is_logged_in
from app.components.control_log_store import list_logs, method_label
from app.components.mobile_ui import apply_mobile_styles, bottom_tab_bar, page_header
from app.components.room_store import get_room

ICONS_DIR = Path(__file__).resolve().parents[1] / "assets" / "icons"

_METHOD_ICON_FILES = {
    "rule": "rule-based.svg",
    "manual": "back_hand.svg",
    "predict": "predictive.svg",
}
_METHOD_ICON_COLOR = "#397f80"
_FILTER_OPTIONS = ["전체", "규칙", "수동", "예측"]
_FILTER_TO_METHOD = {"전체": None, "규칙": "rule", "수동": "manual", "예측": "predict"}


def _icon_data_uri(file_name: str) -> str:
    encoded = base64.b64encode((ICONS_DIR / file_name).read_bytes()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _recolored_icon_data_uri(file_name: str, color: str) -> str:
    content = (ICONS_DIR / file_name).read_text(encoding="utf-8")
    content = re.sub(r"<mask[^>]*>.*?</mask>", "", content, flags=re.DOTALL)
    content = re.sub(r'<[a-zA-Z]+[^>]*\smask="[^"]*"[^>]*/?>', "", content)
    content = re.sub(r'fill="(?!none"|white")[^"]*"', f'fill="{color}"', content)
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


apply_mobile_styles("log_list", shared=("log",))

if not is_logged_in():
    st.switch_page("pages/login.py")

room_id = st.session_state.get("_ts_selected_room")
room = get_room(room_id) if room_id else None

if room is None:
    st.switch_page("pages/room_list.py")

page_header("제어 로그", back_page="pages/home.py")

log_date = date.today()

filter_label = st.pills(
    "방식",
    options=_FILTER_OPTIONS,
    default="전체",
    key="log_method_filter",
    label_visibility="collapsed",
)
method = _FILTER_TO_METHOD.get(filter_label)

day_label = f"오늘 · {log_date.month}월 {log_date.day}일"
st.markdown(f'<p class="ts-log-day-label">{day_label}</p>', unsafe_allow_html=True)

logs = list_logs(room["id"], log_date, method=method)

if logs:
    with st.container(key="ts_log_table_card", border=True):
        st.markdown(
            """
            <div class="ts-log-table-header">
              <span class="ts-log-col-content">제어내용</span>
              <span class="ts-log-col-method">방식</span>
              <span class="ts-log-col-time">시간</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        for log in logs:
            status_icon_file = "control_success.svg" if log["success"] else "control_error.svg"
            status_uri = _icon_data_uri(status_icon_file)
            method_uri = _recolored_icon_data_uri(
                _METHOD_ICON_FILES[log["method"]], _METHOD_ICON_COLOR
            )
            row_class = "ts-log-row-fail" if not log["success"] else ""

            with st.container(key=f"ts_log_row_{log['id']}"):
                if not log["success"]:
                    clicked = st.button(
                        log["content"],
                        key=f"ts_log_open_{log['id']}",
                        use_container_width=True,
                    )
                st.markdown(
                    f"""
                    <div class="ts-log-row {row_class}">
                      <span class="ts-log-content-group">
                        <img src="{status_uri}" class="ts-log-status-icon" alt="" />
                        <span class="ts-log-content-text">{log["content"]}</span>
                      </span>
                      <span class="ts-log-method">
                        <img src="{method_uri}" class="ts-log-method-icon" alt=""
                             title="{method_label(log["method"])}" />
                      </span>
                      <span class="ts-log-time">{log["timestamp"].hour}:{log["timestamp"].minute:02d}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            if not log["success"] and clicked:
                st.session_state["_ts_selected_log"] = log["id"]
                st.session_state["_ts_log_detail_return"] = "pages/log_list.py"
                st.switch_page("pages/log_detail.py")
else:
    st.markdown(
        '<p class="ts-log-empty">해당 조건의 제어 로그가 없어요</p>',
        unsafe_allow_html=True,
    )

bottom_tab_bar(active="log")
