import base64
from pathlib import Path

import streamlit as st

from app.components.auth_store import current_user_name, is_logged_in
from app.components.mobile_ui import apply_mobile_styles
from app.components.room_store import list_rooms, room_status

ICONS_DIR = Path(__file__).resolve().parents[1] / "assets" / "icons"

_STATUS_BADGE_ICON = {
    "정상": "success.svg",
    "주의": "warning.svg",
    "오류": "error.svg",
}


def _icon_data_uri(file_name: str) -> str:
    encoded = base64.b64encode((ICONS_DIR / file_name).read_bytes()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def greeting_header(name: str) -> None:
    with st.container(key="ts_greeting_header"):
        st.markdown(
            f"""
            <div class="ts-greeting-row">
              <div class="ts-greeting-text">
                <p>안녕하세요</p>
                <h1>{name}님</h1>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def dashed_action_button(label: str, page: str, *, key: str) -> None:
    clicked = st.button(
        label,
        key=key,
        icon=":material/add:",
        use_container_width=True,
    )
    if clicked:
        st.switch_page(page)


def room_card(room: dict) -> None:
    temperature = (
        f"{room['temperature']:.1f}°C" if room["temperature"] is not None else "--"
    )
    aircon_label = "ON" if room["aircon_on"] else "OFF"
    sensor_label = "신호양호" if room.get("sensor_connected") else "비연결"
    status_label = room_status(room)
    badge_uri = _icon_data_uri(_STATUS_BADGE_ICON[status_label])
    thermo_uri = _icon_data_uri("thermostat.svg")
    snow_uri = _icon_data_uri("snow.svg")
    sensor_uri = _icon_data_uri("sensor.svg")

    with st.container(key=f"ts_room_card_{room['id']}", border=True):
        clicked = st.button(
            room["name"],
            key=f"ts_room_open_{room['id']}",
            use_container_width=True,
        )
        content_col, badge_col = st.columns(
            [3, 1], gap="small", vertical_alignment="center"
        )
        with content_col:
            st.markdown(
                f"""
                <p class="ts-room-name">{room["name"]}</p>
                <div class="ts-room-meta">
                  <span class="ts-room-stat">
                    <img src="{thermo_uri}" alt="" class="ts-room-stat-icon" />{temperature}
                  </span>
                  <span class="ts-room-stat">
                    <img src="{snow_uri}" alt="" class="ts-room-stat-icon" />{aircon_label}
                  </span>
                  <span class="ts-room-stat">
                    <img src="{sensor_uri}" alt="" class="ts-room-stat-icon" />{sensor_label}
                  </span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with badge_col:
            st.markdown(
                f"""
                <div class="ts-room-badge-wrap">
                  <img src="{badge_uri}" alt="{status_label}" class="ts-room-badge-img" />
                </div>
                """,
                unsafe_allow_html=True,
            )

    if clicked:
        st.session_state["_ts_selected_room"] = room["id"]
        st.switch_page("pages/home.py")


apply_mobile_styles("room_list")

if not is_logged_in():
    st.switch_page("pages/login.py")

greeting_header(current_user_name())

rooms = list_rooms()

if rooms:
    st.markdown(
        f'<p class="ts-room-count">관리 공간 {len(rooms)}곳</p>',
        unsafe_allow_html=True,
    )
    for room in rooms:
        room_card(room)

dashed_action_button("새 공간 등록", "pages/room_create.py", key="add_room_action")
