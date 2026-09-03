import sys
from datetime import datetime
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from app.components.alert_store import alert_severity_counts
from app.components.room_store import (
    ai_judgment,
    environment_snapshot,
    list_rooms,
    room_status,
    system_judgment,
)
from app.components.schedule_store import list_today_schedules
from components.auth_store import current_user_id, is_logged_in
from components.dash_shell import render_sidebar, render_topbar
from components.mobile_ui import apply_mobile_styles, icon_data_uri, recolored_icon_data_uri
from shared.api_client import api_get

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
# (lookback minutes, maximum point count, axis date format)
_PERIODS = {
    "1일": (24 * 60, 120, "%H:%M"),
    "7일": (7 * 24 * 60, 168, "%m/%d"),
    "30일": (30 * 24 * 60, 180, "%m/%d"),
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


def _heat_thumb_style(room_id: str, temp: float | None) -> str:
    # No real floor-plan/render exists yet - stands in with a flat tint
    # (still keyed to the room's live temperature, same blue->teal->red
    # scale as the legend) plus a centered room icon, rather than a busy
    # gradient that read as an odd green blob.
    # A room with no env sensor reading yet (freshly registered, no
    # devices installed) has temp=None rather than the mock's always-on
    # random float - fall back to a neutral gray tint instead of crashing.
    r, g, b = _temp_rgb(temp) if temp is not None else (152, 161, 171)
    tint = tuple(round(c + (255 - c) * 0.62) for c in (r, g, b))
    icon_uri = recolored_icon_data_uri("meeting_room.svg", f"rgba({r},{g},{b},0.55)")
    return (
        f"background: url('{icon_uri}') center/28px no-repeat, "
        f"rgb({tint[0]},{tint[1]},{tint[2]});"
    )


def _real_history(room_id: int, metric: str, minutes: int,
                  max_points: int) -> tuple[list[datetime], list[float]]:
    rows = api_get(
        f"/rooms/{room_id}/trend",
        params={"minutes": minutes, "points": max_points},
    ) or []
    pairs = [
        (datetime.fromisoformat(row["measured_at"]), float(row[metric]))
        for row in rows
        if row.get(metric) is not None
    ]
    if len(pairs) > max_points:
        last_pair = pairs[-1]
        step = max(1, len(pairs) // max_points)
        pairs = pairs[::step]
        if pairs[-1] != last_pair:
            pairs.append(last_pair)
    return [pair[0] for pair in pairs], [pair[1] for pair in pairs]


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

sidebar_col, main_col = st.columns([1, 4], gap="small")

with sidebar_col:
    render_sidebar("dashboard")

with main_col:
    @st.fragment(run_every=5)
    def render_live_dashboard():
        rooms = list_rooms(current_user_id())
        snapshots = {r["id"]: environment_snapshot(r) for r in rooms}
        room_count = len(rooms)

        # A brand-new room (or one whose sensor hasn't reported yet) has no reading
        # at all rather than a mock-random float, so temperature/co2/power can be
        # None here - average/sum only over the rooms that actually have a value.
        temps = [s["temperature"] for s in snapshots.values() if s["temperature"] is not None]
        co2s = [s["co2"] for s in snapshots.values() if s["co2"] is not None]
        powers = [s["power"] for s in snapshots.values() if s["power"] is not None]

        avg_temp = sum(temps) / len(temps) if temps else 0.0
        avg_co2 = sum(co2s) / len(co2s) if co2s else 0.0
        total_power = sum(powers)
        active_count = sum(1 for r in rooms if r.get("occupied"))
        occupancy_rate = round(active_count / room_count * 100) if room_count else 0
        severity = alert_severity_counts([r["id"] for r in rooms])
        alert_total = severity["critical"] + severity["warning"]
        measured_power = bool(powers)

        render_topbar("대시보드", alert_count=alert_total)

        if not rooms:
            st.switch_page("pages/devices.py")
            return

        temp_diff = avg_temp - 24
        temp_state = "근접" if abs(temp_diff) <= 1 else ("초과" if temp_diff > 0 else "미달")
        co2_ok = bool(co2s) and avg_co2 < 1000
        kpi_items = [
            (
                "temp",
                "평균 온도",
                f"{avg_temp:.1f}" if temps else "--",
                "°C",
                "is-positive" if temps and temp_state == "근접" else "is-negative" if temps else "",
                f"{_CHECK_ICON}목표 24°C {temp_state}" if temps else "환경 센서 데이터 없음",
            ),
            (
                "co2",
                "평균 CO₂",
                f"{avg_co2:.0f}" if co2s else "--",
                "ppm",
                "is-positive" if co2_ok else "is-negative" if co2s else "",
                (f"{_CHECK_ICON}목표 <1000ppm " + ("충족" if co2_ok else "초과"))
                if co2s else "환경 센서 데이터 없음",
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
                f"{total_power:.1f}" if measured_power else "--",
                "kW",
                "is-positive" if measured_power else "",
                f"{_CHECK_ICON}전력 센서 합계" if measured_power else "전력 센서 미연동",
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
                        door_label = "문 열림" if snap.get("door_state") == "open" else ("문 닫힘" if snap.get("door_state") == "closed" else "문 --")
                        door_class = "ts-dash-status-warn" if snap.get("door_state") == "open" else "ts-dash-status-ok"
                        motion_label = "움직임 감지" if snap.get("motion") is True else "움직임 없음"

                        with col:
                            with st.container(key=f"ts_dash_room_card_{r['id']}"):
                                st.markdown(
                                    f"""
                                    <div class="ts-dash-room-thumb" style="{_heat_thumb_style(r["id"], snap["temperature"])}"></div>
                                    <div class="ts-dash-room-card-head">
                                       <span class="ts-dash-room-card-name">{r["name"]}</span>
                                       <div style="display:flex; gap:4px; flex-wrap:wrap;">
                                         <span class="ts-dash-status-badge {door_class}">{door_label}</span>
                                         <span class="ts-dash-status-badge ts-dash-status-{status_class}">{status}</span>
                                       </div>
                                    </div>
                                    <div class="ts-dash-room-card-stats">
                                      <span><img src="{icon_data_uri("temperture.svg")}" alt="" />{f'{snap["temperature"]:.1f}°C' if snap["temperature"] is not None else "--"}</span>
                                      <span><img src="{icon_data_uri("co2.svg")}" alt="" />CO₂ {f'{snap["co2"]:.0f}ppm' if snap["co2"] is not None else "--"}</span>
                                      <span><img src="{icon_data_uri("web_door.svg")}" alt="" />{motion_label}</span>
                                      <span><img src="{icon_data_uri("web_bolt.svg")}" alt="" />전력 {f'{snap["power"]:.2f}kW' if snap["power"] is not None else "--"}</span>
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
                minutes, n_points, date_format = _PERIODS[period_choice]
                points, main_series = _real_history(
                    rooms[0]["id"], metric_key, minutes, n_points
                )
                if main_series:
                    series_label = f"{rooms[0]['name']} {metric_choice}"
                    chart = _timeline_chart(
                        points,
                        {series_label: main_series},
                        target=("목표 온도", 24) if metric_key == "temperature" else ("목표 CO₂", 1000),
                        metric_label=metric_choice,
                        unit="°C" if metric_key == "temperature" else "ppm",
                        date_format=date_format,
                        y_domain=(18, 30) if metric_key == "temperature" else None,
                    )
                    st.altair_chart(chart, width="stretch")
                else:
                    st.info("선택한 기간에 실측 데이터가 없습니다.")

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
                flagged_rooms = [r for r in rooms if room_status(r) != "정상"]
                notable_room = flagged_rooms[0] if flagged_rooms else rooms[0]
                ai_result = None
                if not notable_room.get("sensor_connected", True):
                    headline, subline = "센서 응답이 없어 제어를 보류했습니다", "센서 재연결이 필요해요"
                else:
                    ai_result = ai_judgment(notable_room)
                    if ai_result:
                        headline, subline = ai_result
                    else:
                        headline, subline = system_judgment(notable_room)
                badge_label = "LLM" if ai_result else "규칙 기반"
                st.markdown(
                    f'<p class="ts-dash-card-title">{_CHIP_ICON}AI 운영 설명 <span class="ts-dash-badge">{badge_label}</span></p>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"""
                    <p class="ts-dash-judgment-headline">[{notable_room["name"]}] {headline}</p>
                    <p class="ts-dash-judgment-sub">{subline}</p>
                    """,
                    unsafe_allow_html=True,
                )

        ranked = sorted(rooms, key=lambda r: snapshots[r["id"]]["power"] or 0, reverse=True)
        online_powers = [
            snapshots[r["id"]]["power"] for r in ranked if snapshots[r["id"]]["power"] is not None
        ]
        max_power = max(online_powers, default=0) or 1

        def _power_rows_html(room_list: list[dict]) -> str:
            rows = []
            for r in room_list:
                if not r.get("sensor_connected", True) or snapshots[r["id"]]["power"] is None:
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

        connected_count = sum(1 for room_item in rooms if room_item.get("sensor_connected"))

        with st.container(key="ts_dash_summary_card", border=True):
            st.markdown('<p class="ts-dash-card-title">현재 상태 요약</p>', unsafe_allow_html=True)
            summary_items = [
                ("power", "순간 HVAC 전력", f"{total_power:.1f}kW" if measured_power else "--"),
                ("temp", "현재 평균 온도", f"{avg_temp:.1f}°C" if temps else "--"),
                ("co2", "현재 평균 CO₂", f"{avg_co2:.0f}ppm" if co2s else "--"),
                ("active", "현재 공간 사용률", f"{occupancy_rate}%"),
                (None, "환경 센서 연결", f"{connected_count}/{room_count}"),
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

    render_live_dashboard()
