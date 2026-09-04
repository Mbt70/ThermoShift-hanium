import sys
from pathlib import Path

import streamlit as st

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from app.components.room_store import list_rooms
from components.auth_store import current_user_id, is_logged_in
from components.dash_shell import render_sidebar
from components.mobile_ui import apply_mobile_styles
from shared.api_client import ApiError, api_post

apply_mobile_styles("copilot", shared=("dash_shell", "home"))

if not is_logged_in():
    st.switch_page("pages/login.py")

rooms = list_rooms(current_user_id())
selected_id = st.session_state.get("_web_selected_room")
if selected_id and not any(room["id"] == selected_id for room in rooms):
    selected_id = None
if selected_id is None and rooms:
    selected_id = rooms[0]["id"]
    st.session_state["_web_selected_room"] = selected_id
room = next((item for item in rooms if item["id"] == selected_id), None)

history_key = f"_copilot_history_{selected_id}"
proposal_key = f"_copilot_proposal_{selected_id}"
st.session_state.setdefault(history_key, [])


def ask(message: str) -> None:
    st.session_state[history_key].append({"role": "user", "content": message})
    try:
        response = api_post(
            "/ai/copilot/chat",
            json={"room_id": room["id"], "message": message},
            timeout=35,
        )
    except ApiError as exc:
        st.session_state[history_key].append({
            "role": "assistant",
            "content": f"요청을 처리하지 못했습니다: {exc.message or exc}",
            "error": True,
        })
        return
    st.session_state[history_key].append({
        "role": "assistant",
        "content": response["message"],
        "tools_used": response.get("tools_used", []),
        "planner": response.get("planner"),
        "result": response.get("result"),
    })
    if response.get("action_proposal"):
        st.session_state[proposal_key] = response["action_proposal"]


sidebar_col, main_col = st.columns([1, 4], gap="small")
with sidebar_col:
    render_sidebar("copilot")

with main_col:
    if not rooms or room is None:
        st.switch_page("pages/devices.py")

    title_col, room_col = st.columns([3, 1], vertical_alignment="center")
    with title_col:
        st.title("ThermoShift 운영 코파일럿")
        st.caption("센서와 모델을 도구로 조회하고, 실제 제어는 승인 후 기존 안전 경로로 전달합니다.")
    with room_col:
        names = [item["name"] for item in rooms]
        current_index = next(i for i, item in enumerate(rooms) if item["id"] == room["id"])
        picked = st.selectbox("공간", names, index=current_index)
        picked_room = next(item for item in rooms if item["name"] == picked)
        if picked_room["id"] != room["id"]:
            st.session_state["_web_selected_room"] = picked_room["id"]
            st.rerun()

    st.info(
        "코파일럿은 MQTT를 직접 조작하지 않습니다. 제어 요청은 먼저 제안 카드가 되고, "
        "승인 후에도 API 소유권 검사와 게이트웨이 안전 조건을 통과해야 합니다."
    )

    quick_prompts = (
        "현재 센서 상태 알려줘",
        "현재 모델 학습 상태 알려줘",
        "최근 실험 데이터 품질 알려줘",
        "내일 실험 준비됐는지 확인해줘",
        "지금 값으로 MPC 시뮬레이션해줘",
    )
    quick_cols = st.columns(len(quick_prompts))
    quick_message = None
    for index, (column, prompt) in enumerate(zip(quick_cols, quick_prompts)):
        with column:
            if st.button(prompt, key=f"copilot_quick_{index}", width="stretch"):
                quick_message = prompt

    for item in st.session_state[history_key]:
        with st.chat_message(item["role"]):
            st.markdown(item["content"])
            if item.get("tools_used"):
                st.caption(
                    f"도구: {' → '.join(item['tools_used'])} · 계획기: {item.get('planner')}"
                )
            if item.get("result"):
                with st.expander("근거 데이터 보기"):
                    st.json(item["result"])

    pending = st.session_state.get(proposal_key)
    if pending:
        proposal_type = pending.get("proposal_type", "hvac_command")
        with st.container(border=True):
            if proposal_type == "hvac_command":
                command = pending["command"]
                st.subheader("승인이 필요한 제어 제안")
                target = (
                    f" · 목표 {command['target_temp']}°C"
                    if command.get("target_temp") is not None else ""
                )
                st.write(f"명령: `{command['command_type']}`{target}")
                st.warning("아직 실행되지 않았습니다. 승인하면 pending 큐에 들어가며 sent는 장치 ACK와 다릅니다.")
                confirmed = st.checkbox(
                    "대상 공간과 명령을 확인했습니다.", key=f"copilot_confirm_{room['id']}"
                )
                approve_col, cancel_col = st.columns(2)
                with approve_col:
                    if st.button(
                        "승인하고 명령 큐에 넣기",
                        type="primary",
                        disabled=not confirmed,
                        width="stretch",
                    ):
                        try:
                            queued = api_post(pending["approval_endpoint"], json=command)
                            st.success(
                                f"명령 #{queued['command_id']}이 {queued['command_status']} 상태로 등록됐습니다."
                            )
                            st.session_state.pop(proposal_key, None)
                        except ApiError as exc:
                            st.error(f"승인되지 않았습니다: {exc.message or exc}")
                with cancel_col:
                    if st.button("제안 취소", width="stretch"):
                        st.session_state.pop(proposal_key, None)
                        st.rerun()
            else:
                experiment = pending.get("experiment") or {}
                title = "실험 시작 제안" if proposal_type == "experiment_start" else "실험 중단 제안"
                st.subheader(title)
                if proposal_type == "experiment_start":
                    st.write(
                        f"계획: `{experiment.get('plan_key')}` · 약 "
                        f"{experiment.get('duration_min')}분"
                    )
                    for action in experiment.get("manual_actions", []):
                        st.write(f"- {action}")
                    readiness = pending.get("readiness") or {}
                    st.write(f"자동 사전점검: `{'READY' if readiness.get('ready') else 'BLOCKED'}`")
                else:
                    st.write(f"대상 Run: `{experiment.get('run_id', '진행 중인 run 없음')}`")
                st.warning(
                    "안전을 위해 이 카드는 제안 전용입니다. 실험 run 생성·중단 또는 MQTT 출력은 수행하지 않습니다."
                )
                if st.button("제안 닫기", width="stretch"):
                    st.session_state.pop(proposal_key, None)
                    st.rerun()

    typed_message = st.chat_input("예: 내일 실험 준비됐어? / 최근 run은 학습에 쓸 수 있어? / 25도로 설정해줘")
    message = typed_message or quick_message
    if message:
        ask(message)
        st.rerun()
