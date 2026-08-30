import sys
from datetime import date
from pathlib import Path

import streamlit as st

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from app.components.control_log_store import get_log, list_logs, method_label
from app.components.room_store import list_rooms
from components.auth_store import current_user_id, is_logged_in
from components.dash_shell import render_sidebar
from components.mobile_ui import apply_mobile_styles, recolored_icon_data_uri

_METHOD_ICON_FILES = {"rule": "rule-based.svg", "manual": "back_hand.svg", "predict": "predictive.svg"}
_METHOD_ICON_COLOR = "#397f80"
_STATUS_OPTIONS = ["전체", "성공", "실패", "주의"]

_CHECK_ICON = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" '
    'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="12" cy="12" r="9"/><path d="M8 12.5 11 15.5 16 9"/></svg>'
)
_FAIL_ICON = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" '
    'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v6"/><circle cx="12" cy="16.5" r="0.6" fill="currentColor"/></svg>'
)
_ATTENTION_ICON = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 4 3 20h18L12 4Z"/><path d="M12 10v4M12 16.5v.1"/></svg>'
)
_QUESTION_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 0 1 4.9.8c0 1.7-2.4 1.7-2.4 3.4"/>'
    '<circle cx="12" cy="16.5" r="0.5" fill="currentColor"/></svg>'
)
apply_mobile_styles("control_log", shared=("dash_shell",))

if not is_logged_in():
    st.switch_page("pages/login.py")

rooms = list_rooms(current_user_id())

selected_id = st.session_state.get("_web_selected_room")
if selected_id and not any(r["id"] == selected_id for r in rooms):
    selected_id = None
if selected_id is None and rooms:
    selected_id = rooms[0]["id"]
    st.session_state["_web_selected_room"] = selected_id

room = next((r for r in rooms if r["id"] == selected_id), None) if selected_id else None

sidebar_col, main_col = st.columns([1, 4], gap="small")

with sidebar_col:
    render_sidebar("control_log")

with main_col:
    if not rooms or room is None:
        st.switch_page("pages/devices.py")
    else:
        title_col, select_col, spacer_col = st.columns([0.6, 0.8, 4.4], vertical_alignment="center")
        with title_col:
            st.markdown('<h1 class="ts-dash-topbar-title">공간</h1>', unsafe_allow_html=True)
        with select_col:
            names = [r["name"] for r in rooms]
            current_index = next((i for i, r in enumerate(rooms) if r["id"] == room["id"]), 0)
            picked = st.selectbox(
                "공간 선택", names, index=current_index, key="log_top_room_select", label_visibility="collapsed"
            )
            picked_room = next((r for r in rooms if r["name"] == picked), room)
            if picked_room["id"] != room["id"]:
                st.session_state["_web_selected_room"] = picked_room["id"]
                st.session_state.pop("_web_selected_log", None)
                st.rerun()

        @st.fragment(run_every=5)
        def render_live_logs(current_room_id):
            with st.container(key="ts_dash_log_filter_card"):
                status_label = st.segmented_control(
                    "상태", options=_STATUS_OPTIONS, default="전체", key="log_status_filter", label_visibility="collapsed"
                ) or "전체"

            st.markdown(
                f"""
                <div class="ts-log-legend">
                  <span class="ts-log-legend-item is-ok">{_CHECK_ICON}성공</span>
                  <span class="ts-log-legend-item is-fail">{_FAIL_ICON}실패</span>
                  <span class="ts-log-legend-item is-warn">{_ATTENTION_ICON}주의</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

            all_logs = list_logs(current_room_id, date.today())
            if status_label == "성공":
                logs = [log for log in all_logs if log["success"]]
            elif status_label in ("실패", "주의"):
                logs = [log for log in all_logs if not log["success"]] if status_label == "실패" else []
            else:
                logs = all_logs
            logs = list(reversed(logs))

            selected_log_id = st.session_state.get("_web_selected_log")
            selected_log = get_log(selected_log_id) if selected_log_id else None
            if selected_log is not None and (selected_log["room_id"] != current_room_id or selected_log["success"]):
                selected_log = None
                st.session_state.pop("_web_selected_log", None)

            with st.container(key="ts_dash_log_split_card", border=True):
                list_col, detail_col = st.columns([1.6, 1], gap="small")

                with list_col:
                    if logs:
                        st.markdown(
                            """
                            <div class="ts-log-row ts-log-row-head">
                              <span>제어내용</span><span>방식</span><span>시간</span>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                        clicked_log_id = None
                        for log in logs:
                            status_icon = _CHECK_ICON if log["success"] else _FAIL_ICON
                            status_class = "is-ok" if log["success"] else "is-fail"
                            method_uri = recolored_icon_data_uri(_METHOD_ICON_FILES[log["method"]], _METHOD_ICON_COLOR)
                            time_label = f'{log["timestamp"].hour}:{log["timestamp"].minute:02d}'
                            with st.container(key=f"ts_dash_log_row_{log['id']}"):
                                st.markdown(
                                    f"""
                                    <div class="ts-log-row">
                                      <span class="ts-log-content {status_class}">{status_icon}{log["content"]}</span>
                                      <img class="ts-log-method-icon ts-log-method-icon-{log["method"]}" src="{method_uri}" alt="" title="{method_label(log["method"])}" />
                                      <span class="ts-log-time">{time_label}</span>
                                    </div>
                                    """,
                                    unsafe_allow_html=True,
                                )
                                if not log["success"]:
                                    if st.button(log["content"], key=f"dash_log_open_{log['id']}", width="stretch"):
                                        clicked_log_id = log["id"]
                        if clicked_log_id and clicked_log_id != selected_log_id:
                            st.session_state["_web_selected_log"] = clicked_log_id
                            st.rerun()
                    else:
                        st.markdown(
                            '<p class="ts-dash-list-empty">해당 조건의 제어 로그가 없습니다</p>',
                            unsafe_allow_html=True,
                        )

                with detail_col:
                    if selected_log is not None:
                        checklist_items = "".join(f"<li>{item}</li>" for item in selected_log["checklist"])
                        st.markdown(
                            f"""
                            <div class="ts-log-fail-icon-chip">{_FAIL_ICON}</div>
                            <p class="ts-log-fail-title">{selected_log["failure_title"]}</p>
                            <div class="ts-log-cause-card">
                              <p class="ts-log-detail-title">{_QUESTION_ICON}원인 추정</p>
                              <p class="ts-log-cause-desc">{selected_log["cause_guess"]}</p>
                            </div>
                            <div class="ts-log-checklist-card">
                              <p class="ts-log-detail-title">확인해주세요</p>
                              <ul class="ts-log-checklist">{checklist_items}</ul>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

        render_live_logs(room["id"])
