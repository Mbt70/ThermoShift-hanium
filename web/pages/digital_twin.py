import random
import sys
from datetime import date, datetime
from pathlib import Path

import streamlit as st

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from app.components.control_log_store import list_logs
from app.components.room_store import (
    comfort_index,
    environment_snapshot,
    list_rooms,
    set_control_mode,
    system_judgment,
)
from components.auth_store import current_user_id, is_logged_in
from components.dash_shell import render_sidebar
from components.mobile_ui import apply_mobile_styles, icon_data_uri, recolored_icon_data_uri

_CONTROL_MODES = (
    ("monitoring", "모니터링", "monitoring.svg"),
    ("manual", "수동제어", "back_hand.svg"),
    ("rule", "규칙 제어", "rule-based.svg"),
    ("predictive", "예측 제어", "predictive.svg"),
)
_MODE_ICON_INACTIVE = "#98a1ab"
_MODE_ICON_ACTIVE = "#ffffff"

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
_CUBE_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 3 20 7.5V16.5L12 21 4 16.5V7.5Z"/><path d="M4 7.5 12 12 20 7.5M12 12V21"/></svg>'
)
_CFD_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M3 12h4l2-7 4 14 2-7h6"/></svg>'
)
_LIST_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 10h8M8 14h5"/></svg>'
)


apply_mobile_styles("digital_twin", shared=("dash_shell", "home", "room_detail"))

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
    render_sidebar("digital_twin")

with main_col:
    if not rooms or room is None:
        st.switch_page("pages/devices.py")
    else:
        snapshots = {r["id"]: environment_snapshot(r) for r in rooms}
        room_count = len(rooms)
        avg_temp = sum(s["temperature"] for s in snapshots.values()) / room_count
        avg_co2 = sum(s["co2"] for s in snapshots.values()) / room_count
        avg_humidity = sum(s["humidity"] for s in snapshots.values()) / room_count
        total_power = sum(s["power"] for s in snapshots.values())
        active_count = sum(1 for r in rooms if r.get("occupied"))
        occupancy_rate = round(active_count / room_count * 100) if room_count else 0
        # No real per-room headcount sensor exists - synthesize a plausible
        # estimate per occupied room, seeded so it stays stable across
        # reruns (same deterministic-seed approach room_store's own mocks
        # use elsewhere in this app).
        occupancy_estimate = sum(
            random.Random(f"occ-head-{r['id']}").randint(1, 4) for r in rooms if r.get("occupied")
        )
        power_delta_pct = round(random.Random(f"power-yday-{date.today()}").uniform(-9, 6), 1)

        title_col, select_col, spacer_col = st.columns([0.6, 0.8, 4.4], vertical_alignment="center")
        with title_col:
            st.markdown('<h1 class="ts-dash-topbar-title">공간</h1>', unsafe_allow_html=True)
        with select_col:
            names = [r["name"] for r in rooms]
            current_index = next((i for i, r in enumerate(rooms) if r["id"] == room["id"]), 0)
            picked = st.selectbox(
                "공간 선택", names, index=current_index, key="twin_top_room_select", label_visibility="collapsed"
            )
            picked_room = next((r for r in rooms if r["name"] == picked), room)
            if picked_room["id"] != room["id"]:
                st.session_state["_web_selected_room"] = picked_room["id"]
                st.rerun()

        co2_ok = avg_co2 < 700
        kpi_items = [
            ("temp", "온도", f"{avg_temp:.1f}", "°C", "is-positive", f"{_CHECK_ICON}목표 24°C 근접"),
            (
                "co2",
                "CO₂",
                f"{avg_co2:.0f}",
                "ppm",
                "is-positive" if co2_ok else "is-negative",
                f"{_CHECK_ICON}기준 이내" if co2_ok else f"{_WARN_ICON}기준 근접",
            ),
            ("occupancy", "재실추정", f"{occupancy_estimate}", "명", "", f"재실률 {occupancy_rate}%"),
            ("humidity", "습도", f"{avg_humidity:.0f}", "%", "is-positive", f"{_CHECK_ICON}적정"),
            (
                "power",
                "총 HVAC 전력",
                f"{total_power:.1f}",
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
                        f'<span class="ts-dash-kpi-icon ts-twin-humidity-icon">{_HUMIDITY_ICON}</span>'
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

        twin_col, side_col = st.columns([2, 1], gap="small")

        with twin_col:
            with st.container(key="ts_dash_twin_view_card", border=True):
                head_col, tab_col = st.columns([2.6, 1.6], vertical_alignment="center")
                with head_col:
                    st.markdown(
                        f'<p class="ts-dash-card-title" style="margin:0;">{_CUBE_ICON}3D 디지털 트윈</p>',
                        unsafe_allow_html=True,
                    )
                with tab_col:
                    st.segmented_control(
                        "twin_view_mode",
                        options=["3D", "sensor", "히트맵"],
                        default="sensor",
                        key="twin_view_tab",
                        label_visibility="collapsed",
                    )
                st.markdown(
                    """
                    <div class="ts-dash-heat-legend">
                      <span>18°C</span>
                      <div class="ts-dash-heat-legend-bar"></div>
                      <span>30°C</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        with side_col:
            with st.container(key="ts_dash_twin_ai_card", border=True):
                st.markdown(
                    f'<p class="ts-dash-card-title">{_CHIP_ICON}AI 운영 설명 <span class="ts-dash-badge">LLM</span></p>',
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

            state_col, mode_col = st.columns(2, gap="small")
            with state_col:
                with st.container(key="ts_dash_twin_state_card", border=True):
                    st.markdown(
                        f'<p class="ts-dash-card-title">{_LIST_ICON}현재 제어 상태</p>', unsafe_allow_html=True
                    )
                    logs_today = list_logs(room["id"], date.today())
                    latest_log = logs_today[-1] if logs_today else None
                    aircon_state = "AC ON" if room.get("aircon_on") else "AC OFF"
                    latest_text = (
                        f'{latest_log["timestamp"].hour}:{latest_log["timestamp"].minute:02d} {latest_log["content"]}'
                        if latest_log
                        else "기록 없음"
                    )
                    verify_text = "성공" if (latest_log is None or latest_log.get("success", True)) else "실패"
                    rows = [
                        ("Ac 상태", aircon_state, f'설정 온도 {room.get("target_temperature", 24)}'),
                        ("최근 명령", latest_text, ""),
                        ("검증 결과", verify_text, ""),
                    ]
                    rows_html = "".join(
                        f'<div class="ts-dash-list-row">'
                        f'<span class="ts-dash-list-secondary">{k}</span>'
                        f'<span class="ts-dash-list-primary">{v}'
                        + (f' <span class="ts-dash-list-secondary">{extra}</span>' if extra else "")
                        + "</span></div>"
                        for k, v, extra in rows
                    )
                    st.markdown(rows_html, unsafe_allow_html=True)

            with mode_col:
                with st.container(key="ts_dash_twin_mode_card", border=True):
                    st.markdown('<p class="ts-dash-card-title">제어 모드</p>', unsafe_allow_html=True)
                    current_mode = room.get("control_mode", "rule")
                    clicked_mode = None
                    mode_cols = st.columns(2, gap="small")
                    for i, (mode_id, mode_label, icon_file) in enumerate(_CONTROL_MODES):
                        with mode_cols[i % 2]:
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
                                if st.button(mode_label, key=f"dash_mode_btn_{mode_id}", width="stretch"):
                                    clicked_mode = mode_id
                    if clicked_mode and clicked_mode != current_mode:
                        set_control_mode(room["id"], clicked_mode)
                        st.rerun()

            with st.container(key="ts_dash_twin_cfd_card", border=True):
                title_col2, select_col2 = st.columns([2, 1.2], vertical_alignment="center")
                with title_col2:
                    st.markdown(
                        f'<p class="ts-dash-card-title" style="margin:0;">{_CFD_ICON}CFD</p>',
                        unsafe_allow_html=True,
                    )
                with select_col2:
                    st.selectbox(
                        "CFD 지표", ["온도", "기류"], key="twin_cfd_metric", label_visibility="collapsed"
                    )
                st.markdown('<div class="ts-twin-cfd-strip"></div>', unsafe_allow_html=True)

        comfort_avg = round(sum(comfort_index(r) for r in rooms) / room_count) if room_count else 0
        hours_elapsed = datetime.now().hour + datetime.now().minute / 60
        kwh_today = total_power * hours_elapsed

        with st.container(key="ts_dash_summary_card", border=True):
            st.markdown('<p class="ts-dash-card-title">KPI 요약 (오늘)</p>', unsafe_allow_html=True)
            summary_items = [
                ("power", "HVAC 전력 사용량", f"{kwh_today:.0f}kWh"),
                ("temp", "평균 온도", f"{avg_temp:.1f}°C"),
                ("co2", "평균 CO₂", f"{avg_co2:.0f}ppm"),
                ("occupancy", "공간 사용률", f"{occupancy_rate}%"),
                (None, "종합 쾌적도 지수", f"{comfort_avg}/100"),
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
