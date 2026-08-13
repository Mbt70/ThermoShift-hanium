import streamlit as st

from app.components.auth_store import is_logged_in
from app.components.mobile_ui import apply_mobile_styles, page_header
from app.components.room_store import delete_room, get_room, update_room

apply_mobile_styles("room_settings", shared=("room_form",))

if not is_logged_in():
    st.switch_page("pages/login.py")

return_page = st.session_state.get("_ts_room_settings_return", "pages/room_list.py")

page_header("공간 설정", back_page=return_page)

room_id = st.session_state.get("_ts_selected_room")
room = get_room(room_id) if room_id else None

if room is None:
    st.switch_page(return_page)

st.markdown(
    '<p class="ts-settings-hint">공간 이름 위치 평면도를 수정할 수 있어요</p>',
    unsafe_allow_html=True,
)

with st.container(key="room_fields", border=False):
    name = st.text_input(
        "공간 이름", value=room["name"], icon=":material/meeting_room:"
    )
    location = st.text_input(
        "위치", value=room["location"], icon=":material/location_on:"
    )
    floor_plan = st.file_uploader(
        "평면도",
        type=["png", "jpg", "jpeg"],
        key="room_settings_floor_plan",
    )

st.markdown('<div class="ts-room-submit-space"></div>', unsafe_allow_html=True)
delete_col, save_col = st.columns(2, gap="small")
with delete_col:
    delete_clicked = st.button(
        "삭제", key="room_settings_delete", use_container_width=True
    )
with save_col:
    save_clicked = st.button(
        "저장", key="room_settings_save", use_container_width=True
    )

if delete_clicked:
    delete_room(room["id"])
    st.session_state.pop("_ts_selected_room", None)
    st.switch_page(return_page)

if save_clicked:
    update_room(
        room["id"],
        name=name,
        location=location,
        floor_plan_name=floor_plan.name if floor_plan is not None else None,
    )
    st.switch_page(return_page)
