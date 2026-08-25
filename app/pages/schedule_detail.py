import streamlit as st

from app.components.auth_store import is_logged_in
from app.components.mobile_ui import apply_mobile_styles, page_header
from app.components.room_store import get_room
from app.components.schedule_store import (
    active_progress,
    delete_schedule,
    get_schedule,
    precool_info,
    repeat_days_label,
    schedule_status,
)

_BOLT_ICON = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M13 2 4 14h6l-1 8 9-12h-6l1-8Z"/></svg>'
)
_CALENDAR_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="4" y="5.5" width="16" height="14" rx="2"/><path d="M4 9.5h16M8 3.5v3M16 3.5v3"/></svg>'
)


@st.dialog("예약을 취소할까요?")
def _confirm_cancel(schedule_id: str) -> None:
    st.markdown(
        '<p class="ts-schedule-cancel-dialog-desc">취소하면 이 예약은 목록에서 삭제되고 '
        "되돌릴 수 없어요.</p>",
        unsafe_allow_html=True,
    )
    keep_col, cancel_col = st.columns(2, gap="small")
    with keep_col:
        if st.button("유지하기", key="schedule_cancel_keep", use_container_width=True):
            st.rerun()
    with cancel_col:
        if st.button(
            "예약 취소", key="schedule_cancel_confirm", use_container_width=True
        ):
            delete_schedule(schedule_id)
            st.session_state.pop("_ts_selected_schedule", None)
            st.switch_page("pages/schedule_list.py")


apply_mobile_styles("schedule_detail", shared=("schedule",))

if not is_logged_in():
    st.switch_page("pages/login.py")

room_id = st.session_state.get("_ts_selected_room")
room = get_room(room_id) if room_id else None

if room is None:
    st.switch_page("pages/room_list.py")

schedule_id = st.session_state.get("_ts_selected_schedule")
schedule = get_schedule(schedule_id) if schedule_id else None

if schedule is None:
    st.switch_page("pages/schedule_list.py")

page_header("예약 상세", back_page="pages/schedule_list.py")

status = schedule_status(schedule)
precool = precool_info(schedule)
current_temp = room["temperature"]
current_temp_display = f"{current_temp:.1f}°C" if current_temp is not None else "--°C"
target_temp = schedule["target_temperature"]

if precool and precool["active"]:
    progress_pct = round(precool["progress"] * 100)
    st.markdown(
        f"""
        <div class="ts-schedule-status-card">
          <p class="ts-schedule-status-title">{_BOLT_ICON}선냉방 진행 중</p>
          <div class="ts-schedule-status-temps">
            <span class="ts-schedule-status-temp">{current_temp_display}</span>
            <span class="ts-schedule-status-arrow">→</span>
            <span class="ts-schedule-status-temp">{target_temp}°C</span>
          </div>
          <div class="ts-schedule-status-labels">
            <span>현재</span><span>목표</span>
          </div>
          <div class="ts-schedule-progress-track">
            <div class="ts-schedule-progress-fill" style="width:{progress_pct}%"></div>
          </div>
          <p class="ts-schedule-status-caption">
            {precool["precool_start"]:%H:%M} 시작 · 예상 도달 {precool["expected_reach"]:%H:%M}
            · 예약 시각 {precool["start"]:%H:%M} 전 목표 도달
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
elif status == "진행 중":
    active = active_progress(schedule)
    progress_pct = round(active["progress"] * 100) if active else 100
    st.markdown(
        f"""
        <div class="ts-schedule-status-card">
          <p class="ts-schedule-status-title">{_BOLT_ICON}냉방 진행 중</p>
          <div class="ts-schedule-status-temps">
            <span class="ts-schedule-status-temp">{current_temp_display}</span>
            <span class="ts-schedule-status-arrow">→</span>
            <span class="ts-schedule-status-temp">{target_temp}°C</span>
          </div>
          <div class="ts-schedule-status-labels">
            <span>현재</span><span>목표</span>
          </div>
          <div class="ts-schedule-progress-track">
            <div class="ts-schedule-progress-fill" style="width:{progress_pct}%"></div>
          </div>
          <p class="ts-schedule-status-caption">
            {active["start"]:%H:%M} 시작 · {active["end"]:%H:%M} 종료 · 목표 온도까지 {progress_pct}%
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
elif status == "완료":
    st.markdown(
        '<div class="ts-schedule-status-card ts-schedule-status-card-muted">'
        "<p class=\"ts-schedule-status-title\">예약이 종료됐어요</p></div>",
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        '<div class="ts-schedule-status-card ts-schedule-status-card-muted">'
        "<p class=\"ts-schedule-status-title\">예약 대기 중이에요</p></div>",
        unsafe_allow_html=True,
    )

with st.container(key="ts_schedule_info_card", border=True):
    st.markdown(
        f'<p class="ts-schedule-card-title">{_CALENDAR_ICON}예약 정보</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="ts-schedule-info-row">
          <span class="ts-schedule-info-label">공간</span>
          <span class="ts-schedule-info-value">{room["name"]}</span>
        </div>
        <div class="ts-schedule-info-row">
          <span class="ts-schedule-info-label">일정</span>
          <span class="ts-schedule-info-value">오늘 {schedule["start_time"]}-{schedule["end_time"]}</span>
        </div>
        <div class="ts-schedule-info-row">
          <span class="ts-schedule-info-label">목표 온도</span>
          <span class="ts-schedule-info-value">{target_temp}°C</span>
        </div>
        <div class="ts-schedule-info-row">
          <span class="ts-schedule-info-label">반복</span>
          <span class="ts-schedule-info-value">{repeat_days_label(schedule)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

edit_col, cancel_col = st.columns(2, gap="small")
with edit_col:
    if st.button(
        "예약 수정",
        key="schedule_detail_edit",
        icon=":material/edit:",
        use_container_width=True,
    ):
        st.session_state["_ts_editing_schedule"] = schedule["id"]
        st.switch_page("pages/schedule_create.py")
with cancel_col:
    if st.button(
        "예약 취소",
        key="schedule_detail_cancel",
        icon=":material/event_busy:",
        use_container_width=True,
    ):
        _confirm_cancel(schedule["id"])
