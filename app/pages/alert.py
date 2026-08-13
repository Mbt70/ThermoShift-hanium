import base64
import re
from datetime import date
from pathlib import Path

import streamlit as st

from app.components.alert_store import ALERT_TYPE_CONFIG, FILTER_OPTIONS, list_alerts
from app.components.auth_store import is_logged_in
from app.components.control_log_store import list_logs
from app.components.mobile_ui import apply_mobile_styles, bottom_tab_bar, page_header

ICONS_DIR = Path(__file__).resolve().parents[1] / "assets" / "icons"
_ALERT_ICON_COLOR = "#cd4843"


def _recolored_icon_data_uri(file_name: str, color: str) -> str:
    content = (ICONS_DIR / file_name).read_text(encoding="utf-8")
    content = re.sub(r"<mask[^>]*>.*?</mask>", "", content, flags=re.DOTALL)
    content = re.sub(r'<[a-zA-Z]+[^>]*\smask="[^"]*"[^>]*/?>', "", content)
    content = re.sub(r'fill="(?!none"|white")[^"]*"', f'fill="{color}"', content)
    content = re.sub(r'stroke="(?!none"|white")[^"]*"', f'stroke="{color}"', content)
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _handle_alert_click(alert: dict) -> None:
    # 알림 = 제어로그 중 사람의 조치가 필요한 것만 걸러 보여주는 뷰이므로,
    # 어떤 타입이든 눌렀을 때 제어로그 상세페이지로 이동한다. control_failed는
    # 실제 오늘자 제어로그에서 매칭되는 실패 항목을 찾고, 그 외(센서/CO2/온도
    # /네트워크)는 제어 명령이 아니라 control_log_store.get_log()가 "alert_"
    # 접두사로 인식해 알림 데이터로부터 로그 형태를 즉석에서 만들어준다.
    log_id = f"alert_{alert['id']}"
    if alert["type"] == "control_failed":
        room_id = st.session_state.get("_ts_selected_room")
        if room_id:
            failed_logs = [
                log for log in list_logs(room_id, date.today()) if not log["success"]
            ]
            if failed_logs:
                log_id = failed_logs[0]["id"]
    st.session_state["_ts_selected_log"] = log_id
    st.session_state["_ts_log_detail_return"] = "pages/alert.py"
    st.switch_page("pages/log_detail.py")


def _render_alert_item(alert: dict) -> None:
    config = ALERT_TYPE_CONFIG.get(alert["type"], {})
    icon_uri = _recolored_icon_data_uri(
        config.get("icon", "control_error.svg"), _ALERT_ICON_COLOR
    )

    with st.container(key=f"ts_alert_row_{alert['id']}"):
        clicked = st.button(
            alert["title"], key=f"ts_alert_open_{alert['id']}", use_container_width=True
        )
        st.markdown(
            f"""
            <div class="ts-alert-row">
              <div class="ts-alert-icon-chip">
                <img src="{icon_uri}" alt="" />
              </div>
              <div class="ts-alert-body">
                <div class="ts-alert-title-line">
                  <span class="ts-alert-title">{alert["title"]}</span>
                  <span class="ts-alert-time">{alert["time"]}</span>
                </div>
                <p class="ts-alert-message">{alert["message"]}</p>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    if clicked:
        _handle_alert_click(alert)


apply_mobile_styles("alert", shared=("log",))

if not is_logged_in():
    st.switch_page("pages/login.py")

page_header("알림 · 이벤트", show_back=False)

filter_label = st.pills(
    "알림 필터",
    options=FILTER_OPTIONS,
    default="전체",
    key="alert_type_filter",
    label_visibility="collapsed",
)

alerts = list_alerts(filter_label)

if alerts:
    with st.container(key="ts_alert_card", border=True):
        for alert in alerts:
            _render_alert_item(alert)
else:
    st.markdown(
        '<p class="ts-alert-empty">현재 발생한 알림이 없습니다.</p>',
        unsafe_allow_html=True,
    )

bottom_tab_bar(active="alert")
