"""Claude 를 이용한 해설·진단·리포트.

게이트웨이가 남기는 것은 기계용 코드다(decision_type='off',
reason='EMPTY_CONFIRMED | temp=24.53C ...'). 공간 관리자와 심사위원이
읽으려면 사람 말이 필요하다. 그 변환만 담당한다.

API 키가 없으면 503 을 준다. 프론트는 이 상태에서도 원래 화면을 그대로
보여줘야 한다 — AI 는 부가 기능이지 전제가 아니다.
"""

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from api.db import get_conn
from api.services import ai

router = APIRouter(prefix="/ai", tags=["ai"])


def _require_ai():
    if not ai.is_available():
        raise HTTPException(
            status_code=503,
            detail="AI 기능이 설정되지 않았습니다 (ANTHROPIC_API_KEY 필요)",
        )


@router.get("/status")
def ai_status():
    """GET /ai/status - Response: {"available": bool, "model": str}

    프론트가 AI 버튼을 보여줄지 결정하는 데 쓴다.
    """
    return {"available": ai.is_available(), "model": ai.MODEL}


@router.post("/decisions/{decision_id}/explain")
def explain_decision(decision_id: int):
    """POST /ai/decisions/{decision_id}/explain

    Response: {"headline": str, "detail": str, "recommendation": str | null}
    """
    _require_ai()
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
def diagnose_event(event_id: int):
    """POST /ai/events/{event_id}/diagnose

    Response: {"failure_reason": str, "cause_guess": str, "checklist": [str]}
    """
    _require_ai()
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
def room_stats(room_id: int, start: date | None = None, end: date | None = None):
    """GET /ai/rooms/{room_id}/stats?start=&end=

    기간 집계. AI 없이도 그대로 쓸 수 있는 순수 수치다.
    전력 실측 장비가 없으므로 에너지 항목은 만들어 내지 않는다.
    """
    return _collect_stats(room_id, start, end)


@router.post("/rooms/{room_id}/report")
def weekly_report(room_id: int, start: date | None = None, end: date | None = None):
    """POST /ai/rooms/{room_id}/report?start=&end=

    Response: {"summary": str, "highlights": [str], "concerns": [str],
               "recommendations": [str], "stats": {...}}
    """
    _require_ai()
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
