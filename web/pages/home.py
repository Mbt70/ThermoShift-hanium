import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from app.components.alert_store import alert_severity_counts
from app.components.room_store import (
    comfort_index,
    environment_snapshot,
    list_rooms,
    room_status,
    system_judgment,
)
from app.components.schedule_store import list_today_schedules
from components.auth_store import current_user_email, is_logged_in
from components.dash_shell import render_sidebar, render_topbar
from components.mobile_ui import apply_mobile_styles, icon_data_uri, recolored_icon_data_uri

# Pre-colored icon badges the user dropped into assets/icons for the KPI
# row/room cards/summary footer - used as-is (no recoloring) per their request.
_KPI_ICON_FILES = {
    "temp": "temperture.svg",
    "co2": "co2.svg",
    "active": "web_door.svg",
    "power": "web_bolt.svg",
    "alert": "web_error.svg",
}

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
_CHECK_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" '
    'stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5 10 17 19 7"/></svg>'
)
_BAR_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M5 19V11M12 19V5M19 19v-7"/></svg>'
)
_ARROW_DOWN_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" '
    'stroke-linecap="round" stroke-linejoin="round"><path d="M6 8l12 12M18 20H9M18 20v-9"/></svg>'
)
_ARROW_UP_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" '
    'stroke-linecap="round" stroke-linejoin="round"><path d="M6 16 18 4M18 4H9M18 4v9"/></svg>'
)
_WARN_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 4 3 20h18L12 4Z"/><path d="M12 10.5v4M12 17.5v.1"/></svg>'
)
_OFFLINE_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M4 4l16 16M8.5 8.5C6.6 9.5 5 11 4 13M20 13a12 12 0 0 0-3-3M16.7 10.4A8 8 0 0 0 12 9c-1 0-2 .18-2.9.5M12 17.5v.1"/></svg>'
)

_STATUS_CLASS = {"정상": "ok", "주의": "warn", "오류": "err"}
_METRICS = {"온도": "temperature", "CO2": "co2"}
# (unit kind, point count, axis date format)
_PERIODS = {
    "1일": ("hour", 24, "%H:%M"),
    "7일": ("day", 7, "%m/%d"),
    "30일": ("day", 30, "%m/%d"),
}
_SERIES_COLORS = {
    "평균 온도": "#3457be",
    "외기 온도": "#3fae66",
    "목표 온도": "#d99a22",
    "평균 CO₂": "#3457be",
    "목표 CO₂": "#d99a22",
}

# Heatmap scale for room thumbnails - shares the blue/teal/red stops already
# used by the grid's 18°C-30°C legend bar, so the thumbnail tint and the
# legend agree with each other.
_HEAT_STOPS = [(18.0, (91, 132, 196)), (24.0, (88, 164, 152)), (30.0, (230, 74, 69))]


def _temp_rgb(temp: float) -> tuple[int, int, int]:
    if temp <= _HEAT_STOPS[0][0]:
        return _HEAT_STOPS[0][1]
    if temp >= _HEAT_STOPS[-1][0]:
        return _HEAT_STOPS[-1][1]
    for (t0, c0), (t1, c1) in zip(_HEAT_STOPS, _HEAT_STOPS[1:]):
        if t0 <= temp <= t1:
            f = (temp - t0) / (t1 - t0)
            return tuple(round(c0[i] + (c1[i] - c0[i]) * f) for i in range(3))
    return _HEAT_STOPS[-1][1]


def _heat_thumb_style(room_id: str, temp: float) -> str:
    # No real floor-plan/render exists yet - stands in with a flat tint
    # (still keyed to the room's live temperature, same blue->teal->red
    # scale as the legend) plus a centered room icon, rather than a busy
    # gradient that read as an odd green blob.
    r, g, b = _temp_rgb(temp)
    tint = tuple(round(c + (255 - c) * 0.62) for c in (r, g, b))
    icon_uri = recolored_icon_data_uri("meeting_room.svg", f"rgba({r},{g},{b},0.55)")
    return (
        f"background: url('{icon_uri}') center/28px no-repeat, "
        f"rgb({tint[0]},{tint[1]},{tint[2]});"
    )


def _occupancy_rate(room: dict) -> int:
    # room_store only tracks a boolean "occupied" flag, no real utilization
    # metric - synthesize a plausible percentage for occupied rooms, seeded
    # by room id so it stays stable across reruns (same approach room_store
    # itself uses for its live-value mocks).
    if not room.get("occupied"):
        return 0
    return random.Random(f"occ-{room['id']}").randint(55, 92)


def _period_points(period_key: str) -> list[datetime]:
    unit, n, _fmt = _PERIODS[period_key]
    if unit == "hour":
        now = datetime.now().replace(minute=0, second=0, microsecond=0)
        return [now - timedelta(hours=n - i) for i in range(n + 1)]
    anchor = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    return [anchor - timedelta(days=n - 1 - i) for i in range(n)]


def _history_series(rooms: list[dict], snapshots: dict, metric: str, n_points: int, seed_suffix: str) -> list[float]:
    # No real historical store exists (room_store only ever holds the
    # room's *current* live values), so this synthesizes a plausible walk
    # that ends at today's real average - same deterministic-seed approach
    # room_store.trend_series already uses for its single-room 30-point chart.
    base = (
        sum(snapshots[r["id"]][metric] for r in rooms) / len(rooms)
        if rooms
        else (24.0 if metric == "temperature" else 700.0)
    )
    step = 0.3 if metric == "temperature" else 18
    rnd = random.Random(f"history-{metric}-{seed_suffix}-{len(rooms)}")
    value = base + rnd.uniform(-step * 3, step * 3)
    series = []
    for _ in range(n_points):
        value += rnd.uniform(-step, step)
        series.append(value)
    series[-1] = base
    return series


def _outdoor_series(main_series: list[float], seed_suffix: str) -> list[float]:
    # Outdoor temperature has no sensor/data source in this app - synthesized
    # as a cooler, more volatile walk loosely tracking the indoor average,
    # same synthesis approach as _history_series above.
    rnd = random.Random(f"outdoor-{seed_suffix}-{len(main_series)}")
    offset = rnd.uniform(-4.5, -1.5)
    series = []
    value = main_series[0] + offset + rnd.uniform(-1.0, 1.0)
    for indoor in main_series:
        value += rnd.uniform(-0.6, 0.6)
        value = value * 0.7 + (indoor + offset) * 0.3
        series.append(value)
    return series


def _timeline_chart(
    points: list[datetime],
    series: dict[str, list[float]],
    *,
    target: tuple[str, float] | None,
    metric_label: str,
    unit: str,
    date_format: str,
    y_domain: tuple[float, float] | None = None,
) -> alt.LayerChart:
    rows = [
        {"time": ts, "값": value, "구분": name}
        for name, values in series.items()
        for ts, value in zip(points, values)
    ]
    domain = list(series.keys()) + ([target[0]] if target else [])
    color_scale = alt.Scale(domain=domain, range=[_SERIES_COLORS.get(name, "#5f84c4") for name in domain])
    y_scale = alt.Scale(domain=list(y_domain), zero=False) if y_domain else alt.Scale(zero=False)

    line = (
        alt.Chart(pd.DataFrame(rows))
        .mark_line(strokeWidth=2.2)
        .encode(
            x=alt.X("time:T", title=None, axis=alt.Axis(format=date_format, grid=False)),
            y=alt.Y("값:Q", title=f"{metric_label} ({unit})", scale=y_scale),
            color=alt.Color("구분:N", scale=color_scale, legend=alt.Legend(title=None, orient="top")),
        )
    )
    layers = [line]
    if target is not None:
        target_label, target_value = target
        layers.append(
            alt.Chart(pd.DataFrame({"y": [target_value], "구분": [target_label]}))
            .mark_rule(strokeWidth=1.4, strokeDash=[5, 4])
            .encode(y=alt.Y("y:Q"), color=alt.Color("구분:N", scale=color_scale, legend=None))
        )
    return (
        alt.layer(*layers)
        .properties(height=250)
        .configure_axis(labelFont="Inter", titleFont="Inter", grid=True, gridColor="#eef2f4", labelFontSize=9)
        .configure_view(strokeWidth=0)
        .configure_legend(labelFont="Inter", symbolType="circle", labelFontSize=10, padding=2)
    )


apply_mobile_styles("home", shared=("dash_shell",))

if not is_logged_in():
    st.switch_page("pages/login.py")

rooms = list_rooms(current_user_email())
snapshots = {r["id"]: environment_snapshot(r) for r in rooms}
room_count = len(rooms)

avg_temp = sum(s["temperature"] for s in snapshots.values()) / room_count if room_count else 0.0
avg_co2 = sum(s["co2"] for s in snapshots.values()) / room_count if room_count else 0.0
total_power = sum(s["power"] for s in snapshots.values())
active_count = sum(1 for r in rooms if r.get("occupied"))
occupancy_rate = round(active_count / room_count * 100) if room_count else 0
severity = alert_severity_counts()
alert_total = severity["critical"] + severity["warning"]
power_delta_pct = round(random.Random(f"power-yday-{datetime.now().date()}").uniform(-9, 6), 1)

sidebar_col, main_col = st.columns([1, 4], gap="small")

with sidebar_col:
    render_sidebar("dashboard")

with main_col:
    render_topbar("대시보드", alert_count=alert_total)

    if not rooms:
        st.switch_page("pages/devices.py")
    else:
        temp_diff = avg_temp - 24
        temp_state = "근접" if abs(temp_diff) <= 1 else ("초과" if temp_diff > 0 else "미달")
        co2_ok = avg_co2 < 1000
        kpi_items = [
            (
                "temp",
                "평균 온도",
                f"{avg_temp:.1f}",
                "°C",
                "is-positive" if temp_state == "근접" else "is-negative",
                f"{_CHECK_ICON}목표 24°C {temp_state}",
            ),
            (
                "co2",
                "평균 CO₂",
                f"{avg_co2:.0f}",
                "ppm",
                "is-positive" if co2_ok else "is-negative",
                f"{_CHECK_ICON}목표 <1000ppm " + ("충족" if co2_ok else "초과"),
            ),
            (
                "active",
                "활성 공간",
                f"{active_count}",
                f"/{room_count}",
                "",
                f"{_BAR_ICON}재실률 {occupancy_rate}%",
            ),
            (
                "power",
                "총 HVAC 전력",
                f"{total_power:.1f}",
                "kW",
                "is-positive" if power_delta_pct < 0 else "is-negative",
                f"{_ARROW_DOWN_ICON if power_delta_pct < 0 else _ARROW_UP_ICON}어제 대비 {power_delta_pct:+.1f}%",
            ),
            (
                "alert",
                "경보 수",
                f"{alert_total}",
                "건",
                "is-negative" if alert_total else "",
                f"{_WARN_ICON}심각 {severity['critical']} · 주의 {severity['warning']}",
            ),
        ]
        kpi_cols = st.columns(5, gap="small")
        for col, (slug, label, value, unit, sub_class, sub) in zip(kpi_cols, kpi_items):
            with col:
                with st.container(key=f"ts_dash_kpi_card_{slug}", border=True):
                    st.markdown(
                        f"""
                        <div class="ts-dash-kpi-head">
                          <span class="ts-dash-kpi-label">{label}</span>
                          <img class="ts-dash-kpi-icon" src="{icon_data_uri(_KPI_ICON_FILES[slug])}" alt="" />
                        </div>
                        <p class="ts-dash-kpi-value">{value}<span class="ts-dash-kpi-unit">{unit}</span></p>
                        <p class="ts-dash-kpi-sub {sub_class}">{sub}</p>
                        """,
                        unsafe_allow_html=True,
                    )

        grid_col, timeline_col, side_col = st.columns([2, 2, 1], gap="small")

        with grid_col:
            with st.container(key="ts_dash_room_grid_card", border=True):
                st.markdown('<p class="ts-dash-card-title">공간 현황</p>', unsafe_allow_html=True)
                room_rows = [rooms[i : i + 2] for i in range(0, len(rooms), 2)]
                for row in room_rows:
                    row_cols = st.columns(2, gap="small")
                    for col, r in zip(row_cols, row):
                        snap = snapshots[r["id"]]
                        status = room_status(r)
                        status_class = _STATUS_CLASS.get(status, "ok")
                        usage_pct = _occupancy_rate(r)
                        with col:
                            with st.container(key=f"ts_dash_room_card_{r['id']}"):
                                st.markdown(
                                    f"""
                                    <div class="ts-dash-room-thumb" style="{_heat_thumb_style(r["id"], snap["temperature"])}"></div>
                                    <div class="ts-dash-room-card-head">
                                      <span class="ts-dash-room-card-name">{r["name"]}</span>
                                      <span class="ts-dash-status-badge ts-dash-status-{status_class}">{status}</span>
                                    </div>
                                    <div class="ts-dash-room-card-stats">
                                      <span><img src="{icon_data_uri("temperture.svg")}" alt="" />{snap["temperature"]:.1f}°C</span>
                                      <span><img src="{icon_data_uri("co2.svg")}" alt="" />CO₂ {snap["co2"]:.0f}ppm</span>
                                      <span><img src="{icon_data_uri("web_door.svg")}" alt="" />사용율 {usage_pct}%</span>
                                      <span><img src="{icon_data_uri("web_bolt.svg")}" alt="" />전력 {snap["power"]:.2f}kW</span>
                                    </div>
                                    """,
                                    unsafe_allow_html=True,
                                )
                                if st.button(r["name"], key=f"room_card_btn_{r['id']}", width="stretch"):
                                    st.session_state["_web_selected_room"] = r["id"]
                                    st.switch_page("pages/room_detail.py")
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

        with timeline_col:
            with st.container(key="ts_dash_timeline_card", border=True):
                title_col, metric_col, period_col = st.columns([2.2, 1.4, 1.4], vertical_alignment="center")
                with title_col:
                    st.markdown(
                        '<p class="ts-dash-card-title" style="margin:0;">과거 타임라인 변화</p>',
                        unsafe_allow_html=True,
                    )
                with metric_col:
                    metric_choice = st.selectbox(
                        "지표", list(_METRICS.keys()), key="dash_timeline_metric", label_visibility="collapsed"
                    )
                with period_col:
                    period_choice = st.selectbox(
                        "기간", list(_PERIODS.keys()), index=1, key="dash_timeline_period", label_visibility="collapsed"
                    )
                metric_key = _METRICS[metric_choice]
                _unit_kind, n_points, date_format = _PERIODS[period_choice]
                points = _period_points(period_choice)
                main_series = _history_series(rooms, snapshots, metric_key, len(points), period_choice)
                if metric_key == "temperature":
                    outdoor_series = _outdoor_series(main_series, period_choice)
                    chart = _timeline_chart(
                        points,
                        {"평균 온도": main_series, "외기 온도": outdoor_series},
                        target=("목표 온도", 24),
                        metric_label="평균 온도",
                        unit="°C",
                        date_format=date_format,
                        y_domain=(18, 30),
                    )
                else:
                    chart = _timeline_chart(
                        points,
                        {"평균 CO₂": main_series},
                        target=("목표 CO₂", 1000),
                        metric_label="평균 CO₂",
                        unit="ppm",
                        date_format=date_format,
                    )
                st.altair_chart(chart, width="stretch")

        with side_col:
            today_schedules = sorted(
                (
                    (r, s)
                    for r in rooms
                    for s in list_today_schedules(r["id"])
                ),
                key=lambda pair: pair[1]["start_time"],
            )
            with st.container(key="ts_dash_reservation_card", border=True):
                st.markdown(
                    f"""
                    <p class="ts-dash-card-title">{_CALENDAR_ICON}예약 냉방
                      <span class="ts-dash-badge">예약 {len(today_schedules)}건</span>
                    </p>
                    <p class="ts-dash-reservation-desc">예약한 시간에 맞춰 자동으로 냉방을 켜고, 설정한 온도를 유지해요</p>
                    """,
                    unsafe_allow_html=True,
                )
                reserve_col, reserve_all_col = st.columns(2, gap="small")
                with reserve_col:
                    if st.button("＋ 예약하기", key="dash_reservation_new", width="stretch"):
                        st.toast("예약 생성 기능은 곧 제공될 예정이에요", icon="🛠️")
                with reserve_all_col:
                    if st.button("전체보기", key="dash_reservation_all", width="stretch"):
                        st.toast("예약 목록 페이지는 곧 제공될 예정이에요", icon="🛠️")

            with st.container(key="ts_dash_ai_card", border=True):
                st.markdown(
                    f'<p class="ts-dash-card-title">{_CHIP_ICON}AI 운영 설명 <span class="ts-dash-badge">LLM</span></p>',
                    unsafe_allow_html=True,
                )
                flagged_rooms = [r for r in rooms if room_status(r) != "정상"]
                notable_room = flagged_rooms[0] if flagged_rooms else rooms[0]
                if not notable_room.get("sensor_connected", True):
                    headline, subline = "센서 응답이 없어 제어를 보류했습니다", "센서 재연결이 필요해요"
                else:
                    headline, subline = system_judgment(notable_room)
                st.markdown(
                    f"""
                    <p class="ts-dash-judgment-headline">[{notable_room["name"]}] {headline}</p>
                    <p class="ts-dash-judgment-sub">{subline}</p>
                    """,
                    unsafe_allow_html=True,
                )

        ranked = sorted(rooms, key=lambda r: snapshots[r["id"]]["power"], reverse=True)
        online_powers = [snapshots[r["id"]]["power"] for r in ranked if r.get("sensor_connected", True)]
        max_power = max(online_powers, default=0) or 1

        def _power_rows_html(room_list: list[dict]) -> str:
            rows = []
            for r in room_list:
                if not r.get("sensor_connected", True):
                    rows.append(
                        f'<div class="ts-dash-power-row">'
                        f'<span class="ts-dash-power-name">{r["name"]}</span>'
                        f'<div class="ts-dash-power-bar-track"><span class="ts-dash-power-offline-tag">'
                        f'{_OFFLINE_ICON}오프라인</span></div>'
                        f'<span class="ts-dash-power-value">-</span>'
                        f"</div>"
                    )
                    continue
                rows.append(
                    f'<div class="ts-dash-power-row">'
                    f'<span class="ts-dash-power-name">{r["name"]}</span>'
                    f'<div class="ts-dash-power-bar-track">'
                    f'<div class="ts-dash-power-bar-fill" style="width:{snapshots[r["id"]]["power"] / max_power * 100:.0f}%"></div>'
                    f"</div>"
                    f'<span class="ts-dash-power-value">{snapshots[r["id"]]["power"]:.2f}kW</span>'
                    f"</div>"
                )
            return "".join(rows)

        with st.container(key="ts_dash_power_rank_card", border=True):
            st.markdown(
                f'<p class="ts-dash-card-title"><img class="ts-dash-inline-icon" '
                f'src="{icon_data_uri("web_bolt.svg")}" alt="" />공간별 실시간 전력'
                f'<span class="ts-dash-badge ts-dash-badge-muted">kW · 높은 순</span></p>',
                unsafe_allow_html=True,
            )
            axis_row = "".join(f"<span>{max_power * frac:.0f}kW</span>" for frac in (0, 0.5, 1))
            st.markdown(
                f'{_power_rows_html(ranked)}<div class="ts-dash-power-axis">{axis_row}</div>',
                unsafe_allow_html=True,
            )

        comfort_avg = round(sum(comfort_index(r) for r in rooms) / room_count) if room_count else 0
        hours_elapsed = datetime.now().hour + datetime.now().minute / 60
        kwh_today = total_power * hours_elapsed

        with st.container(key="ts_dash_summary_card", border=True):
            st.markdown('<p class="ts-dash-card-title">KPI 요약 (오늘)</p>', unsafe_allow_html=True)
            summary_items = [
                ("power", "HVAC 전력 사용량", f"{kwh_today:.0f}kWh"),
                ("temp", "평균 온도", f"{avg_temp:.1f}°C"),
                ("co2", "평균 CO₂", f"{avg_co2:.0f}ppm"),
                ("active", "공간 사용률", f"{occupancy_rate}%"),
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
