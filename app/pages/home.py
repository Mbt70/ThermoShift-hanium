import streamlit as st

from app.components.auth_store import is_logged_in
from app.components.mobile_ui import apply_mobile_styles
from app.components.room_store import get_room

apply_mobile_styles("home")

if not is_logged_in():
    st.switch_page("pages/login.py")

room_id = st.session_state.get("_ts_selected_room")
room = get_room(room_id) if room_id else None

st.write(f"{room['name']} 홈" if room else "홈")

if room:
    st.page_link("pages/room_settings.py", label="공간 설정", icon=":material/settings:")
