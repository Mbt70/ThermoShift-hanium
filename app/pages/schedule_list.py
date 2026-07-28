import streamlit as st

from app.components.auth_store import is_logged_in
from app.components.mobile_ui import apply_mobile_styles, bottom_tab_bar, page_header
from app.components.room_store import get_room
from app.components.schedule_store import list_today_schedules, schedule_status

_STATUS_META = {
    "완료": "ts-schedule-badge-done",
    "진행 중": "ts-schedule-badge-active",
    "예정": "ts-schedule-badge-upcoming",
}

apply_mobile_styles("schedule_list", shared=("schedule",))

if not is_logged_in():
    st.switch_page("pages/login.py")

room_id = st.session_state.get("_ts_selected_room")
room = get_room(room_id) if room_id else None

if room is None:
    st.switch_page("pages/room_list.py")

page_header("예약 스케줄", back_page="pages/home.py")

st.markdown('<p class="ts-schedule-day-label">오늘</p>', unsafe_allow_html=True)

schedules = list_today_schedules(room["id"])

for schedule in schedules:
    status = schedule_status(schedule)
    badge_class = _STATUS_META[status]
    with st.container(key=f"ts_schedule_card_{schedule['id']}", border=True):
        clicked = st.button(
            f"{schedule['start_time']}-{schedule['end_time']}",
            key=f"ts_schedule_open_{schedule['id']}",
            use_container_width=True,
        )
        st.markdown(
            f"""
            <div class="ts-schedule-row">
              <p class="ts-schedule-time">{schedule["start_time"]}-{schedule["end_time"]}
                · 목표 {schedule["target_temperature"]}°C</p>
              <span class="ts-schedule-badge {badge_class}">{status}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    if clicked:
        st.session_state["_ts_selected_schedule"] = schedule["id"]
        st.switch_page("pages/schedule_detail.py")

st.markdown('<div class="ts-schedule-add-space"></div>', unsafe_allow_html=True)
add_clicked = st.button(
    "냉방 예약하기",
    key="schedule_add",
    icon=":material/add:",
    use_container_width=True,
)
if add_clicked:
    st.session_state.pop("_ts_editing_schedule", None)
    st.switch_page("pages/schedule_create.py")

bottom_tab_bar(active="home")
