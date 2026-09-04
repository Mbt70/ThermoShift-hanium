"""Gemini 를 이용한 해설·진단·리포트.

게이트웨이가 남기는 것은 기계용 코드다(decision_type='off',
reason='EMPTY_CONFIRMED | temp=24.53C ...'). 공간 관리자와 심사위원이
읽으려면 사람 말이 필요하다. 그 변환만 담당한다.

API 키가 없으면 503 을 준다. 프론트는 이 상태에서도 원래 화면을 그대로
보여줘야 한다 — AI 는 부가 기능이지 전제가 아니다.
"""

from datetime import date, datetime, timedelta, timezone
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.db import get_conn
from api.services import ai, copilot_tools
from api.security import get_current_user_id, require_owned_resource, require_room_owner

router = APIRouter(prefix="/ai", tags=["ai"])


class CopilotToolRequest(BaseModel):
    room_id: int = Field(gt=0)
    arguments: dict = Field(default_factory=dict)


class CopilotChatRequest(BaseModel):
    room_id: int = Field(gt=0)
    message: str = Field(min_length=1, max_length=1000)


@router.get("/copilot/tools")
def list_copilot_tools(
    _current_user_id: int = Depends(get_current_user_id),
):
    """LLM과 UI가 사용할 수 있는 허용 도구 목록. 임의 함수 실행은 없다."""
    return {"tools": copilot_tools.TOOL_DEFINITIONS}


@router.post("/copilot/tools/{tool_name}")
def run_copilot_tool(
    tool_name: str,
    body: CopilotToolRequest,
    current_user_id: int = Depends(get_current_user_id),
):
    """허용 목록의 도구 하나를 실행한다. 실제 장치 명령은 만들지 않는다."""
    if tool_name not in copilot_tools.TOOL_NAMES:
        raise HTTPException(status_code=404, detail="unknown copilot tool")
    require_room_owner(body.room_id, current_user_id)
    try:
        result = _execute_copilot_tool(tool_name, body.room_id, body.arguments)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"tool": tool_name, "room_id": body.room_id, "result": result}


def _execute_copilot_tool(tool_name: str, room_id: int, arguments: dict) -> dict:
    if tool_name == "get_model_status":
        return copilot_tools.get_model_status()
    if tool_name == "simulate_mpc":
        return copilot_tools.simulate_mpc(arguments)
    if tool_name == "propose_control_action":
        return copilot_tools.propose_control_action(room_id, arguments)
    return _run_database_copilot_tool(tool_name, room_id, arguments)


def _fallback_copilot_plan(message: str) -> tuple[str, dict]:
    """Gemini 미설정/실패 시에도 기본 조회와 안전한 제안은 동작한다."""
    text = message.strip().lower()
    if "왜" in text or "최근 판단" in text or "제어 근거" in text:
        return "get_recent_decisions", {"limit": 5}
    if "시뮬" in text or "what-if" in text or "mpc" in text:
        return "simulate_mpc", {}
    if "실험" in text or "run" in text:
        return "get_experiment_status", {}
    if "모델" in text or "학습" in text or "pinn" in text or "rc" in text:
        return "get_model_status", {}
    temperature = re.search(r"(1[6-9]|2\d|30)(?:\.\d+)?\s*도", text)
    if temperature and any(word in text for word in ("설정", "맞춰", "변경")):
        return "propose_control_action", {
            "command_type": "set_temp",
            "target_temp": float(temperature.group(0).replace("도", "").strip()),
            "reason": message,
        }
    if any(word in text for word in ("꺼줘", "꺼 줘", "끄자", "정지해")):
        return "propose_control_action", {"command_type": "power_off", "reason": message}
    if any(word in text for word in ("켜줘", "켜 줘", "가동해")):
        return "propose_control_action", {"command_type": "power_on", "reason": message}
    return "get_live_snapshot", {}


def _copilot_summary(tool_name: str, result: dict) -> str:
    if tool_name == "get_live_snapshot":
        env = result.get("environment") or {}
        occ = result.get("occupancy") or {}
        if not env:
            return "아직 환경 센서 측정값이 없습니다. 장치 연결과 마지막 수신 시각을 확인해 주세요."
        return (
            f"최신 측정은 온도 {env.get('temperature')}°C, 습도 {env.get('humidity')}%, "
            f"CO₂ {env.get('co2')}ppm입니다. 재실 상태는 "
            f"{occ.get('occupancy_state', 'unknown')}이며 측정 시각은 {env.get('measured_at')}입니다."
        )
    if tool_name == "get_recent_decisions":
        decisions = result.get("decisions") or []
        if not decisions:
            return "저장된 제어 판단이 없습니다."
        latest = decisions[0]
        return (
            f"최근 판단은 {latest.get('decision_type')}이며, 근거는 "
            f"‘{latest.get('reason')}’입니다. 장치 실행 여부는 명령 상태에서 별도로 확인해야 합니다."
        )
    if tool_name == "get_experiment_status":
        experiment = result.get("experiment")
        if not experiment:
            return "저장된 실험 run이 없습니다."
        state = "종료" if experiment.get("stopped_at") else "진행 또는 종료시각 대기"
        return f"최근 실험은 Run {experiment.get('run_id')} ({experiment.get('plan_name')})이고 상태는 {state}입니다."
    if tool_name == "get_model_status":
        state = "실측 교정" if result.get("calibrated") else "가정값"
        return f"현재 열모델은 {state}이며 제어 사용 범위는 {result.get('control_use')}입니다."
    if tool_name == "simulate_mpc":
        return (
            f"[SIM] MPC 권장 동작은 {result.get('optimal_action')}이고, 현재 PMV는 "
            f"{result.get('current_pmv'):+.2f}입니다. 이 계산은 장치 명령을 만들지 않았습니다."
        )
    if tool_name == "propose_control_action":
        command = result.get("command", {})
        return (
            f"{command.get('command_type')} 제안 카드를 만들었습니다. 아직 실행하지 않았으며, "
            "로그인한 운영자의 명시적 승인이 필요합니다."
        )
    return "도구 실행이 완료됐습니다."


@router.post("/copilot/chat")
def copilot_chat(
    body: CopilotChatRequest,
    current_user_id: int = Depends(get_current_user_id),
):
    """자연어 요청을 허용 도구로 계획·실행한다. 제어는 제안까지만 한다."""
    require_room_owner(body.room_id, current_user_id)
    plan = ai.plan_copilot_tool(body.message, copilot_tools.TOOL_DEFINITIONS)
    planner = "gemini" if plan is not None else "deterministic_fallback"
    if plan is None or plan.tool_name not in copilot_tools.TOOL_NAMES:
        tool_name, arguments = _fallback_copilot_plan(body.message)
        planner = "deterministic_fallback"
    else:
        tool_name, arguments = plan.tool_name, dict(plan.arguments or {})

    # 인자 없는 MPC 요청은 최신 센서값을 먼저 조회해 두 도구를 연결한다.
    tools_used: list[str] = []
    if tool_name == "simulate_mpc" and not {
        "temperature_c", "humidity_pct", "p_occupied"
    }.issubset(arguments):
        snapshot = _run_database_copilot_tool("get_live_snapshot", body.room_id, {})
        tools_used.append("get_live_snapshot")
        env = snapshot.get("environment") or {}
        occ = snapshot.get("occupancy") or {}
        if env.get("temperature") is None or env.get("humidity") is None:
            raise HTTPException(status_code=409, detail="MPC 시뮬레이션에 필요한 센서값이 없습니다")
        arguments.update({
            "temperature_c": float(env["temperature"]),
            "humidity_pct": float(env["humidity"]),
            "p_occupied": float(occ.get("probability") or 0.0),
        })

    try:
        result = _execute_copilot_tool(tool_name, body.room_id, arguments)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    tools_used.append(tool_name)
    return {
        "message": _copilot_summary(tool_name, result),
        "planner": planner,
        "tools_used": tools_used,
        "result": result,
        "action_proposal": result if tool_name == "propose_control_action" else None,
    }


def _run_database_copilot_tool(
    tool_name: str, room_id: int, arguments: dict,
) -> dict:
    with get_conn() as conn, conn.cursor() as cur:
        if tool_name == "get_live_snapshot":
            cur.execute(
                "SELECT name, control_mode, target_temp FROM rooms WHERE room_id=%s",
                (room_id,),
            )
            room = cur.fetchone()
            cur.execute(
                "SELECT e.temperature, e.humidity, e.co2, e.measured_at"
                " FROM sensor_env e JOIN devices d USING (device_id)"
                " WHERE d.room_id=%s ORDER BY e.measured_at DESC LIMIT 1",
                (room_id,),
            )
            env = cur.fetchone()
            cur.execute(
                "SELECT p.power_w, p.flag, p.measured_at"
                " FROM power_readings p JOIN devices d USING (device_id)"
                " WHERE d.room_id=%s ORDER BY p.measured_at DESC LIMIT 1",
                (room_id,),
            )
            power = cur.fetchone()
            cur.execute(
                "SELECT occupancy_state, probability, estimated_at"
                " FROM occupancy_estimates WHERE room_id=%s"
                " ORDER BY estimated_at DESC LIMIT 1",
                (room_id,),
            )
            occupancy = cur.fetchone()
            cur.execute(
                "SELECT s.door_state, s.measured_at FROM sensor_door s"
                " JOIN devices d USING (device_id) WHERE d.room_id=%s"
                " ORDER BY s.measured_at DESC LIMIT 1",
                (room_id,),
            )
            door = cur.fetchone()
            cur.execute(
                "SELECT p.motion, p.measured_at FROM sensor_pir p"
                " JOIN devices d USING (device_id) WHERE d.room_id=%s"
                " ORDER BY p.measured_at DESC LIMIT 1",
                (room_id,),
            )
            pir = cur.fetchone()
            cur.execute(
                "SELECT command_type, command_status, issued_at, verified_at"
                " FROM hvac_commands WHERE room_id=%s"
                " ORDER BY issued_at DESC LIMIT 1",
                (room_id,),
            )
            command = cur.fetchone()
            return {
                "scope": "MEASURED_LATEST",
                "room": dict(room) if room else None,
                "environment": dict(env) if env else None,
                "power": dict(power) if power else None,
                "occupancy": dict(occupancy) if occupancy else None,
                "door": dict(door) if door else None,
                "pir": dict(pir) if pir else None,
                "last_command": dict(command) if command else None,
            }

        if tool_name == "get_recent_decisions":
            limit = max(1, min(20, int(arguments.get("limit", 5))))
            cur.execute(
                "SELECT decision_id, control_mode, decision_type, target_temp,"
                " reason, decided_at FROM control_decisions WHERE room_id=%s"
                " ORDER BY decided_at DESC LIMIT %s",
                (room_id, limit),
            )
            return {"scope": "MEASURED_HISTORY", "decisions": [dict(row) for row in cur.fetchall()]}

        if tool_name == "get_experiment_status":
            cur.execute(
                "SELECT run_id, plan_name, plan, started_at, ends_at, stopped_at, note"
                " FROM experiment_runs WHERE room_id=%s"
                " ORDER BY started_at DESC LIMIT 1",
                (room_id,),
            )
            row = cur.fetchone()
            return {"scope": "EXPERIMENT_METADATA", "experiment": dict(row) if row else None}

    raise ValueError("tool is not implemented")


def _require_ai():
    if not ai.is_available():
        raise HTTPException(
            status_code=503,
            detail="AI 기능이 설정되지 않았습니다 (GEMINI_API_KEY 필요)",
        )


@router.get("/status")
def ai_status():
    """GET /ai/status - Response: {"available": bool, "model": str}

    프론트가 AI 버튼을 보여줄지 결정하는 데 쓴다.
    """
    return {"available": ai.is_available(), "model": ai.MODEL}


@router.post("/decisions/{decision_id}/explain")
def explain_decision(decision_id: int,
                     current_user_id: int = Depends(get_current_user_id)):
    """POST /ai/decisions/{decision_id}/explain

    Response: {"headline": str, "detail": str, "recommendation": str | null}
    """
    _require_ai()
    require_owned_resource(
        "control_decisions", "decision_id", decision_id, current_user_id
    )
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT d.decision_id, d.control_mode, d.decision_type, d.target_temp,"
            "       d.reason, d.decided_at, d.room_id,"
            "       o.occupancy_state"
            "  FROM control_decisions d"
            "  LEFT JOIN occupancy_estimates o ON o.estimate_id = d.estimate_id"
            " WHERE d.decision_id = %s",
            (decision_id,),
        )
        decision = cur.fetchone()
        if decision is None:
            raise HTTPException(status_code=404, detail="decision not found")

        cur.execute(
            "SELECT name, target_temp FROM rooms WHERE room_id = %s",
            (decision["room_id"],),
        )
        room = cur.fetchone() or {}

        # 판단 시점에 가장 가까운 환경 측정을 근거로 붙인다.
        cur.execute(
            "SELECT e.temperature, e.humidity, e.co2 FROM sensor_env e"
            "  JOIN devices dv ON dv.device_id = e.device_id"
            " WHERE dv.room_id = %s AND e.measured_at <= %s"
            " ORDER BY e.measured_at DESC LIMIT 1",
            (decision["room_id"], decision["decided_at"]),
        )
        env = cur.fetchone() or {}

    payload = dict(decision)
    payload["temperature"] = env.get("temperature")
    payload["co2"] = env.get("co2")

    result = ai.explain_decision(payload, room)
    if result is None:
        raise HTTPException(status_code=502, detail="AI 응답을 받지 못했습니다")
    return result.model_dump()


@router.post("/events/{event_id}/diagnose")
def diagnose_event(event_id: int,
                   current_user_id: int = Depends(get_current_user_id)):
    """POST /ai/events/{event_id}/diagnose

    Response: {"failure_reason": str, "cause_guess": str, "checklist": [str]}
    """
    _require_ai()
    require_owned_resource("event_logs", "event_id", event_id, current_user_id)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT event_id, room_id, device_id, event_category, event_severity,"
            "       status, message, occurred_at"
            "  FROM event_logs WHERE event_id = %s",
            (event_id,),
        )
        event = cur.fetchone()
        if event is None:
            raise HTTPException(status_code=404, detail="event not found")

        room_id = event["room_id"]
        cur.execute(
            "SELECT e.temperature, e.humidity, e.co2, e.measured_at FROM sensor_env e"
            "  JOIN devices dv ON dv.device_id = e.device_id"
            " WHERE dv.room_id = %s ORDER BY e.measured_at DESC LIMIT 1",
            (room_id,),
        )
        env = cur.fetchone() or {}

        cur.execute(
            "SELECT device_code, device_type, comm_status, last_seen_at"
            "  FROM devices WHERE room_id = %s ORDER BY device_code",
            (room_id,),
        )
        devices = cur.fetchall()

        cur.execute(
            "SELECT decision_type, reason, decided_at FROM control_decisions"
            " WHERE room_id = %s ORDER BY decided_at DESC LIMIT 1",
            (room_id,),
        )
        recent = cur.fetchone()

    last_seen = env.get("measured_at")
    context = {
        "temperature": env.get("temperature"),
        "humidity": env.get("humidity"),
        "co2": env.get("co2"),
        # 5분 넘게 새 측정이 없으면 센서가 끊긴 것으로 본다.
        "sensor_connected": bool(
            last_seen and datetime.now(timezone.utc) - last_seen < timedelta(minutes=5)
        ),
        "last_updated": last_seen,
        "recent_decision": recent,
        "devices": [
            f"{d['device_code']}({d['device_type']}, {d['comm_status']})" for d in devices
        ],
    }

    result = ai.diagnose_alert(dict(event), context)
    if result is None:
        raise HTTPException(status_code=502, detail="AI 응답을 받지 못했습니다")
    return result.model_dump()


@router.get("/rooms/{room_id}/stats")
def room_stats(room_id: int, start: date | None = None, end: date | None = None,
               current_user_id: int = Depends(get_current_user_id)):
    """GET /ai/rooms/{room_id}/stats?start=&end=

    기간 집계. AI 없이도 그대로 쓸 수 있는 순수 수치다.
    전력 실측 장비가 없으므로 에너지 항목은 만들어 내지 않는다.
    """
    require_room_owner(room_id, current_user_id)
    return _collect_stats(room_id, start, end)


@router.post("/rooms/{room_id}/report")
def weekly_report(room_id: int, start: date | None = None, end: date | None = None,
                  current_user_id: int = Depends(get_current_user_id)):
    """POST /ai/rooms/{room_id}/report?start=&end=

    Response: {"summary": str, "highlights": [str], "concerns": [str],
               "recommendations": [str], "stats": {...}}
    """
    _require_ai()
    require_room_owner(room_id, current_user_id)
    stats = _collect_stats(room_id, start, end)
    result = ai.weekly_report(stats)
    if result is None:
        raise HTTPException(status_code=502, detail="AI 응답을 받지 못했습니다")
    return {**result.model_dump(), "stats": stats}


def _collect_stats(room_id: int, start: date | None, end: date | None) -> dict:
    """기간 KPI 를 모은다. 없는 값은 None 으로 두고 추정하지 않는다."""
    end = end or datetime.now(timezone.utc).date()
    start = start or (end - timedelta(days=7))

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT name, target_temp FROM rooms WHERE room_id = %s", (room_id,))
        room = cur.fetchone()
        if room is None:
            raise HTTPException(status_code=404, detail="room not found")
        target = float(room["target_temp"])

        cur.execute(
            "SELECT count(*) AS n,"
            "       avg(e.temperature) AS t_avg, min(e.temperature) AS t_min,"
            "       max(e.temperature) AS t_max,"
            "       avg(e.co2) AS c_avg, max(e.co2) AS c_max,"
            "       count(*) FILTER (WHERE abs(e.temperature - %s) > 2) AS t_out,"
            "       count(*) FILTER (WHERE e.co2 > 1000) AS c_high,"
            "       count(*) FILTER (WHERE e.temp_flag <> 'ok'"
            "                          OR e.humidity_flag <> 'ok'"
            "                          OR e.co2_flag <> 'ok') AS bad"
            "  FROM sensor_env e JOIN devices dv ON dv.device_id = e.device_id"
            " WHERE dv.room_id = %s AND e.measured_at::date BETWEEN %s AND %s",
            (target, room_id, start, end),
        )
        env = cur.fetchone()

        cur.execute(
            "SELECT count(*) AS n,"
            "       count(*) FILTER (WHERE occupancy_state = 'occupied') AS occupied"
            "  FROM occupancy_estimates"
            " WHERE room_id = %s AND estimated_at::date BETWEEN %s AND %s",
            (room_id, start, end),
        )
        occ = cur.fetchone()

        cur.execute(
            "SELECT count(*) AS n, control_mode FROM control_decisions"
            " WHERE room_id = %s AND decided_at::date BETWEEN %s AND %s"
            " GROUP BY control_mode",
            (room_id, start, end),
        )
        modes = {r["control_mode"]: r["n"] for r in cur.fetchall()}

        cur.execute(
            "SELECT command_status, count(*) AS n FROM hvac_commands"
            " WHERE room_id = %s AND issued_at::date BETWEEN %s AND %s"
            " GROUP BY command_status",
            (room_id, start, end),
        )
        commands = {r["command_status"]: r["n"] for r in cur.fetchall()}

        cur.execute(
            "SELECT event_category, count(*) AS n FROM event_logs"
            " WHERE room_id = %s AND occurred_at::date BETWEEN %s AND %s"
            " GROUP BY event_category",
            (room_id, start, end),
        )
        events = {r["event_category"]: r["n"] for r in cur.fetchall()}

        # 전력 측정 장비가 실제로 붙어 있는지. 없으면 에너지 KPI 를 만들지 않는다.
        cur.execute(
            "SELECT count(*) AS n FROM devices WHERE room_id = %s AND device_type = 'plug'",
            (room_id,),
        )
        has_plug = cur.fetchone()["n"] > 0

    total = env["n"] or 0

    def pct(part) -> float | None:
        return round(100.0 * (part or 0) / total, 1) if total else None

    return {
        "room_name": room["name"],
        "target_temp": target,
        "start": str(start),
        "end": str(end),
        "temp_avg": _round(env["t_avg"]),
        "temp_min": _round(env["t_min"]),
        "temp_max": _round(env["t_max"]),
        "temp_out_of_range_pct": pct(env["t_out"]),
        "co2_avg": _round(env["c_avg"], 0),
        "co2_max": _round(env["c_max"], 0),
        "co2_high_pct": pct(env["c_high"]),
        "occupied_pct": (
            round(100.0 * occ["occupied"] / occ["n"], 1) if occ["n"] else None
        ),
        "occupancy_samples": occ["n"],
        "decision_count": sum(modes.values()),
        "control_modes": modes,
        "command_sent": commands.get("sent", 0) + commands.get("acked", 0),
        "command_failed": commands.get("failed", 0) + commands.get("timeout", 0),
        "reading_count": total,
        "invalid_pct": pct(env["bad"]),
        "alert_counts": events,
        # 스마트 플러그가 없으면 소비 전력을 알 수 없다. 0 이나 추정치를
        # 넣으면 리포트가 절감률을 지어내게 된다.
        "power_measured": has_plug,
        "energy_kwh": None,
    }


def _round(value, digits: int = 2):
    return None if value is None else round(float(value), digits)
