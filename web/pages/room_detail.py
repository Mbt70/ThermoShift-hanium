import sys
from datetime import date
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from app.components.alert_store import active_alert_count, list_alerts
from app.components.control_log_store import list_logs, method_label
from app.components.room_store import (
    comfort_index,
    comfort_label,
    environment_snapshot,
    list_rooms,
    relative_updated,
    room_status,
    set_control_mode,
    set_target_temperature,
    system_judgment,
    trend_series,
)
from app.components.schedule_store import list_today_schedules
from components.auth_store import current_user_email, is_logged_in
from components.dash_shell import render_sidebar, render_topbar
from components.mobile_ui import apply_mobile_styles, recolored_icon_data_uri

_THERMO_ICON = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 14.5V4a2 2 0 1 0-4 0v10.5a4 4 0 1 0 4 0Z"/><path d="M12 14.5v-7"/></svg>'
)
_DROPLET_ICON = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 2.5c4 5 7 8.5 7 12.5a7 7 0 0 1-14 0c0-4 3-7.5 7-12.5Z"/></svg>'
)
_CLOUD_ICON = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M7 18h10a4 4 0 0 0 .5-7.97A5.5 5.5 0 0 0 7.16 9.1 4 4 0 0 0 7 18Z"/></svg>'
)
_BOLT_ICON = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M13 2 4 14h6l-1 8 9-12h-6l1-8Z"/></svg>'
)
_CHIP_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="7" y="7" width="10" height="10" rx="1.5"/>'
    '<path d="M9.5 7V4M14.5 7V4M9.5 20v-3M14.5 20v-3M7 9.5H4M7 14.5H4M20 9.5h-3M20 14.5h-3"/></svg>'
)
_CALENDAR_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="4" y="5.5" width="16" height="14" rx="2"/><path d="M4 9.5h16M8 3.5v3M16 3.5v3"/></svg>'
)
_LOG_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="5" y="3.5" width="14" height="17" rx="2"/><path d="M8.5 8h7M8.5 12h7M8.5 16h4"/></svg>'
)
_ALERT_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="12" cy="12" r="9"/><path d="M12 8v5"/><circle cx="12" cy="16" r="0.5" fill="currentColor"/></svg>'
)

_CONTROL_MODES = (
    ("monitoring", "모니터", "monitoring.svg"),
    ("manual", "수동", "back_hand.svg"),
    ("rule", "규칙", "rule-based.svg"),
    ("predictive", "예측", "predictive.svg"),
)
_MODE_ICON_INACTIVE = "#98a1ab"
_MODE_ICON_ACTIVE = "#ffffff"

_STATUS_CLASS = {"정상": "ok", "주의": "warn", "오류": "err"}


def _trend_chart(temps: list[float], co2s: list[float], target: float) -> alt.LayerChart:
    idx = list(range(len(temps)))
    temp_df = pd.DataFrame({"분": idx, "값": temps})
    co2_df = pd.DataFrame({"분": idx, "값": co2s})
    target_df = pd.DataFrame({"y": [target]})

    temp_line = (
        alt.Chart(temp_df)
        .mark_line(color="#171a21", strokeWidth=2.4)
        .encode(
            x=alt.X("분:Q", axis=None),
            y=alt.Y("값:Q", title="온도 (°C)", scale=alt.Scale(zero=False)),
            tooltip=[alt.Tooltip("값:Q", title="온도 (°C)")],
        )
    )
    target_rule = (
        alt.Chart(target_df)
        .mark_rule(color="#d99a22", strokeWidth=1.4, strokeDash=[5, 4])
        .encode(y=alt.Y("y:Q"))
    )
    co2_line = (
        alt.Chart(co2_df)
        .mark_line(color="#5f84c4", strokeWidth=2, strokeDash=[2, 3])
        .encode(
            x=alt.X("분:Q", axis=None),
            y=alt.Y("값:Q", title="CO₂ (ppm)", scale=alt.Scale(zero=False)),
            tooltip=[alt.Tooltip("값:Q", title="CO₂ (ppm)")],
        )
    )
    temp_group = alt.layer(temp_line, target_rule)
    return (
        alt.layer(temp_group, co2_line)
        .resolve_scale(y="independent")
        .properties(height=260)
        .configure_axis(labelFont="Inter", titleFont="Inter", grid=True, gridColor="#eef2f4")
        .configure_view(strokeWidth=0)
    )


apply_mobile_styles("room_detail", shared=("dash_shell",))

if not is_logged_in():
    st.switch_page("pages/login.py")

rooms = list_rooms(current_user_email())

selected_id = st.session_state.get("_web_selected_room")
if selected_id and not any(r["id"] == selected_id for r in rooms):
    selected_id = None
if selected_id is None and rooms:
    selected_id = rooms[0]["id"]
    st.session_state["_web_selected_room"] = selected_id

room = next((r for r in rooms if r["id"] == selected_id), None) if selected_id else None

sidebar_col, main_col = st.columns([1, 4], gap="small")

with sidebar_col:
    render_sidebar("room_detail")

with main_col:
    render_topbar("공간 상세", alert_count=active_alert_count())

    if room is None:
        st.switch_page("pages/devices.py")
    else:
        with st.container(key="ts_dash_room_switch"):
            names = [r["name"] for r in rooms]
            current_index = next((i for i, r in enumerate(rooms) if r["id"] == room["id"]), 0)
            picked = st.selectbox(
                "공간 선택", names, index=current_index, key="room_detail_select", label_visibility="collapsed"
            )
            picked_room = next((r for r in rooms if r["name"] == picked), room)
            if picked_room["id"] != room["id"]:
                st.session_state["_web_selected_room"] = picked_room["id"]
                st.rerun()

        status = room_status(room)
        status_class = _STATUS_CLASS.get(status, "ok")
        auto_class = "is-active" if room.get("auto_control") else ""

        header_col, chip_col = st.columns([3, 2], gap="small", vertical_alignment="center")
        with header_col:
            st.markdown(
                f"""
                <div class="ts-dash-title-row">
                  <h1 class="ts-dash-room-title">{room["name"]}</h1>
                  <span class="ts-dash-status-badge ts-dash-status-{status_class}">{status}</span>
                </div>
                <p class="ts-dash-room-location">{room["location"]}</p>
                """,
                unsafe_allow_html=True,
            )
        with chip_col:
            st.markdown(
                f"""
                <div class="ts-dash-chips">
                  <span class="ts-dash-chip">업데이트 {relative_updated(room)}</span>
                  <span class="ts-dash-chip ts-dash-chip-auto {auto_class}">자동 제어</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

        snapshot = environment_snapshot(room)
        tiles = [
            (_THERMO_ICON, "온도", f"{snapshot['temperature']:.1f}", "°C"),
            (_DROPLET_ICON, "습도", f"{snapshot['humidity']:.0f}", "%"),
            (_CLOUD_ICON, "CO₂", f"{snapshot['co2']:.0f}", "ppm"),
            (_BOLT_ICON, "전력", f"{snapshot['power']:.2f}", "kW"),
        ]
        tiles_html = "".join(
            f'<div class="ts-dash-tile">'
            f'<p class="ts-dash-tile-label">{icon}{label}</p>'
            f'<p class="ts-dash-tile-value">{value}<span class="ts-dash-tile-unit">{unit}</span></p>'
            f"</div>"
            for icon, label, value, unit in tiles
        )
        st.markdown(f'<div class="ts-dash-tile-grid">{tiles_html}</div>', unsafe_allow_html=True)

        score = comfort_index(room)
        label = comfort_label(score)
        label_color = {"좋음": "var(--success)", "보통": "var(--warning)", "나쁨": "var(--danger)"}[label]
        circumference = 326.73
        dash = circumference * score / 100
        headline, subline = system_judgment(room)

        comfort_col, judgment_col = st.columns([1, 2], gap="medium")
        with comfort_col:
            with st.container(key="ts_dash_comfort_card", border=True):
                st.markdown(
                    f"""
                    <p class="ts-dash-card-title">쾌적도 지수</p>
                    <div class="ts-dash-gauge-wrap">
                      <svg viewBox="0 0 120 120" class="ts-dash-gauge-ring">
                        <circle cx="60" cy="60" r="52" stroke="var(--border)" stroke-width="14" fill="none" />
                        <circle cx="60" cy="60" r="52" stroke="{label_color}" stroke-width="14" fill="none"
                                stroke-linecap="round" stroke-dasharray="{dash:.2f} {circumference:.2f}"
                                transform="rotate(-90 60 60)" />
                      </svg>
                      <div class="ts-dash-gauge-center">
                        <span class="ts-dash-gauge-score">{score}</span>
                        <span class="ts-dash-gauge-label">{label}</span>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        with judgment_col:
            with st.container(key="ts_dash_judgment_card", border=True):
                st.markdown(
                    f"""
                    <p class="ts-dash-card-title">{_CHIP_ICON}시스템 판단 <span class="ts-dash-badge">LLM</span></p>
                    <p class="ts-dash-judgment-headline">{headline}</p>
                    <p class="ts-dash-judgment-sub">{subline}</p>
                    """,
                    unsafe_allow_html=True,
                )

        mode_col, target_col = st.columns([2, 1], gap="medium")
        with mode_col:
            with st.container(key="ts_dash_mode_card", border=True):
                st.markdown('<p class="ts-dash-card-title">제어 모드</p>', unsafe_allow_html=True)
                current_mode = room.get("control_mode", "rule")
                clicked_mode = None
                mode_cols = st.columns(4, gap="small")
                for col, (mode_id, mode_label, icon_file) in zip(mode_cols, _CONTROL_MODES):
                    with col:
                        with st.container(key=f"ts_dash_mode_{mode_id}"):
                            is_mode_active = mode_id == current_mode
                            icon_color = _MODE_ICON_ACTIVE if is_mode_active else _MODE_ICON_INACTIVE
                            icon_uri = recolored_icon_data_uri(icon_file, icon_color)
                            active_mode_class = "is-active" if is_mode_active else ""
                            st.markdown(
                                f"""
                                <div class="ts-dash-mode-item {active_mode_class}">
                                  <div class="ts-dash-mode-icon-wrap"><img src="{icon_uri}" alt="" /></div>
                                  <p class="ts-dash-mode-label">{mode_label}</p>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )
                            if st.button(mode_label, key=f"dash_mode_btn_{mode_id}", use_container_width=True):
                                clicked_mode = mode_id
                if clicked_mode and clicked_mode != current_mode:
                    set_control_mode(room["id"], clicked_mode)
                    st.rerun()
        with target_col:
            with st.container(key="ts_dash_target_card", border=True):
                st.markdown('<p class="ts-dash-card-title">목표 온도</p>', unsafe_allow_html=True)
                minus_col, value_col, plus_col = st.columns([1, 2, 1], vertical_alignment="center")
                with minus_col:
                    if st.button("−", key="dash_target_minus", use_container_width=True):
                        set_target_temperature(room["id"], max(16, room["target_temperature"] - 1))
                        st.rerun()
                with value_col:
                    st.markdown(
                        f'<p class="ts-dash-target-value">{room["target_temperature"]}°</p>',
                        unsafe_allow_html=True,
                    )
                with plus_col:
                    if st.button("+", key="dash_target_plus", use_container_width=True):
                        set_target_temperature(room["id"], min(30, room["target_temperature"] + 1))
                        st.rerun()

        with st.container(key="ts_dash_trend_card", border=True):
            st.markdown('<p class="ts-dash-card-title">30분 추이</p>', unsafe_allow_html=True)
            temps, co2s = trend_series(room)
            st.altair_chart(
                _trend_chart(temps, co2s, room["target_temperature"]),
                use_container_width=True,
            )

        schedules = list_today_schedules(room["id"])
        logs = list_logs(room["id"], date.today())
        recent_logs = list(reversed(logs))[:6]
        alerts = list_alerts()
        alert_count = active_alert_count()

        schedule_col, activity_col = st.columns(2, gap="medium")
        with schedule_col:
            with st.container(key="ts_dash_schedule_card", border=True):
                st.markdown(
                    f'<p class="ts-dash-card-title">{_CALENDAR_ICON}오늘의 예약</p>',
                    unsafe_allow_html=True,
                )
                if schedules:
                    rows = "".join(
                        f'<div class="ts-dash-list-row">'
                        f'<span class="ts-dash-list-primary">{s["start_time"]} - {s["end_time"]}</span>'
                        f'<span class="ts-dash-list-secondary">목표 {s["target_temperature"]}°C</span>'
                        f"</div>"
                        for s in schedules
                    )
                    st.markdown(rows, unsafe_allow_html=True)
                else:
                    st.markdown(
                        '<p class="ts-dash-list-empty">오늘 예약된 냉방이 없습니다</p>',
                        unsafe_allow_html=True,
                    )
        with activity_col:
            with st.container(key="ts_dash_activity_card", border=True):
                st.markdown(
                    f"""
                    <p class="ts-dash-card-title">{_LOG_ICON}최근 제어 로그
                      <span class="ts-dash-badge ts-dash-badge-muted">오늘 {len(logs)}건</span>
                    </p>
                    """,
                    unsafe_allow_html=True,
                )
                if recent_logs:
                    rows = "".join(
                        f'<div class="ts-dash-list-row">'
                        f'<span class="ts-dash-list-primary">{"✓" if log["success"] else "✕"} {log["content"]}</span>'
                        f'<span class="ts-dash-list-secondary">{method_label(log["method"])} · '
                        f'{log["timestamp"].hour}:{log["timestamp"].minute:02d}</span>'
                        f"</div>"
                        for log in recent_logs
                    )
                    st.markdown(rows, unsafe_allow_html=True)
                else:
                    st.markdown(
                        '<p class="ts-dash-list-empty">오늘 기록된 제어 로그가 없습니다</p>',
                        unsafe_allow_html=True,
                    )

        with st.container(key="ts_dash_alert_card", border=True):
            st.markdown(
                f"""
                <p class="ts-dash-card-title">{_ALERT_ICON}활성 알림
                  <span class="ts-dash-badge ts-dash-badge-danger">{alert_count}건</span>
                </p>
                """,
                unsafe_allow_html=True,
            )
            if alerts:
                rows = "".join(
                    f'<div class="ts-dash-list-row">'
                    f'<span class="ts-dash-list-primary">{a["title"]}</span>'
                    f'<span class="ts-dash-list-secondary">{a["room"]} · {a["time"]}</span>'
                    f"</div>"
                    for a in alerts
                )
                st.markdown(rows, unsafe_allow_html=True)
            else:
                st.markdown(
                    '<p class="ts-dash-list-empty">활성 알림이 없습니다</p>',
                    unsafe_allow_html=True,
                )
