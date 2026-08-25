import base64
import re
from pathlib import Path

import streamlit as st

from app.components.auth_store import is_logged_in
from app.components.mobile_ui import apply_mobile_styles, bottom_tab_bar, page_header
from app.components.room_store import (
    comfort_index,
    comfort_label,
    environment_snapshot,
    get_room,
    relative_updated,
    set_control_mode,
    set_target_temperature,
    system_judgment,
    trend_series,
)
from app.components.schedule_store import list_today_schedules

ICONS_DIR = Path(__file__).resolve().parents[1] / "assets" / "icons"

_AUTO_ICON = (
    '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M4 12a8 8 0 0 1 13.7-5.7L20 8"/><path d="M20 4v4h-4"/>'
    '<path d="M20 12a8 8 0 0 1-13.7 5.7L4 16"/><path d="M4 20v-4h4"/></svg>'
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
_THERMO_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 14.5V4a2 2 0 1 0-4 0v10.5a4 4 0 1 0 4 0Z"/><path d="M12 14.5v-7"/></svg>'
)
_DROPLET_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 2.5c4 5 7 8.5 7 12.5a7 7 0 0 1-14 0c0-4 3-7.5 7-12.5Z"/></svg>'
)
_CLOUD_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M7 18h10a4 4 0 0 0 .5-7.97A5.5 5.5 0 0 0 7.16 9.1 4 4 0 0 0 7 18Z"/></svg>'
)
_BOLT_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M13 2 4 14h6l-1 8 9-12h-6l1-8Z"/></svg>'
)


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


_CONTROL_MODES = (
    ("monitoring", "모니터", "monitoring.svg"),
    ("manual", "수동", "back_hand.svg"),
    ("rule", "규칙", "rule-based.svg"),
    ("predictive", "예측", "predictive.svg"),
)
_MODE_ICON_INACTIVE = "#98a1ab"
_MODE_ICON_ACTIVE = "#ffffff"


def _trend_svg(temps: list[float], co2s: list[float], target: float) -> str:
    width, height = 300, 90
    left, right, top, bottom = 6, 294, 10, 78
    n = len(temps)

    def scale(values: list[float]) -> tuple[float, float]:
        lo, hi = min(values), max(values)
        if hi - lo < 0.01:
            hi = lo + 0.5
        return lo, hi

    t_lo, t_hi = scale([*temps, target])
    c_lo, c_hi = scale(co2s)

    def to_points(values: list[float], lo: float, hi: float) -> str:
        pts = []
        for i, v in enumerate(values):
            x = left + (right - left) * i / (n - 1)
            y = bottom - (bottom - top) * (v - lo) / (hi - lo)
            pts.append(f"{x:.1f},{y:.1f}")
        return " ".join(pts)

    temp_points = to_points(temps, t_lo, t_hi)
    co2_points = to_points(co2s, c_lo, c_hi)
    target_y = bottom - (bottom - top) * (target - t_lo) / (t_hi - t_lo)

    return f"""
    <svg viewBox="0 0 {width} {height}" class="ts-trend-svg" preserveAspectRatio="none">
      <line x1="{left}" y1="{target_y:.1f}" x2="{right}" y2="{target_y:.1f}"
            stroke="var(--warning)" stroke-width="1.4" stroke-dasharray="4 3" />
      <text x="{right}" y="{target_y - 4:.1f}" text-anchor="end" class="ts-trend-target-label">목표 {target}°C</text>
      <polyline points="{co2_points}" fill="none" stroke="var(--chart-blue)"
                stroke-width="1.6" stroke-dasharray="1.5 3" stroke-linecap="round" />
      <polyline points="{temp_points}" fill="none" stroke="var(--text)"
                stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
    """


@st.dialog("환경 데이터", width="small")
def _show_environment_dialog(room: dict) -> None:
    snapshot = environment_snapshot(room)
    tiles = [
        (_THERMO_ICON, "온도", f"{snapshot['temperature']:.1f}" if snapshot["temperature"] is not None else "--", "°C", "var(--text)"),
        (_DROPLET_ICON, "습도", f"{snapshot['humidity']:.0f}" if snapshot["humidity"] is not None else "--", "%", "var(--chart-purple)"),
        (_CLOUD_ICON, "CO₂", f"{snapshot['co2']:.0f}" if snapshot["co2"] is not None else "--", "ppm", "var(--chart-blue)"),
        (_BOLT_ICON, "전력", f"{snapshot['power']:.2f}" if snapshot["power"] is not None else "--", "kW", "var(--chart-orange)"),
    ]
    tiles_html = "".join(
        f'<div class="ts-env-tile">'
        f'<p class="ts-env-tile-label" style="color:{color}">{icon}{label}</p>'
        f'<p class="ts-env-tile-value">{value}<span class="ts-env-tile-unit">{unit}</span></p>'
        f"</div>"
        for icon, label, value, unit, color in tiles
    )
    st.markdown(f'<div class="ts-env-grid">{tiles_html}</div>', unsafe_allow_html=True)


apply_mobile_styles("home")

if not is_logged_in():
    st.switch_page("pages/login.py")

room_id = st.session_state.get("_ts_selected_room")
room = get_room(room_id) if room_id else None

if room is None:
    st.switch_page("pages/room_list.py")

header_col, chip_col = st.columns([3, 4], gap="small", vertical_alignment="center")
with header_col:
    page_header(room["name"], back_page="pages/room_list.py")
with chip_col:
    auto_class = "is-active" if room.get("auto_control") else ""
    st.markdown(
        f"""
        <div class="ts-home-chips">
          <span class="ts-home-chip">업데이트 {relative_updated(room)}</span>
          <span class="ts-home-chip ts-home-chip-auto {auto_class}">{_AUTO_ICON}자동 제어</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

score = comfort_index(room)
label = comfort_label(score)
label_color = {
    "좋음": "var(--success)",
    "보통": "var(--warning)",
    "나쁨": "var(--danger)",
}[label]
circumference = 326.73
dash = circumference * score / 100

with st.container(key="ts_comfort_link"):
    st.markdown(
        f"""
        <div class="ts-comfort">
          <p class="ts-comfort-title">쾌적도 지수</p>
          <div class="ts-gauge-wrap">
            <svg viewBox="0 0 120 120" class="ts-gauge-ring">
              <circle cx="60" cy="60" r="52" stroke="var(--border)" stroke-width="14" fill="none" />
              <circle cx="60" cy="60" r="52" stroke="{label_color}" stroke-width="14" fill="none"
                      stroke-linecap="round" stroke-dasharray="{dash:.2f} {circumference:.2f}"
                      transform="rotate(-90 60 60)" />
            </svg>
            <div class="ts-gauge-center"><span class="ts-gauge-score">{score}</span></div>
          </div>
          <p class="ts-gauge-label">{label}</p>
          <p class="ts-comfort-hint">환경 데이터 보기 ›</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    comfort_clicked = st.button(
        "쾌적도 지수 상세 보기", key="ts_comfort_open", use_container_width=True
    )

if comfort_clicked:
    _show_environment_dialog(room)

headline, subline = system_judgment(room)
with st.container(key="ts_judgment_card", border=True):
    st.markdown(
        f"""
        <p class="ts-judgment-title">{_CHIP_ICON}시스템 판단 <span class="ts-judgment-badge">LLM</span></p>
        <p class="ts-judgment-headline">{headline}</p>
        """,
        unsafe_allow_html=True,
    )
    sub_col, link_col = st.columns([3, 1], vertical_alignment="center")
    with sub_col:
        st.markdown(f'<p class="ts-judgment-sub">{subline}</p>', unsafe_allow_html=True)
    with link_col:
        st.page_link("pages/log_detail.py", label="자세히 ›")

with st.container(key="ts_control_mode_card", border=True):
    st.markdown('<p class="ts-mode-title">제어 모드</p>', unsafe_allow_html=True)
    current_mode = room.get("control_mode", "rule")
    clicked_mode = None
    mode_cols = st.columns(4, gap="small")
    for col, (mode_id, mode_label, icon_file) in zip(mode_cols, _CONTROL_MODES):
        with col:
            with st.container(key=f"ts_mode_{mode_id}"):
                is_active = mode_id == current_mode
                icon_color = _MODE_ICON_ACTIVE if is_active else _MODE_ICON_INACTIVE
                icon_uri = _recolored_icon_data_uri(icon_file, icon_color)
                active_class = "is-active" if is_active else ""
                st.markdown(
                    f"""
                    <div class="ts-mode-item {active_class}">
                      <div class="ts-mode-icon-wrap"><img src="{icon_uri}" alt="" class="ts-mode-icon" /></div>
                      <p class="ts-mode-label">{mode_label}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if st.button(mode_label, key=f"mode_btn_{mode_id}", use_container_width=True):
                    clicked_mode = mode_id
    if clicked_mode and clicked_mode != current_mode:
        set_control_mode(room["id"], clicked_mode)
        st.rerun()

with st.container(key="ts_target_card", border=True):
    thermo_uri = _icon_data_uri("thermostat.svg")
    st.markdown(
        f'<p class="ts-target-title"><img src="{thermo_uri}" alt="" class="ts-target-title-icon" />목표 온도</p>',
        unsafe_allow_html=True,
    )
    minus_col, value_col, plus_col = st.columns([1, 2, 1], vertical_alignment="center")
    with minus_col:
        if st.button("−", key="target_temp_minus", use_container_width=True):
            set_target_temperature(room["id"], max(16, room["target_temperature"] - 1))
            st.rerun()
    with value_col:
        st.markdown(
            f'<p class="ts-target-value">{room["target_temperature"]}°</p>',
            unsafe_allow_html=True,
        )
    with plus_col:
        if st.button("+", key="target_temp_plus", use_container_width=True):
            set_target_temperature(room["id"], min(30, room["target_temperature"] + 1))
            st.rerun()
    st.markdown('<p class="ts-target-sub">예약 시간 동안 유지</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="ts-target-note">수동 조정 시 자동 제어보다 우선 실행됩니다</p>',
        unsafe_allow_html=True,
    )

with st.container(key="ts_reservation_card", border=True):
    header_col, badge_col = st.columns([3, 1], vertical_alignment="center")
    with header_col:
        st.markdown(
            f'<p class="ts-reservation-title">{_CALENDAR_ICON}예약 냉방</p>',
            unsafe_allow_html=True,
        )
    with badge_col:
        reservation_count = len(list_today_schedules(room["id"]))
        if reservation_count > 0:
            st.markdown(
                f"""
                <div class="ts-reservation-badge-wrap">
                  <span class="ts-reservation-badge">예약 {reservation_count}건</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
    st.markdown(
        '<p class="ts-reservation-desc">예약한 시간에 맞춰 자동으로 냉방을 켜고, '
        "설정한 온도를 유지하세요.</p>",
        unsafe_allow_html=True,
    )
    add_col, all_col = st.columns(2, gap="small")
    with add_col:
        if st.button("냉방 예약하기", key="reservation_add", use_container_width=True):
            st.switch_page("pages/schedule_create.py")
    with all_col:
        if st.button("예약 전체 보기", key="reservation_all", use_container_width=True):
            st.switch_page("pages/schedule_list.py")

temps, co2s = trend_series(room)
with st.container(key="ts_trend_card", border=True):
    trend_body = (
        _trend_svg(temps, co2s, room["target_temperature"])
        if temps and co2s
        else '<p class="ts-trend-empty">최근 30분간 수신된 센서 데이터가 없어요</p>'
    )
    st.markdown(
        f"""
        <div class="ts-trend-header">
          <p class="ts-trend-title">30분 추이</p>
          <div class="ts-trend-legend">
            <span class="ts-legend-item ts-legend-temp">온도</span>
            <span class="ts-legend-item ts-legend-co2">CO₂</span>
          </div>
        </div>
        {trend_body}
        """,
        unsafe_allow_html=True,
    )

bottom_tab_bar(active="home")
