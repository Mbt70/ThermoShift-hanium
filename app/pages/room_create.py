import streamlit as st

from app.components.auth_store import is_logged_in
from app.components.mobile_ui import apply_mobile_styles, inline_error, page_header
from app.components.room_store import register_room

apply_mobile_styles("room_create", shared=("room_form",))

if not is_logged_in():
    st.switch_page("pages/login.py")

page_header("공간 등록", back_page="pages/room_list.py")

with st.container(key="room_fields", border=False):
    name = st.text_input(
        "공간 이름",
        placeholder="중앙대 도서관 팀플룸",
        icon=":material/meeting_room:",
    )
    location = st.text_input(
        "위치",
        placeholder="중앙대학교 도서관 3층",
        icon=":material/location_on:",
    )
    floor_plan = st.file_uploader(
        "평면도",
        type=["png", "jpg", "jpeg"],
        key="room_create_floor_plan",
    )
    floor_plan_error = st.empty()

st.markdown('<div class="ts-room-submit-space"></div>', unsafe_allow_html=True)
submitted = st.button(
    "등록하기",
    key="room_create_submit",
    use_container_width=True,
)

if submitted:
    valid = bool(name) and bool(location) and floor_plan is not None
    if floor_plan is None:
        with floor_plan_error:
            inline_error("이미지 형식이 올바르지 않습니다")
    if valid:
        register_room(name, location, floor_plan.name)
        st.switch_page("pages/room_list.py")
