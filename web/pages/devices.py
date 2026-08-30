import sys
from pathlib import Path

import streamlit as st

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from app.components.room_store import delete_room, list_rooms, register_room, update_room
from app.components.sensor_store import list_sensors, sensor_type_label, set_sensor_enabled
from components.auth_store import current_user_id, is_logged_in
from components.dash_shell import render_sidebar, render_topbar
from components.mobile_ui import apply_mobile_styles, inline_error, recolored_icon_data_uri

_BUILDING_ICON = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="7" y="7" width="10" height="10" rx="1.5"/>'
    '<path d="M9.5 7V4M14.5 7V4M9.5 20v-3M14.5 20v-3M7 9.5H4M7 14.5H4M20 9.5h-3M20 14.5h-3"/></svg>'
)
_STATUS_LABELS = {"normal": "정상", "offline": "오프라인", "error": "오류"}
_STATUS_CLASSES = {"normal": "is-success", "offline": "is-offline", "error": "is-error"}
apply_mobile_styles("devices", shared=("dash_shell",))

if not is_logged_in():
    st.switch_page("pages/login.py")

rooms = list_rooms(current_user_id())

sidebar_col, main_col = st.columns([1, 4], gap="small")

with sidebar_col:
    render_sidebar("devices")

with main_col:
    render_topbar("공간 디바이스 관리")

    with st.container(key="ts_dev_tabs"):
        tab_choice = st.pills(
            "탭", ["공간", "센서 장비"], default="공간", key="devices_tab", label_visibility="collapsed"
        ) or "공간"

    if tab_choice == "센서 장비":
        room_names = [r["name"] for r in rooms]
        current_room_id = st.session_state.get("_web_selected_room") or (rooms[0]["id"] if rooms else None)
        current_index = next((i for i, r in enumerate(rooms) if r["id"] == current_room_id), 0) if rooms else 0

        picked_name = st.selectbox(
            "공간 선택", room_names, index=current_index, key="devices_room_select", label_visibility="collapsed"
        )
        picked_room = next((r for r in rooms if r["name"] == picked_name), None)
        selected_room_id = picked_room["id"] if picked_room else current_room_id

        @st.fragment(run_every=5)
        def render_live_sensors(room_id):
            sensors = list_sensors(room_id) if room_id else []

            with st.container(key="ts_dash_sensor_card", border=True):
                sensor_icon_uri = recolored_icon_data_uri("sensors.svg", "#397f80")
                st.markdown(
                    f'<p class="ts-dash-card-title"><img class="ts-sensor-title-icon" src="{sensor_icon_uri}" alt="" />센서 장비 목록</p>',
                    unsafe_allow_html=True,
                )
                if sensors:
                    head_cols = st.columns([1.2, 1.6, 1.8, 1.2, 0.8], vertical_alignment="center")
                    for col, label in zip(head_cols, ["노드 ID", "유형", "설치위치", "통신 상태", "활성"]):
                        with col:
                            st.markdown(f'<span class="ts-sensor-head">{label}</span>', unsafe_allow_html=True)

                    for sensor in sensors:
                        row_cols = st.columns([1.2, 1.6, 1.8, 1.2, 0.8], vertical_alignment="center")
                        with row_cols[0]:
                            st.markdown(f'<span class="ts-sensor-node">{sensor["name"]}</span>', unsafe_allow_html=True)
                        with row_cols[1]:
                            st.markdown(
                                f'<span class="ts-sensor-type">{sensor_type_label(sensor["type"])}</span>',
                                unsafe_allow_html=True,
                            )
                        with row_cols[2]:
                            if sensor.get("location"):
                                st.markdown(
                                    f'<span class="ts-sensor-location">{sensor["location"]}</span>',
                                    unsafe_allow_html=True,
                                )
                        with row_cols[3]:
                            status = sensor.get("status")
                            if status and status != "unknown":
                                st.markdown(
                                    f'<span class="ts-sensor-status {_STATUS_CLASSES.get(status, "is-offline")}">'
                                    f'<span class="ts-sensor-status-dot"></span>{_STATUS_LABELS.get(status, status)}</span>',
                                    unsafe_allow_html=True,
                                )
                            else:
                                st.markdown('<span class="ts-sensor-status is-offline">대기</span>', unsafe_allow_html=True)
                        with row_cols[4]:
                            enabled = st.toggle(
                                sensor["name"],
                                value=sensor["enabled"],
                                key=f"dev_sensor_toggle_{sensor['id']}",
                                label_visibility="collapsed",
                            )
                            if enabled != sensor["enabled"]:
                                set_sensor_enabled(sensor["id"], enabled)
                                st.rerun()
                else:
                    st.markdown(
                        '<p class="ts-dash-list-empty">등록된 센서 장비가 없습니다</p>',
                        unsafe_allow_html=True,
                    )

        render_live_sensors(selected_room_id)
    else:
        list_col, form_col = st.columns([3, 2], gap="medium")

        with list_col:
            with st.container(key="ts_dash_room_list_card", border=True):
                st.markdown(
                    f'<p class="ts-dash-card-title">{_BUILDING_ICON}등록된 공간 {len(rooms)}</p>',
                    unsafe_allow_html=True,
                )
                if rooms:
                    header_col, _edit_head, _delete_head = st.columns([7, 1, 1])
                    with header_col:
                        st.markdown(
                            '<div class="ts-dev-room-row ts-dev-room-header"><span>공간</span><span>위치</span></div>',
                            unsafe_allow_html=True,
                        )
                    for r in rooms:
                        row_col, edit_col, delete_col = st.columns([7, 1, 1], vertical_alignment="center")
                        with row_col:
                            st.markdown(
                                f"""
                                <div class="ts-dev-room-row">
                                  <span class="ts-dev-room-name">{r["name"]}</span>
                                  <span class="ts-dev-room-loc">{r.get("location", "")}</span>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )
                        with edit_col:
                            if st.button(
                                "edit", key=f"dev_edit_{r['id']}", icon=":material/edit:", width="stretch"
                            ):
                                st.session_state["_devices_editing"] = r["id"]
                                st.rerun()
                        with delete_col:
                            if st.button(
                                "delete",
                                key=f"dev_delete_{r['id']}",
                                icon=":material/delete:",
                                width="stretch",
                            ):
                                delete_room(r["id"])
                                if st.session_state.get("_web_selected_room") == r["id"]:
                                    st.session_state.pop("_web_selected_room", None)
                                st.rerun()

                        if st.session_state.get("_devices_editing") == r["id"]:
                            with st.form(f"dev_edit_form_{r['id']}", border=False):
                                new_name = st.text_input("공간 이름", value=r["name"], key=f"dev_edit_name_{r['id']}")
                                new_loc = st.text_input(
                                    "위치", value=r.get("location", ""), key=f"dev_edit_loc_{r['id']}"
                                )
                                edit_col1, edit_col2 = st.columns(2)
                                with edit_col1:
                                    cancel = st.form_submit_button("취소", width="stretch")
                                with edit_col2:
                                    save = st.form_submit_button("저장", width="stretch")
                            if save and new_name and new_loc:
                                update_room(r["id"], name=new_name, location=new_loc, floor_plan_name=None)
                                st.session_state.pop("_devices_editing", None)
                                st.rerun()
                            elif cancel:
                                st.session_state.pop("_devices_editing", None)
                                st.rerun()
                else:
                    st.markdown(
                        '<p class="ts-dash-list-empty">등록된 공간이 없습니다</p>',
                        unsafe_allow_html=True,
                    )

        with form_col:
            with st.container(key="ts_dash_room_form_card", border=True):
                st.markdown('<p class="ts-dash-card-title">공간 등록</p>', unsafe_allow_html=True)
                with st.container(key="dev_room_fields", border=False):
                    name = st.text_input(
                        "공간 이름", placeholder="예: 팀플룸 1", icon=":material/meeting_room:", key="dev_new_name"
                    )
                    location = st.text_input(
                        "위치", placeholder="건물, 층", icon=":material/location_on:", key="dev_new_location"
                    )
                    floor_plan = st.file_uploader(
                        "평면도", type=["png", "jpg", "jpeg"], key="dev_new_floor_plan"
                    )
                    error_slot = st.empty()
                submitted = st.button("등록하기", key="dev_register_submit", width="stretch")
                if submitted:
                    if name and location:
                        register_room(
                            name, location, floor_plan.name if floor_plan else "", current_user_id()
                        )
                        st.toast(f"'{name}' 공간이 등록됐어요", icon="✅")
                        st.rerun()
                    else:
                        with error_slot:
                            inline_error("공간 이름과 위치를 입력해주세요")
