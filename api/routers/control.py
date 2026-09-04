from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from psycopg.types.json import Json

from api.db import get_conn
from api.security import get_current_user_id, require_owned_resource, require_room_owner

router = APIRouter(tags=["control"])

_COLUMNS = (
    "command_id, room_id, device_id, decision_id, schedule_id, issued_by, "
    "command_type, control_mode, target_temp, command_status, issued_at, "
    "power_before_w, power_after_w, verify_result, result_message, "
    "estimated_cause, action_guide, verified_at"
)

_DECISION_COLUMNS = (
    "decision_id, room_id, estimate_id, schedule_id, control_mode, "
    "decision_type, target_temp, reason, decided_at"
)


@router.get("/rooms/{room_id}/commands")
def list_commands(room_id: int, day: date | None = None,
                  current_user_id: int = Depends(get_current_user_id)):
    """GET /rooms/{room_id}/commands?day=2026-08-19

    Response: list of HVAC command/control-log entries for the room, newest
    last (issued_at ASC). If `day` is omitted, returns every command for the
    room.
    [
      {
        "command_id": int, "room_id": int, "device_id": int,
        "decision_id": int | null, "schedule_id": int | null,
        "issued_by": int | null,
        "command_type": "power_on" | "power_off" | "set_temp" | "set_mode" | "set_fan",
        "control_mode": "monitoring" | "manual" | "rule" | "mpc",
        "target_temp": float | null,
        "command_status": "pending" | "sent" | "acked" | "failed" | "timeout",
        "issued_at": str,
        "power_before_w": float | null, "power_after_w": float | null,
        "verify_result": "success" | "failed" | "uncertain" | null,
        "result_message": str | null, "estimated_cause": str | null,
        "action_guide": str | null, "verified_at": str | null
      },
      ...
    ]
    """
    require_room_owner(room_id, current_user_id)
    with get_conn() as conn, conn.cursor() as cur:
        if day is None:
            cur.execute(
                f"SELECT {_COLUMNS} FROM hvac_commands WHERE room_id = %s ORDER BY issued_at",
                (room_id,),
            )
        else:
            cur.execute(
                f"""
                SELECT {_COLUMNS} FROM hvac_commands
                WHERE room_id = %s AND issued_at::date = %s
                ORDER BY issued_at
                """,
                (room_id, day),
            )
        return cur.fetchall()


@router.get("/commands/{command_id}")
def get_command(command_id: int,
                current_user_id: int = Depends(get_current_user_id)):
    """GET /commands/{command_id} - Response: same shape as one list_commands() entry."""
    require_owned_resource("hvac_commands", "command_id", command_id, current_user_id)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM hvac_commands WHERE command_id = %s", (command_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="command not found")
    return row


class IssueCommandRequest(BaseModel):
    """수동 제어 명령. 게이트웨이가 큐에서 집어가 실제로 실행한다."""

    command_type: str = Field(pattern="^(power_on|power_off|set_temp|set_mode|set_fan)$")
    target_temp: float | None = Field(default=None, ge=16, le=30)
    control_mode: Literal["manual"] = "manual"
    issued_by: int | None = None
    payload: dict | None = None


@router.post("/rooms/{room_id}/commands", status_code=201)
def issue_command(room_id: int, body: IssueCommandRequest,
                  current_user_id: int = Depends(get_current_user_id)):
    """POST /rooms/{room_id}/commands

    명령을 'pending' 으로 큐에 넣기만 한다. API 는 액추에이터를 직접
    건드리지 않는다 — 게이트웨이가 이 큐를 폴링해 MQTT 로 내보내고
    command_status 를 갱신한다. 제어 주체를 하나로 묶어 두지 않으면
    API 와 게이트웨이가 동시에 상반된 명령을 낼 수 있다.

    Response: {"command_id": int, "command_status": "pending", "issued_at": str}
    """
    require_room_owner(room_id, current_user_id)
    with get_conn() as conn, conn.cursor() as cur:
        proposal_id = str((body.payload or {}).get("proposal_id") or "").strip()
        if proposal_id:
            # Streamlit 재실행이나 네트워크 재시도로 같은 승인 요청이 두 번
            # 도착해도 실제 장치 명령은 하나만 만든다.
            cur.execute(
                f"SELECT {_COLUMNS} FROM hvac_commands"
                " WHERE room_id=%s AND payload->>'proposal_id'=%s"
                " ORDER BY issued_at DESC LIMIT 1",
                (room_id, proposal_id),
            )
            existing = cur.fetchone()
            if existing:
                return existing

        cur.execute(
            "SELECT control_mode FROM rooms WHERE room_id=%s",
            (room_id,),
        )
        room = cur.fetchone()
        if body.command_type != "power_off" and (
            not room or room["control_mode"] not in {"manual", "rule", "mpc"}
        ):
            raise HTTPException(
                status_code=409,
                detail="모니터링 모드에서는 장치를 켤 수 없습니다. 제어 모드를 먼저 변경해 주세요.",
            )

        cur.execute(
            "SELECT command_id FROM hvac_commands WHERE room_id=%s"
            " AND command_status IN ('pending','sent') ORDER BY issued_at LIMIT 1",
            (room_id,),
        )
        outstanding = cur.fetchone()
        if outstanding and body.command_type != "power_off":
            raise HTTPException(
                status_code=409,
                detail=f"명령 #{outstanding['command_id']}의 장치 확인이 끝날 때까지 기다려 주세요.",
            )
        if outstanding and body.command_type == "power_off":
            # OFF는 안전 동작이므로 오래된 ON/온도 명령 뒤에서 기다리게 하지
            # 않는다. 기존 미완료 작업을 명시적으로 종결하고 OFF를 새로 큐잉한다.
            cur.execute(
                "UPDATE hvac_commands SET command_status='failed',"
                " verify_result='failed', verified_at=now(),"
                " result_message='superseded_by_power_off'"
                " WHERE room_id=%s AND command_status IN ('pending','sent')",
                (room_id,),
            )

        # 이 공간의 IR 송신기를 찾는다. 냉방 명령이 나갈 통로다.
        cur.execute(
            "SELECT device_id, comm_status, last_seen_at FROM devices"
            " WHERE room_id = %s AND device_type = 'ir' AND is_enabled"
            " ORDER BY device_id LIMIT 1",
            (room_id,),
        )
        device = cur.fetchone()
        if device is None:
            raise HTTPException(
                status_code=409,
                detail="이 공간에 사용 가능한 IR 송신기가 없습니다",
            )
        if body.command_type != "power_off":
            cur.execute(
                "SELECT MAX(e.measured_at) AS measured_at FROM sensor_env e"
                " JOIN devices d USING (device_id) WHERE d.room_id=%s",
                (room_id,),
            )
            latest_env = cur.fetchone()
            if not latest_env or latest_env["measured_at"] is None:
                raise HTTPException(
                    status_code=409, detail="환경 센서값이 없어 장치를 켤 수 없습니다"
                )
            cur.execute(
                "SELECT EXTRACT(EPOCH FROM (now() - %s)) AS age_sec",
                (latest_env["measured_at"],),
            )
            if float(cur.fetchone()["age_sec"]) > 120:
                raise HTTPException(
                    status_code=409, detail="환경 센서값이 120초 이상 오래되어 장치를 켤 수 없습니다"
                )
            if device["comm_status"] != "normal":
                raise HTTPException(
                    status_code=409, detail="제어 장치가 정상 연결 상태가 아닙니다"
                )
            cur.execute(
                "SELECT EXTRACT(EPOCH FROM (now() - %s)) AS age_sec",
                (device["last_seen_at"],),
            )
            if device["last_seen_at"] is None or float(cur.fetchone()["age_sec"]) > 120:
                raise HTTPException(
                    status_code=409, detail="제어 장치 상태가 120초 이상 수신되지 않았습니다"
                )

        # set_temp 인데 목표 온도가 없으면 게이트웨이가 무엇을 쏴야 할지
        # 알 수 없다. 큐에 넣기 전에 막는다.
        if body.command_type == "set_temp" and body.target_temp is None:
            raise HTTPException(
                status_code=422, detail="set_temp 에는 target_temp 가 필요합니다"
            )

        cur.execute(
            "INSERT INTO hvac_commands"
            " (room_id, device_id, issued_by, command_type, control_mode,"
            "  target_temp, command_status, payload)"
            " VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s)"
            " RETURNING command_id, command_status, issued_at",
            (room_id, device["device_id"], current_user_id, body.command_type,
             "manual", body.target_temp, Json(body.payload or {})),
        )
        return cur.fetchone()


@router.get("/rooms/{room_id}/decisions/latest")
def get_latest_decision(room_id: int,
                        current_user_id: int = Depends(get_current_user_id)):
    """GET /rooms/{room_id}/decisions/latest

    이 공간에서 게이트웨이가 가장 최근에 내린 제어 판단 한 건. AI 해설
    (`/ai/decisions/{id}/explain`)에 넘길 decision_id 를 얻는 데 쓴다.

    Response: same columns as control_decisions, or 404 if this room has
    no recorded decision yet.
    """
    require_room_owner(room_id, current_user_id)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {_DECISION_COLUMNS} FROM control_decisions"
            " WHERE room_id = %s ORDER BY decided_at DESC LIMIT 1",
            (room_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="no control decision recorded for this room yet")
    return row
