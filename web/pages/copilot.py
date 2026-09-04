import html
import sys
from pathlib import Path

import streamlit as st

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from app.components.room_store import list_rooms
from components.auth_store import current_user_id, is_demo_session, is_logged_in
from components.dash_shell import render_sidebar
from components.mobile_ui import apply_mobile_styles
from shared.api_client import ApiError, api_get, api_post

apply_mobile_styles("copilot", shared=("dash_shell",))

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

if not rooms or room is None:
    st.switch_page("pages/devices.py")

history_key = f"_copilot_history_{selected_id}"
proposal_key = f"_copilot_proposal_{selected_id}"
tracking_key = f"_copilot_command_tracking_{selected_id}"
st.session_state.setdefault(history_key, [])


def _friendly_error(exc: ApiError) -> str:
    text = exc.message or str(exc)
    for prefix in ('{"detail":"', "{'detail': '"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            text = text.rstrip("'}\"")
            break
    return text[:240]


def ask(message: str) -> None:
    st.session_state[history_key].append({"role": "user", "content": message})
    try:
        with st.spinner("센서와 제어 기록을 확인하고 있어요…"):
            response = api_post(
                "/ai/copilot/chat",
                json={"room_id": room["id"], "message": message},
                timeout=35,
            )
    except ApiError as exc:
        st.session_state[history_key].append({
            "role": "assistant",
            "content": (
                "요청을 끝까지 처리하지 못했어요. 장치나 네트워크 상태를 확인한 뒤 "
                f"다시 시도해 주세요.\n\n`{_friendly_error(exc)}`"
            ),
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


def _value(value, suffix="", digits=1) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return html.escape(str(value))


@st.fragment(run_every="10s")
def render_live_context() -> None:
    try:
        payload = api_post(
            "/ai/copilot/tools/get_live_snapshot",
            json={"room_id": room["id"], "arguments": {}},
            timeout=5,
        )
        snapshot = payload.get("result") or {}
    except ApiError:
        st.markdown(
            '<div class="ts-copilot-live is-offline"><span></span>상태 연결 지연</div>',
            unsafe_allow_html=True,
        )
        return

    env = snapshot.get("environment") or {}
    occupancy = snapshot.get("occupancy") or {}
    power = snapshot.get("power") or {}
    door = snapshot.get("door") or {}
    last_command = snapshot.get("last_command") or {}
    room_state = snapshot.get("room") or {}
    command_status = last_command.get("command_status") or "기록 없음"
    st.markdown(
        f"""
        <div class="ts-copilot-live"><span></span>실시간 연동 · 10초</div>
        <div class="ts-copilot-snapshot">
          <div><small>온도</small><strong>{_value(env.get('temperature'), '°C')}</strong></div>
          <div><small>습도</small><strong>{_value(env.get('humidity'), '%')}</strong></div>
          <div><small>CO₂</small><strong>{_value(env.get('co2'), ' ppm', 0)}</strong></div>
          <div><small>재실</small><strong>{html.escape(str(occupancy.get('occupancy_state') or '—'))}</strong></div>
          <div><small>문</small><strong>{html.escape(str(door.get('door_state') or '—'))}</strong></div>
          <div><small>전력</small><strong>{_value(power.get('power_w'), ' W')}</strong></div>
        </div>
        <div class="ts-copilot-last-command">
          <span>모드 {html.escape(str(room_state.get('control_mode') or '—'))}</span>
          <strong>최근 제어 {html.escape(str(command_status))}</strong>
        </div>
        """,
        unsafe_allow_html=True,
    )


_STATUS_LABELS = {
    "pending": ("요청 접수", "API가 명령을 안전 큐에 등록했습니다.", 25),
    "sent": ("장치 확인 중", "게이트웨이가 전송했고 릴레이 상태 응답을 기다립니다.", 65),
    "acked": ("동작 확인 완료", "장치가 목표 상태를 직접 회신했습니다.", 100),
    "failed": ("실행 차단", "안전 조건 또는 전송 과정에서 명령이 차단됐습니다.", 100),
    "timeout": ("응답 시간 초과", "120초 안에 장치 상태를 확인하지 못했습니다.", 100),
}


@st.fragment(run_every="2s")
def render_command_tracking() -> None:
    tracked = st.session_state.get(tracking_key)
    if not tracked:
        return
    try:
        command = api_get(f"/commands/{tracked['command_id']}")
    except ApiError as exc:
        st.error(f"명령 상태를 불러오지 못했어요: {_friendly_error(exc)}")
        return

    status = command.get("command_status", "pending")
    label, description, progress = _STATUS_LABELS.get(
        status, (status, "상태를 확인하고 있습니다.", 40)
    )
    terminal = status in {"acked", "failed", "timeout"}
    tone = "is-success" if status == "acked" else "is-error" if terminal else "is-running"
    st.markdown(
        f"""
        <div class="ts-command-progress {tone}">
          <div class="ts-command-progress-head">
            <span class="ts-command-pulse"></span>
            <div><small>명령 #{command.get('command_id')}</small><strong>{html.escape(label)}</strong></div>
            <b>{progress}%</b>
          </div>
          <div class="ts-command-progress-track"><i style="width:{progress}%"></i></div>
          <p>{html.escape(description)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if terminal:
        detail = command.get("result_message")
        if detail:
            st.caption(f"장치 기록: {detail}")
        if st.button("확인하고 상태 카드 닫기", key=f"close_command_{command['command_id']}"):
            st.session_state.pop(tracking_key, None)
            st.rerun()


def render_proposal() -> None:
    pending = st.session_state.get(proposal_key)
    if not pending:
        return
    proposal_type = pending.get("proposal_type", "hvac_command")
    with st.container(key="copilot_approval_card", border=True):
        st.markdown('<p class="ts-proposal-eyebrow">승인이 필요한 작업</p>', unsafe_allow_html=True)
        if proposal_type == "hvac_command":
            command = pending["command"]
            labels = {
                "power_on": "냉각 장치 켜기",
                "power_off": "냉각 장치 끄기",
                "set_temp": "목표 온도 변경 후 냉각",
            }
            label = labels.get(command["command_type"], command["command_type"])
            target = (
                f" · {command['target_temp']}°C"
                if command.get("target_temp") is not None else ""
            )
            st.subheader(f"{label}{target}")
            st.markdown(
                "API 안전 검사 → 단일 명령 큐 → Raspberry Pi 게이트웨이 → "
                "MQTT → 릴레이 → 상태 ACK 순서로 실행됩니다."
            )
            st.warning("승인은 실제 펠티어·팬 동작으로 이어질 수 있습니다.")
            demo = is_demo_session()
            confirmed = st.checkbox(
                "대상 공간과 실제 장치 동작을 확인했습니다.",
                key=f"copilot_confirm_{pending.get('proposal_id', room['id'])}",
                disabled=demo,
            )
            if demo:
                st.caption("체험 세션에서는 실제 제어를 승인할 수 없습니다.")
            approve_col, cancel_col = st.columns(2)
            with approve_col:
                if st.button(
                    "승인하고 실행",
                    type="primary",
                    disabled=not confirmed or demo,
                    width="stretch",
                ):
                    try:
                        queued = api_post(pending["approval_endpoint"], json=command)
                    except ApiError as exc:
                        st.error(f"실행하지 못했어요: {_friendly_error(exc)}")
                    else:
                        st.session_state[tracking_key] = {
                            "command_id": queued["command_id"],
                            "command_type": command["command_type"],
                        }
                        st.session_state[history_key].append({
                            "role": "assistant",
                            "content": (
                                f"명령 #{queued['command_id']}을 안전 큐에 등록했어요. "
                                "아래 상태 카드에서 장치 확인까지 계속 추적할게요."
                            ),
                        })
                        st.session_state.pop(proposal_key, None)
                        st.rerun()
            with cancel_col:
                if st.button("취소", key="cancel_control_proposal", width="stretch"):
                    st.session_state.pop(proposal_key, None)
                    st.rerun()
        else:
            experiment = pending.get("experiment") or {}
            title = "실험 시작 준비" if proposal_type == "experiment_start" else "실험 중단 준비"
            st.subheader(title)
            if proposal_type == "experiment_start":
                st.write(
                    f"**{experiment.get('plan_key')}** · 약 {experiment.get('duration_min')}분 · "
                    f"{experiment.get('purpose', '')}"
                )
                for action in experiment.get("manual_actions", []):
                    st.markdown(f"- {action}")
                readiness = pending.get("readiness") or {}
                badge = "READY" if readiness.get("ready") else "BLOCKED"
                st.markdown(f"자동 사전점검: **{badge}**")
            else:
                st.write(f"대상 Run: **{experiment.get('run_id', '진행 중인 run 없음')}**")
            st.info(
                "히터가 수동 ON/OFF 방식이므로 실험 제어는 아직 자동 실행하지 않습니다. "
                "장치 상태와 작업자를 확인한 뒤 단계별 안내 모드로 연결할 예정입니다."
            )
            if st.button("확인", key="close_experiment_proposal", width="stretch"):
                st.session_state.pop(proposal_key, None)
                st.rerun()


sidebar_col, main_col = st.columns([1, 4], gap="small")
with sidebar_col:
    render_sidebar("copilot")

with main_col:
    with st.container(key="copilot_header"):
        title_col, room_col = st.columns([3, 1], vertical_alignment="center")
        with title_col:
            st.markdown(
                """
                <div class="ts-copilot-title">
                  <span class="ts-copilot-bot">T</span>
                  <div><h1>Thermo Copilot</h1><p>쾌적도와 에너지를 함께 보는 운영 에이전트</p></div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with room_col:
            names = [item["name"] for item in rooms]
            current_index = next(i for i, item in enumerate(rooms) if item["id"] == room["id"])
            picked = st.selectbox("대상 공간", names, index=current_index, label_visibility="collapsed")
            picked_room = next(item for item in rooms if item["name"] == picked)
            if picked_room["id"] != room["id"]:
                st.session_state["_web_selected_room"] = picked_room["id"]
                st.rerun()

    with st.container(key="copilot_workspace"):
        chat_col, context_col = st.columns([2.25, 1], gap="medium")

        with chat_col:
            with st.container(key="copilot_chat_toolbar"):
                st.markdown(
                    '<div><strong>대화</strong><span>측정값과 실행 결과를 근거로 답해요</span></div>',
                    unsafe_allow_html=True,
                )
                if st.button("새 대화", key="copilot_clear", help="대화 내용 지우기"):
                    st.session_state[history_key] = []
                    st.session_state.pop(proposal_key, None)
                    st.rerun()

            if not st.session_state[history_key]:
                st.markdown(
                    f"""
                    <div class="ts-copilot-welcome">
                      <span class="ts-copilot-welcome-icon">✦</span>
                      <h2>안녕하세요. 무엇을 확인해 볼까요?</h2>
                      <p>{html.escape(room['name'])}의 센서·모델·실험 기록을 조회하고,<br>
                      제어가 필요하면 실행 전에 근거와 영향을 먼저 보여드릴게요.</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                quick_prompts = (
                    ("지금 상태", "현재 센서와 재실 상태를 요약해줘"),
                    ("제어 이유", "최근 제어 판단은 왜 내려졌어?"),
                    ("MPC 비교", "지금 값으로 MPC 시뮬레이션해줘"),
                    ("실험 준비", "내일 실험 준비됐는지 확인해줘"),
                )
                first_row = st.columns(2)
                second_row = st.columns(2)
                quick_message = None
                for index, ((label, prompt), column) in enumerate(
                    zip(quick_prompts, (*first_row, *second_row))
                ):
                    with column:
                        if st.button(
                            f"{label}  →",
                            key=f"copilot_quick_{index}",
                            help=prompt,
                            width="stretch",
                        ):
                            quick_message = prompt
                if quick_message:
                    ask(quick_message)
                    st.rerun()

            for item in st.session_state[history_key]:
                avatar = "❄️" if item["role"] == "assistant" else "🙂"
                with st.chat_message(item["role"], avatar=avatar):
                    st.markdown(item["content"])
                    if item.get("tools_used"):
                        planner = "Gemini" if item.get("planner") == "gemini" else "안전 폴백"
                        st.caption(f"{planner} · {' → '.join(item['tools_used'])}")
                    if item.get("result"):
                        with st.expander("근거 데이터 확인"):
                            st.json(item["result"])

            render_proposal()
            render_command_tracking()

            typed_message = st.chat_input(
                "상태 조회, 실험 준비, MPC 비교 또는 제어 요청을 입력하세요"
            )
            if typed_message:
                ask(typed_message)
                st.rerun()

        with context_col:
            with st.container(key="copilot_context_panel", border=True):
                st.markdown("### 공간 상태")
                st.caption(f"{room['name']} · 측정값 기반")
                render_live_context()
                control_on, control_off = st.columns(2)
                with control_on:
                    if st.button("냉각 켜기", key="copilot_suggest_on", width="stretch"):
                        ask("현재 상태를 확인하고 냉각 장치를 켜줘")
                        st.rerun()
                with control_off:
                    if st.button("냉각 끄기", key="copilot_suggest_off", width="stretch"):
                        ask("냉각 장치를 꺼줘")
                        st.rerun()
            with st.container(key="copilot_safety_panel", border=True):
                st.markdown(
                    """
                    <div class="ts-safety-copy">
                      <span>✓</span><div><strong>안전 실행 경로</strong>
                      <p>AI는 명령을 제안하고, 사용자가 승인한 뒤에도 API와 게이트웨이가 조건을 다시 검사합니다.</p></div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
