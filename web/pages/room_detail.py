import random
import sys
from datetime import date
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from app.components.room_store import (
    comfort_index,
    environment_snapshot,
    list_rooms,
    set_target_temperature,
    system_judgment,
    trend_series,
)
from app.components.schedule_store import list_today_schedules, schedule_status
from components.auth_store import current_user_email, is_logged_in
from components.dash_shell import render_sidebar
from components.mobile_ui import apply_mobile_styles, icon_data_uri

_KPI_ICON_FILES = {
    "temp": "temperture.svg",
    "co2": "co2.svg",
    "occupancy": "web_door.svg",
    "power": "web_bolt.svg",
}
_CHECK_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" '
    'stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5 10 17 19 7"/></svg>'
)
_WARN_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 4 3 20h18L12 4Z"/><path d="M12 10.5v4M12 17.5v.1"/></svg>'
)
_ARROW_DOWN_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" '
    'stroke-linecap="round" stroke-linejoin="round"><path d="M6 8l12 12M18 20H9M18 20v-9"/></svg>'
)
_ARROW_UP_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" '
    'stroke-linecap="round" stroke-linejoin="round"><path d="M6 16 18 4M18 4H9M18 4v9"/></svg>'
)
_HUMIDITY_ICON = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 2.5c4 5 7 8.5 7 12.5a7 7 0 0 1-14 0c0-4 3-7.5 7-12.5Z"/></svg>'
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
_CHEVRON_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 5l7 7-7 7"/></svg>'
)


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
        .mark_line(color="#5f84c4", strokeWidth=2)
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
        .properties(height=210)
        .configure_axis(labelFont="Inter", titleFont="Inter", grid=True, gridColor="#eef2f4", labelFontSize=9)
        .configure_view(strokeWidth=0)
    )


apply_mobile_styles("room_detail", shared=("dash_shell", "home"))

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
    if not rooms or room is None:
        st.switch_page("pages/devices.py")
    else:
        snapshot = environment_snapshot(room)
        occupied = bool(room.get("occupied"))
        occupancy_estimate = random.Random(f"occ-head-{room['id']}").randint(1, 6) if occupied else 0
        occupancy_rate = random.Random(f"occ-rate-{room['id']}-{date.today()}").randint(60, 95) if occupied else 0
        power_delta_pct = round(random.Random(f"power-yday-{room['id']}-{date.today()}").uniform(-9, 6), 1)
        co2_ok = snapshot["co2"] < 700
        target_ok = abs(snapshot["temperature"] - room["target_temperature"]) <= 1.5

        title_col, select_col, spacer_col = st.columns([0.6, 0.8, 4.4], vertical_alignment="center")
        with title_col:
            st.markdown('<h1 class="ts-dash-topbar-title">공간</h1>', unsafe_allow_html=True)
        with select_col:
            names = [r["name"] for r in rooms]
            current_index = next((i for i, r in enumerate(rooms) if r["id"] == room["id"]), 0)
            picked = st.selectbox(
                "공간 선택", names, index=current_index, key="roomdetail_top_room_select", label_visibility="collapsed"
            )
            picked_room = next((r for r in rooms if r["name"] == picked), room)
            if picked_room["id"] != room["id"]:
                st.session_state["_web_selected_room"] = picked_room["id"]
                st.rerun()

        kpi_items = [
            (
                "temp",
                "온도",
                f"{snapshot['temperature']:.1f}",
                "°C",
                "is-positive" if target_ok else "is-negative",
                f"{_CHECK_ICON}목표 {room['target_temperature']}°C 근접"
                if target_ok
                else f"{_WARN_ICON}목표 {room['target_temperature']}°C 미달",
            ),
            (
                "co2",
                "CO₂",
                f"{snapshot['co2']:.0f}",
                "ppm",
                "is-positive" if co2_ok else "is-negative",
                f"{_CHECK_ICON}기준 근접" if co2_ok else f"{_WARN_ICON}기준 초과",
            ),
            ("occupancy", "재실추정", f"{occupancy_estimate}", "명", "", f"재실률 {occupancy_rate}%"),
            ("humidity", "습도", f"{snapshot['humidity']:.0f}", "%", "is-positive", f"{_CHECK_ICON}적정"),
            (
                "power",
                "총 HVAC 전력",
                f"{snapshot['power']:.1f}",
                "kW",
                "is-positive" if power_delta_pct < 0 else "is-negative",
                f"{_ARROW_DOWN_ICON if power_delta_pct < 0 else _ARROW_UP_ICON}어제 대비 {power_delta_pct:+.1f}%",
            ),
        ]
        kpi_cols = st.columns(5, gap="small")
        for col, (slug, label, value, unit, sub_class, sub) in zip(kpi_cols, kpi_items):
            with col:
                with st.container(key=f"ts_dash_kpi_card_{slug}", border=True):
                    icon_html = (
                        f'<span class="ts-dash-kpi-icon ts-room-humidity-icon">{_HUMIDITY_ICON}</span>'
                        if slug == "humidity"
                        else f'<img class="ts-dash-kpi-icon" src="{icon_data_uri(_KPI_ICON_FILES[slug])}" alt="" />'
                    )
                    st.markdown(
                        f"""
                        <div class="ts-dash-kpi-head">
                          <span class="ts-dash-kpi-label">{label}</span>
                          {icon_html}
                        </div>
                        <p class="ts-dash-kpi-value">{value}<span class="ts-dash-kpi-unit">{unit}</span></p>
                        <p class="ts-dash-kpi-sub {sub_class}">{sub}</p>
                        """,
                        unsafe_allow_html=True,
                    )

        left_col, right_col = st.columns([2, 1], gap="small")

        with left_col:
            with st.container(key="ts_dash_trend_card", border=True):
                head_col, legend_col = st.columns([1.4, 1.6], vertical_alignment="center")
                with head_col:
                    st.markdown('<p class="ts-dash-card-title" style="margin:0;">30분 추이</p>', unsafe_allow_html=True)
                with legend_col:
                    st.markdown(
                        """
                        <div class="ts-trend-legend">
                          <span class="ts-trend-legend-item ts-trend-legend-temp">온도</span>
                          <span class="ts-trend-legend-item ts-trend-legend-co2">CO₂</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                temps, co2s = trend_series(room)
                st.altair_chart(
                    _trend_chart(temps, co2s, room["target_temperature"]),
                    width="stretch",
                )

                schedules = list_today_schedules(room["id"])
                res_head_col, res_link_col = st.columns([2, 1], vertical_alignment="center")
                with res_head_col:
                    st.markdown(
                        f'<p class="ts-dash-card-title" style="margin:0;">{_CALENDAR_ICON}예약 냉방</p>',
                        unsafe_allow_html=True,
                    )
                with res_link_col:
                    if st.button("예약 목록보기", key="dash_reservation_all", width="stretch"):
                        st.toast("예약 목록 페이지는 곧 제공될 예정이에요", icon="🛠️")
                if schedules:
                    rows = "".join(
                        f'<div class="ts-room-reservation-row">'
                        f'<span class="ts-room-reservation-time">{s["start_time"]}–{s["end_time"]}</span>'
                        f'<span class="ts-room-reservation-status is-{"done" if schedule_status(s) == "완료" else "active" if schedule_status(s) == "진행 중" else "pending"}">'
                        f'{schedule_status(s)}</span>'
                        f'<span class="ts-room-reservation-chevron">{_CHEVRON_ICON}</span>'
                        f"</div>"
                        for s in schedules
                    )
                    st.markdown(rows, unsafe_allow_html=True)
                else:
                    st.markdown(
                        '<p class="ts-dash-list-empty">오늘 예약된 냉방이 없습니다</p>',
                        unsafe_allow_html=True,
                    )
                if st.button("＋ 새 예약 추가", key="dash_reservation_new", width="stretch"):
                    st.toast("예약 생성 기능은 곧 제공될 예정이에요", icon="🛠️")

        with right_col:
            with st.container(key="ts_room_manual_card", border=True):
                st.markdown(
                    f'<p class="ts-dash-card-title">'
                    f'<img class="ts-dash-kpi-icon" src="{icon_data_uri("snow.svg")}" alt="" />에어컨 수동 제어</p>',
                    unsafe_allow_html=True,
                )
                minus_col, value_col, plus_col = st.columns([1, 2, 1], vertical_alignment="center")
                with minus_col:
                    if st.button("−", key="dash_target_minus", width="stretch"):
                        set_target_temperature(room["id"], max(16, room["target_temperature"] - 1))
                        st.rerun()
                with value_col:
                    st.markdown(
                        f"""
                        <p class="ts-room-manual-value">{room["target_temperature"]}°</p>
                        <p class="ts-room-manual-caption">예약 시간 동안 유지</p>
                        """,
                        unsafe_allow_html=True,
                    )
                with plus_col:
                    if st.button("+", key="dash_target_plus", width="stretch"):
                        set_target_temperature(room["id"], min(30, room["target_temperature"] + 1))
                        st.rerun()
                st.markdown(
                    '<p class="ts-room-manual-note">수동 제어는 자동 제어보다 항상 우선 실행됩니다</p>',
                    unsafe_allow_html=True,
                )

            with st.container(key="ts_room_ai_card", border=True):
                st.markdown(
                    f'<p class="ts-dash-card-title">{_CHIP_ICON}AI 운영 설명</p>',
                    unsafe_allow_html=True,
                )
                headline, subline = system_judgment(room)
                st.markdown(
                    f"""
                    <p class="ts-dash-judgment-headline">{headline}</p>
                    <p class="ts-dash-judgment-sub">{subline}</p>
                    """,
                    unsafe_allow_html=True,
                )

        comfort = comfort_index(room)
        with st.container(key="ts_dash_summary_card", border=True):
            st.markdown('<p class="ts-dash-card-title">KPI 요약 (오늘)</p>', unsafe_allow_html=True)
            summary_items = [
                ("power", "HVAC 전력 사용량", f"{snapshot['power'] * 24:.0f}kWh"),
                ("temp", "평균 온도", f"{snapshot['temperature']:.1f}°C"),
                ("co2", "평균 CO₂", f"{snapshot['co2']:.0f}ppm"),
                ("occupancy", "공간 사용률", f"{occupancy_rate}%"),
                (None, "종합 쾌적도 지수", f"{comfort}/100"),
            ]
            items_html = "".join(
                f'<div class="ts-dash-summary-item">'
                f'<div class="ts-dash-summary-head">'
                f'<span class="ts-dash-summary-label">{label}</span>'
                + (f'<img src="{icon_data_uri(_KPI_ICON_FILES[slug])}" alt="" />' if slug else "")
                + "</div>"
                f'<span class="ts-dash-summary-value">{value}</span>'
                f"</div>"
                for slug, label, value in summary_items
            )
            st.markdown(f'<div class="ts-dash-summary-grid">{items_html}</div>', unsafe_allow_html=True)
