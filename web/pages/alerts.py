import calendar
import sys
from datetime import date
from pathlib import Path

import streamlit as st

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from app.components.alert_store import list_room_alerts, mark_alert_read
from app.components.room_store import list_rooms
from components.auth_store import current_user_id, is_logged_in
from components.dash_shell import render_sidebar
from components.mobile_ui import apply_mobile_styles

_FAIL_ICON = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
    'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v6"/><circle cx="12" cy="16.5" r="0.6" fill="currentColor"/></svg>'
)
_ATTENTION_ICON = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 4 3 20h18L12 4Z"/><path d="M12 10v4M12 16.5v.1"/></svg>'
)

apply_mobile_styles("alerts", shared=("dash_shell",))

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
    render_sidebar("alerts")

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
                "공간 선택", names, index=current_index, key="alert_top_room_select", label_visibility="collapsed"
            )
            picked_room = next((r for r in rooms if r["name"] == picked), room)
            if picked_room["id"] != room["id"]:
                st.session_state["_web_selected_room"] = picked_room["id"]
                st.rerun()

        today = date.today()
        year_options = [f"{y}년" for y in range(today.year - 2, today.year + 1)]
        month_options = [f"{m}월" for m in range(1, 13)]

        # Resolve the current date-toggle selection from session_state *before*
        # the widgets are created below, so the alert list (and the banner,
        # which has to render above the card the widgets live in) can be
        # computed first. The widgets, once created, read/write the exact
        # same keys, so this always matches what's actually shown.
        year_pick = st.session_state.get("alert_year_select", f"{today.year}년")
        month_pick = st.session_state.get("alert_month_select", f"{today.month}월")
        year = int(year_pick[:-1])
        month = int(month_pick[:-1])
        max_day = calendar.monthrange(year, month)[1]
        default_day = today.day if (year, month) == (today.year, today.month) else 1
        default_day = min(default_day, max_day)
        day_key = f"alert_day_select_{year}_{month}"
        day_pick = st.session_state.get(day_key, f"{default_day}일")
        day_num = int(day_pick[:-1])
        day_options = [f"{d}일" for d in range(1, max_day + 1)]
        selected_date = date(year, month, day_num)

        alerts = list_room_alerts(room["id"], selected_date)

        if any(alert["severity"] == "critical" and not alert["read"] for alert in alerts):
            st.markdown(
                f"""
                <div class="ts-alert-banner">{_FAIL_ICON}
                  <p>제어 실패로 확인이 필요한 알림입니다.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with st.container(key="ts_dash_alert_card", border=True):
            label_col, year_col, month_col, day_col = st.columns(
                [2.4, 1, 1, 1], vertical_alignment="center"
            )
            with year_col:
                st.selectbox(
                    "년도", year_options, index=year_options.index(f"{year}년"),
                    key="alert_year_select", label_visibility="collapsed",
                )
            with month_col:
                st.selectbox(
                    "월", month_options, index=month_options.index(f"{month}월"),
                    key="alert_month_select", label_visibility="collapsed",
                )
            with day_col:
                # Keyed per (year, month) so switching to a shorter month always
                # remounts a fresh widget with a valid default index, instead of
                # a stale display value (e.g. "31일") lingering from a widget
                # whose options no longer include it.
                st.selectbox(
                    "일", day_options, index=day_options.index(f"{day_num}일"),
                    key=day_key, label_visibility="collapsed",
                )
            with label_col:
                date_prefix = "오늘 " if selected_date == today else ""
                st.markdown(
                    f'<p class="ts-alert-date-label">{date_prefix}{month}월 {day_num}일</p>',
                    unsafe_allow_html=True,
                )

            if alerts:
                clicked_alert_id = None
                for alert in alerts:
                    read_class = "is-read" if alert["read"] else "is-unread"
                    severity_class = "is-critical" if alert["severity"] == "critical" else "is-warning"
                    icon = _FAIL_ICON if alert["severity"] == "critical" else _ATTENTION_ICON
                    dot = "" if alert["read"] else '<span class="ts-alert-unread-dot"></span>'
                    time_label = f'{alert["timestamp"].hour}:{alert["timestamp"].minute:02d}'
                    with st.container(key=f"ts_dash_alert_row_{alert['id']}"):
                        st.markdown(
                            f"""
                            <div class="ts-alert-row">
                              <span class="ts-alert-content {severity_class} {read_class}">
                                {icon}<span class="ts-alert-title">{alert["title"]}</span>{dot}
                              </span>
                              <span class="ts-alert-time">{time_label}</span>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                        if not alert["read"]:
                            if st.button(alert["title"], key=f"alert_mark_read_{alert['id']}", width="stretch"):
                                clicked_alert_id = alert["id"]
                if clicked_alert_id:
                    mark_alert_read(clicked_alert_id)
                    st.rerun()
            else:
                st.markdown(
                    '<p class="ts-dash-list-empty">해당 날짜의 알림이 없습니다</p>',
                    unsafe_allow_html=True,
                )
