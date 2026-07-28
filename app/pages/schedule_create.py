from datetime import date, time

import streamlit as st

from app.components.auth_store import is_logged_in
from app.components.mobile_ui import apply_mobile_styles, page_header
from app.components.room_store import get_room
from app.components.schedule_store import create_schedule, get_schedule, update_schedule

_BOLT_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M13 2 4 14h6l-1 8 9-12h-6l1-8Z"/></svg>'
)
_CALENDAR_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="4" y="5.5" width="16" height="14" rx="2"/><path d="M4 9.5h16M8 3.5v3M16 3.5v3"/></svg>'
)
_WARNING_ICON = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="12" cy="12" r="9"/><path d="M12 8v5"/><circle cx="12" cy="16" r="0.5" fill="currentColor"/></svg>'
)

_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_WEEKDAY_LABELS = {"mon": "월", "tue": "화", "wed": "수", "thu": "목", "fri": "금", "sat": "토", "sun": "일"}
_PRECOOL_OPTIONS = list(range(10, 61, 10))
_HOURS = list(range(24))
_MINUTES = list(range(0, 60, 10))


def _closest_minute_index(minute: int) -> int:
    closest = min(_MINUTES, key=lambda m: abs(m - minute))
    return _MINUTES.index(closest)


apply_mobile_styles("schedule_create", shared=("schedule",))

if not is_logged_in():
    st.switch_page("pages/login.py")

room_id = st.session_state.get("_ts_selected_room")
room = get_room(room_id) if room_id else None

if room is None:
    st.switch_page("pages/room_list.py")

editing_id = st.session_state.get("_ts_editing_schedule")
editing = get_schedule(editing_id) if editing_id else None

form_key = editing_id or "new"
if st.session_state.get("_ts_schedule_form_key") != form_key:
    st.session_state["_ts_schedule_form_key"] = form_key
    st.session_state["schedule_target_temp"] = (
        editing["target_temperature"] if editing else 24
    )

page_header(
    "예약 수정" if editing else "예약 추가",
    back_page="pages/schedule_detail.py" if editing else "pages/home.py",
)

st.markdown(
    '<p class="ts-schedule-form-hint">예약한 시간 동안 입력한 온도로 냉방을 자동 유지합니다</p>',
    unsafe_allow_html=True,
)

st.markdown('<p class="ts-schedule-field-label">날짜</p>', unsafe_allow_html=True)
default_date = date.fromisoformat(editing["date"]) if editing else date.today()
schedule_date = st.date_input(
    "날짜", value=default_date, label_visibility="collapsed", key="schedule_date"
)

default_start = time.fromisoformat(editing["start_time"]) if editing else time(9, 0)
default_end = time.fromisoformat(editing["end_time"]) if editing else time(10, 0)

st.markdown('<p class="ts-schedule-field-label">시작 시간</p>', unsafe_allow_html=True)
start_hour_col, start_minute_col = st.columns(2, gap="small")
with start_hour_col:
    start_hour = st.selectbox(
        "시", _HOURS, index=default_start.hour, format_func=lambda h: f"{h:02d}시",
        key="schedule_start_hour", label_visibility="collapsed",
    )
with start_minute_col:
    start_minute = st.selectbox(
        "분", _MINUTES, index=_closest_minute_index(default_start.minute),
        format_func=lambda m: f"{m:02d}분",
        key="schedule_start_minute", label_visibility="collapsed",
    )
start_time = time(start_hour, start_minute)

st.markdown('<p class="ts-schedule-field-label">종료 시간</p>', unsafe_allow_html=True)
end_hour_col, end_minute_col = st.columns(2, gap="small")
with end_hour_col:
    end_hour = st.selectbox(
        "시", _HOURS, index=default_end.hour, format_func=lambda h: f"{h:02d}시",
        key="schedule_end_hour", label_visibility="collapsed",
    )
with end_minute_col:
    end_minute = st.selectbox(
        "분", _MINUTES, index=_closest_minute_index(default_end.minute),
        format_func=lambda m: f"{m:02d}분",
        key="schedule_end_minute", label_visibility="collapsed",
    )
end_time = time(end_hour, end_minute)
time_error = st.empty()

with st.container(key="ts_schedule_temp_card", border=True):
    st.markdown('<p class="ts-schedule-card-title">🌡 목표 온도</p>', unsafe_allow_html=True)
    minus_col, value_col, plus_col = st.columns([1, 2, 1], vertical_alignment="center")
    with minus_col:
        if st.button("−", key="schedule_temp_minus", use_container_width=True):
            st.session_state["schedule_target_temp"] = max(
                16, st.session_state["schedule_target_temp"] - 1
            )
    with plus_col:
        if st.button("+", key="schedule_temp_plus", use_container_width=True):
            st.session_state["schedule_target_temp"] = min(
                30, st.session_state["schedule_target_temp"] + 1
            )
    with value_col:
        st.markdown(
            f'<p class="ts-schedule-temp-value">{st.session_state["schedule_target_temp"]}°</p>',
            unsafe_allow_html=True,
        )
    st.markdown('<p class="ts-schedule-temp-sub">예약 시간 동안 유지</p>', unsafe_allow_html=True)

target_temperature = st.session_state["schedule_target_temp"]

with st.container(key="ts_schedule_precool_card", border=True):
    title_col, toggle_col = st.columns([4, 1], vertical_alignment="center")
    with title_col:
        st.markdown(
            f'<p class="ts-schedule-card-title">{_BOLT_ICON}선냉방 (미리 가동)</p>',
            unsafe_allow_html=True,
        )
    with toggle_col:
        precool_enabled = st.toggle(
            "선냉방",
            value=editing["precool_enabled"] if editing else False,
            key="schedule_precool_toggle",
            label_visibility="collapsed",
        )
    st.markdown(
        '<p class="ts-schedule-card-desc">예약 시작 전 미리 냉방을 시작해, '
        "시작 시각에 목표 온도에 도달하게 합니다.</p>",
        unsafe_allow_html=True,
    )
    if precool_enabled:
        default_minutes = editing["precool_minutes_before"] if editing else 20
        precool_minutes_before = st.selectbox(
            "몇 분 전",
            _PRECOOL_OPTIONS,
            index=_PRECOOL_OPTIONS.index(default_minutes)
            if default_minutes in _PRECOOL_OPTIONS
            else 1,
            format_func=lambda m: f"{m}분전",
            key="schedule_precool_minutes",
            label_visibility="collapsed",
        )
    else:
        precool_minutes_before = editing["precool_minutes_before"] if editing else 20

with st.container(key="ts_schedule_repeat_card", border=True):
    title_col, toggle_col = st.columns([4, 1], vertical_alignment="center")
    with title_col:
        st.markdown(
            f'<p class="ts-schedule-card-title">{_CALENDAR_ICON}매주 반복</p>',
            unsafe_allow_html=True,
        )
    with toggle_col:
        repeat_enabled = st.toggle(
            "매주 반복",
            value=editing["repeat_enabled"] if editing else False,
            key="schedule_repeat_toggle",
            label_visibility="collapsed",
        )
    if repeat_enabled:
        default_days = editing["repeat_days"] if editing else []
        repeat_days = st.pills(
            "반복 요일",
            options=_WEEKDAYS,
            format_func=lambda d: _WEEKDAY_LABELS[d],
            selection_mode="multi",
            default=[d for d in default_days if d in _WEEKDAYS],
            key="schedule_repeat_days",
            label_visibility="collapsed",
        )
    else:
        repeat_days = []

repeat_days_error = st.empty()

st.markdown(
    f'<div class="ts-schedule-note">{_WARNING_ICON}예약 시간이 끝나면 자동으로 절전·종료됩니다</div>',
    unsafe_allow_html=True,
)

submitted = st.button(
    "예약 수정" if editing else "예약 저장",
    key="schedule_submit",
    use_container_width=True,
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
                '<p class="ts-schedule-field-error">반복 요일을 선택해주세요</p>',
                unsafe_allow_html=True,
            )
    else:
        fields = dict(
            schedule_date=schedule_date,
            start_time=start_time,
            end_time=end_time,
            target_temperature=target_temperature,
            precool_enabled=precool_enabled,
            precool_minutes_before=precool_minutes_before,
            repeat_enabled=repeat_enabled,
            repeat_days=list(repeat_days) if repeat_days else [],
        )
        st.session_state.pop("schedule_target_temp", None)
        st.session_state.pop("_ts_schedule_form_key", None)
        if editing:
            update_schedule(editing["id"], **fields)
            st.session_state.pop("_ts_editing_schedule", None)
            st.switch_page("pages/schedule_detail.py")
        else:
            new_schedule = create_schedule(room_id=room["id"], **fields)
            st.session_state["_ts_selected_schedule"] = new_schedule["id"]
            st.switch_page("pages/schedule_list.py")
