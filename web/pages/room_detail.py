import sys
from datetime import date, time
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from app.components.room_store import (
    environment_snapshot,
    list_rooms,
    set_target_temperature,
    system_judgment,
    trend_series,
)
from app.components.schedule_store import (
    create_schedule,
    delete_schedule,
    get_schedule,
    list_schedules,
    list_today_schedules,
    schedule_status,
    update_schedule,
)
from components.auth_store import current_user_id, is_logged_in
from components.dash_shell import render_sidebar
from components.mobile_ui import apply_mobile_styles, icon_data_uri
from ml.comfort_model import calculate_pmv

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
_CLOCK_ICON = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/></svg>'
)
_BOLT_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M13 2 4 14h6l-1 8 9-12h-6l1-8Z"/></svg>'
)
_WARNING_ICON = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="12" cy="12" r="9"/><path d="M12 8v5"/><circle cx="12" cy="16" r="0.5" fill="currentColor"/></svg>'
)

_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_WEEKDAY_LABELS = {"mon": "월", "tue": "화", "wed": "수", "thu": "목", "fri": "금", "sat": "토", "sun": "일"}
_PRECOOL_OPTIONS = list(range(10, 61, 10))


def _close_resv_dialog() -> None:
    # Also fires when the dialog's own native X is clicked (not just our
    # buttons) - without this, closing that way would leave the "which
    # dialog is open" flag stale, silently reopening it on the next
    # unrelated rerun anywhere else on the page.
    st.session_state["_resv_dialog"] = None
    st.session_state["_resv_editing_id"] = None


@st.dialog("예약 추가", width="large", on_dismiss=_close_resv_dialog)
def _reservation_form_dialog(room: dict, editing_id: str | None = None) -> None:
    st.markdown('<div class="ts-reservation-dialog"></div>', unsafe_allow_html=True)
    editing = get_schedule(editing_id) if editing_id else None

    form_key = editing_id or "new"
    if st.session_state.get("_resv_form_key") != form_key:
        st.session_state["_resv_form_key"] = form_key
        st.session_state["resv_target_temp"] = editing["target_temperature"] if editing else 23

    st.markdown(
        '<p class="ts-schedule-form-hint">예약한 시간 동안 입력한 온도로 냉방을 자동 유지합니다</p>',
        unsafe_allow_html=True,
    )

    st.markdown('<p class="ts-schedule-field-label">일정 이름</p>', unsafe_allow_html=True)
    title = st.text_input(
        "일정 이름", value=editing["title"] if editing else "", key="resv_title", label_visibility="collapsed"
    )

    st.markdown('<p class="ts-schedule-field-label">날짜</p>', unsafe_allow_html=True)
    default_date = date.fromisoformat(editing["date"]) if editing else date.today()
    schedule_date = st.date_input("날짜", value=default_date, key="resv_date", label_visibility="collapsed")

    st.markdown('<p class="ts-schedule-field-label">시작 · 종료 시간</p>', unsafe_allow_html=True)
    default_start = time.fromisoformat(editing["start_time"]) if editing else time(9, 0)
    default_end = time.fromisoformat(editing["end_time"]) if editing else time(10, 0)
    start_col, end_col = st.columns(2, gap="small")
    with start_col:
        start_time = st.time_input("시작 시간", value=default_start, key="resv_start", label_visibility="collapsed")
    with end_col:
        end_time = st.time_input("종료 시간", value=default_end, key="resv_end", label_visibility="collapsed")
    time_error = st.empty()

    with st.container(key="ts_resv_temp_card", border=True):
        st.markdown(f'<p class="ts-schedule-card-title">{_CHIP_ICON}목표 온도</p>', unsafe_allow_html=True)
        minus_col, value_col, plus_col = st.columns([1, 2, 1], vertical_alignment="center")
        with minus_col:
            if st.button("−", key="resv_temp_minus", width="stretch"):
                st.session_state["resv_target_temp"] = max(16, st.session_state["resv_target_temp"] - 1)
        with plus_col:
            if st.button("+", key="resv_temp_plus", width="stretch"):
                st.session_state["resv_target_temp"] = min(30, st.session_state["resv_target_temp"] + 1)
        with value_col:
            st.markdown(
                f'<p class="ts-schedule-temp-value">{st.session_state["resv_target_temp"]}°</p>',
                unsafe_allow_html=True,
            )
        st.markdown('<p class="ts-schedule-temp-sub">예약 시간 동안 유지</p>', unsafe_allow_html=True)
    target_temperature = st.session_state["resv_target_temp"]

    with st.container(key="ts_resv_precool_card", border=True):
        title_col, toggle_col = st.columns([4, 1], vertical_alignment="center")
        with title_col:
            st.markdown(
                f'<p class="ts-schedule-card-title">{_BOLT_ICON}선냉방 (미리 가동)</p>', unsafe_allow_html=True
            )
        with toggle_col:
            precool_enabled = st.toggle(
                "선냉방", value=editing["precool_enabled"] if editing else False,
                key="resv_precool_toggle", label_visibility="collapsed",
            )
        st.markdown(
            '<p class="ts-schedule-card-desc">시작 전 미리 냉방해 목표 온도를 맞춰둡니다.</p>',
            unsafe_allow_html=True,
        )
        if precool_enabled:
            default_minutes = editing["precool_minutes_before"] if editing else 20
            precool_minutes_before = st.selectbox(
                "몇 분 전", _PRECOOL_OPTIONS,
                index=_PRECOOL_OPTIONS.index(default_minutes) if default_minutes in _PRECOOL_OPTIONS else 1,
                format_func=lambda m: f"시작 {m}분 전",
                key="resv_precool_minutes", label_visibility="collapsed",
            )
        else:
            precool_minutes_before = editing["precool_minutes_before"] if editing else 20

    with st.container(key="ts_resv_repeat_card", border=True):
        title_col, toggle_col = st.columns([4, 1], vertical_alignment="center")
        with title_col:
            st.markdown(f'<p class="ts-schedule-card-title">{_CALENDAR_ICON}매주 반복</p>', unsafe_allow_html=True)
        with toggle_col:
            repeat_enabled = st.toggle(
                "매주 반복", value=editing["repeat_enabled"] if editing else False,
                key="resv_repeat_toggle", label_visibility="collapsed",
            )
        if repeat_enabled:
            default_days = editing["repeat_days"] if editing else []
            repeat_days = st.pills(
                "반복 요일", options=_WEEKDAYS, format_func=lambda d: _WEEKDAY_LABELS[d],
                selection_mode="multi", default=[d for d in default_days if d in _WEEKDAYS],
                key="resv_repeat_days", label_visibility="collapsed",
            )
        else:
            repeat_days = []
    repeat_days_error = st.empty()

    st.markdown(
        f'<div class="ts-schedule-note">{_WARNING_ICON}예약 시간이 끝나면 자동으로 절전·종료됩니다</div>',
        unsafe_allow_html=True,
    )

    submitted = st.button(
        "예약 수정" if editing else "예약 저장", key="resv_submit", width="stretch"
    )
    if submitted:
        if start_time >= end_time:
            with time_error:
                st.markdown(
                    '<p class="ts-schedule-time-error">종료 시간을 시작 시간보다 늦게 설정해주세요</p>',
                    unsafe_allow_html=True,
                )
        elif repeat_enabled and not repeat_days:
            with repeat_days_error:
                st.markdown(
                    '<p class="ts-schedule-field-error">반복 요일을 선택해주세요</p>', unsafe_allow_html=True
                )
        else:
            fields = dict(
                title=title,
                schedule_date=schedule_date,
                start_time=start_time,
                end_time=end_time,
                target_temperature=target_temperature,
                precool_enabled=precool_enabled,
                precool_minutes_before=precool_minutes_before,
                repeat_enabled=repeat_enabled,
                repeat_days=list(repeat_days) if repeat_days else [],
            )
            st.session_state.pop("resv_target_temp", None)
            st.session_state.pop("_resv_form_key", None)
            if editing:
                update_schedule(editing["id"], **fields)
            else:
                create_schedule(room_id=room["id"], **fields)
            _close_resv_dialog()
            st.rerun()


@st.dialog("예약 냉방", width="large", on_dismiss=_close_resv_dialog)
def _reservation_list_dialog(room: dict) -> None:
    st.markdown('<div class="ts-reservation-dialog"></div>', unsafe_allow_html=True)
    schedules = list_schedules(room["id"])
    if schedules:
        for s in schedules:
            status = schedule_status(s)
            row_col, edit_col, delete_col = st.columns([6, 1, 1], vertical_alignment="center")
            with row_col:
                icon = _CLOCK_ICON if status != "완료" else ""
                extra = (
                    f'<p class="ts-reservation-row-sub">목표 {s["target_temperature"]}°C · 냉방</p>'
                    if status == "진행 중"
                    else ""
                )
                st.markdown(
                    f"""
                    <div class="ts-reservation-row">
                      <span class="ts-reservation-row-icon">{icon}</span>
                      <div>
                        <p class="ts-reservation-row-title">{s["start_time"]}–{s["end_time"]} · {s["title"] or "제목 없음"}</p>
                        {extra}
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with edit_col:
                # Streamlit doesn't allow opening a dialog from inside another
                # dialog - flag which one should be open instead and let the
                # top-level page body (which reruns every time) call it.
                if st.button("", key=f"resv_edit_{s['id']}", icon=":material/edit:"):
                    st.session_state["_resv_dialog"] = "form"
                    st.session_state["_resv_editing_id"] = s["id"]
                    st.rerun()
            with delete_col:
                if st.button("", key=f"resv_delete_{s['id']}", icon=":material/delete:"):
                    delete_schedule(s["id"])
                    st.rerun()
    else:
        st.markdown('<p class="ts-dash-list-empty">등록된 예약이 없습니다</p>', unsafe_allow_html=True)

    if st.button("＋ 새 예약 추가", key="resv_list_add", width="stretch"):
        st.session_state["_resv_dialog"] = "form"
        st.session_state["_resv_editing_id"] = None
        st.rerun()


def _trend_chart(temps: list[float], co2s: list[float], target: float) -> alt.LayerChart:
    temp_df = pd.DataFrame({"분": list(range(len(temps))), "값": temps})
    co2_df = pd.DataFrame({"분": list(range(len(co2s))), "값": co2s})
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

rooms = list_rooms(current_user_id())

selected_id = st.session_state.get("_web_selected_room")
if selected_id and not any(r["id"] == selected_id for r in rooms):
    selected_id = None
if selected_id is None and rooms:
    selected_id = rooms[0]["id"]
    st.session_state["_web_selected_room"] = selected_id

room = next((r for r in rooms if r["id"] == selected_id), None) if selected_id else None

if room is not None:
    active_dialog = st.session_state.get("_resv_dialog")
    if active_dialog == "list":
        _reservation_list_dialog(room)
    elif active_dialog == "form":
        _reservation_form_dialog(room, editing_id=st.session_state.get("_resv_editing_id"))

sidebar_col, main_col = st.columns([1, 4], gap="small")

with sidebar_col:
    render_sidebar("room_detail")

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
                "공간 선택", names, index=current_index, key="roomdetail_top_room_select", label_visibility="collapsed"
            )
            picked_room = next((r for r in rooms if r["name"] == picked), room)
            if picked_room["id"] != room["id"]:
                st.session_state["_web_selected_room"] = picked_room["id"]
                st.rerun()

        @st.fragment(run_every=5)
        def render_live_room_detail(current_room_id: int):
            # Fetch fresh room & snapshot on every fragment tick
            fresh_rooms = list_rooms(current_user_id())
            current_r = next((r for r in fresh_rooms if r["id"] == current_room_id), room)
            snapshot = environment_snapshot(current_r)
            temp_val, co2_val, humidity_val, power_val = (
                snapshot["temperature"], snapshot["co2"], snapshot["humidity"], snapshot["power"],
            )
            target_ok = temp_val is not None and abs(temp_val - current_r["target_temperature"]) <= 1.5
            temp_display = f"{temp_val:.1f}" if temp_val is not None else "--"
            co2_display = f"{co2_val:.0f}" if co2_val is not None else "--"
            humidity_display = f"{humidity_val:.0f}" if humidity_val is not None else "--"
            power_display = f"{power_val:.1f}" if power_val is not None else "--"
            co2_ok = co2_val is not None and co2_val < 700
            door_val = snapshot.get("door_state")
            motion_val = snapshot.get("motion")
            door_display = "열림" if door_val == "open" else ("닫힘" if door_val == "closed" else "--")
            door_ok = door_val == "closed"
            motion_display = "감지됨" if motion_val is True else ("미감지" if motion_val is False else "--")
            motion_active = motion_val is True

            kpi_items = [
                (
                    "temp",
                    "온도",
                    temp_display,
                    "°C",
                    "is-positive" if target_ok else "is-negative",
                    f"{_CHECK_ICON}목표 {current_r['target_temperature']}°C 근접"
                    if target_ok
                    else f"{_WARN_ICON}목표 {current_r['target_temperature']}°C 미달",
                ),
                (
                    "humidity",
                    "습도",
                    humidity_display,
                    "%",
                    "is-positive",
                    f"{_CHECK_ICON}적정",
                ),
                (
                    "co2",
                    "CO₂",
                    co2_display,
                    "ppm",
                    "is-positive" if co2_ok else "is-negative",
                    f"{_CHECK_ICON}기준 충족" if co2_ok else f"{_WARN_ICON}기준 초과",
                ),
                (
                    "door",
                    "문열림 센서",
                    door_display,
                    "",
                    "is-positive" if door_ok else "is-negative",
                    f"{_CHECK_ICON}문 닫힘 상태" if door_ok else f"{_WARN_ICON}문 열림 감지",
                ),
                (
                    "pir",
                    "인체 감지(PIR)",
                    motion_display,
                    "",
                    "is-positive" if motion_active else "",
                    f"{_CHECK_ICON}실시간 움직임 감지" if motion_active else "움직임 미감지",
                ),
                (
                    "power",
                    "HVAC 전력",
                    power_display,
                    "kW",
                    "is-positive" if power_val is not None else "",
                    f"{_CHECK_ICON}전력 센서 실측" if power_val is not None else "전력 센서 미연동",
                ),
            ]
            kpi_cols = st.columns(6, gap="small")
            for col, (slug, label, value, unit, sub_class, sub) in zip(kpi_cols, kpi_items):
                with col:
                    with st.container(key=f"ts_dash_kpi_card_{slug}", border=True):
                        if slug == "humidity":
                            icon_html = f'<span class="ts-dash-kpi-icon ts-room-humidity-icon">{_HUMIDITY_ICON}</span>'
                        elif slug in ("door", "pir", "occupancy"):
                            icon_html = f'<img class="ts-dash-kpi-icon" src="{icon_data_uri("web_door.svg")}" alt="" />'
                        else:
                            icon_html = f'<img class="ts-dash-kpi-icon" src="{icon_data_uri(_KPI_ICON_FILES.get(slug, "temperture.svg"))}" alt="" />'

                        unit_html = f'<span class="ts-dash-kpi-unit">{unit}</span>' if unit else ""
                        st.markdown(
                            f"""
                            <div class="ts-dash-kpi-head">
                              <span class="ts-dash-kpi-label">{label}</span>
                              {icon_html}
                            </div>
                            <p class="ts-dash-kpi-value">{value}{unit_html}</p>
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
                    temps, co2s = trend_series(current_r)
                    st.altair_chart(
                        _trend_chart(temps, co2s, current_r["target_temperature"]),
                        width="stretch",
                    )
                    schedules = list_today_schedules(current_r["id"])
                    res_head_col, res_link_col = st.columns([2, 1], vertical_alignment="center")
                    with res_head_col:
                        st.markdown(
                            f'<p class="ts-dash-card-title" style="margin:0;">{_CALENDAR_ICON}예약 냉방</p>',
                            unsafe_allow_html=True,
                        )
                    with res_link_col:
                        if st.button("예약 목록보기", key="dash_reservation_all", width="stretch"):
                            st.session_state["_resv_dialog"] = "list"
                            st.rerun()
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
                        st.session_state["_resv_dialog"] = "form"
                        st.session_state["_resv_editing_id"] = None
                        st.rerun()

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
                            set_target_temperature(current_r["id"], max(16, current_r["target_temperature"] - 1))
                            st.rerun()
                    with value_col:
                        st.markdown(
                            f"""
                            <p class="ts-room-manual-value">{current_r["target_temperature"]}°</p>
                            <p class="ts-room-manual-caption">예약 시간 동안 유지</p>
                            """,
                            unsafe_allow_html=True,
                        )
                    with plus_col:
                        if st.button("+", key="dash_target_plus", width="stretch"):
                            set_target_temperature(current_r["id"], min(30, current_r["target_temperature"] + 1))
                            st.rerun()
                    st.markdown(
                        '<p class="ts-room-manual-note">수동 제어는 자동 제어보다 항상 우선 실행됩니다</p>',
                        unsafe_allow_html=True,
                    )

                with st.container(key="ts_room_ai_card", border=True):
                    st.markdown(
                        f'<p class="ts-dash-card-title">{_CHIP_ICON}운영 설명 <span class="ts-dash-badge">규칙 기반</span></p>',
                        unsafe_allow_html=True,
                    )
                    headline, subline = system_judgment(current_r)
                    st.markdown(
                        f"""
                        <p class="ts-dash-judgment-headline">{headline}</p>
                        <p class="ts-dash-judgment-sub">{subline}</p>
                        """,
                        unsafe_allow_html=True,
                    )

            pmv = (
                calculate_pmv(float(temp_val), float(humidity_val)).pmv
                if temp_val is not None and humidity_val is not None
                else None
            )
            with st.container(key="ts_dash_summary_card", border=True):
                st.markdown('<p class="ts-dash-card-title">현재 상태 요약</p>', unsafe_allow_html=True)
                summary_items = [
                    ("power", "순간 HVAC 전력", f"{power_val:.1f}kW" if power_val is not None else "--"),
                    ("temp", "현재 온도", f"{temp_display}°C" if temp_val is not None else "--"),
                    ("co2", "현재 CO₂", f"{co2_display}ppm" if co2_val is not None else "--"),
                    ("occupancy", "현재 재실 상태", "재실" if current_r.get("occupied") else "공실"),
                    (None, "현재 PMV", f"{pmv:+.2f}" if pmv is not None else "--"),
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

        render_live_room_detail(room["id"])
