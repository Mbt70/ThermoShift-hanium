"""게이트웨이의 PostgreSQL 저장 계층.

api/db.py 와 같은 데이터베이스를 본다. 스키마는 db/001~003 이 단일 원본이고
게이트웨이는 CREATE TABLE 을 들고 있지 않는다. 게이트웨이만 쓰는 테이블
(ir_events)은 db/004_gateway.sql 에 따로 있다.

MQTT 콜백 스레드에서 호출되므로 커넥션 풀을 쓴다. 요청마다 새로 접속하면
핸드셰이크 비용이 그대로 지연이 된다.
"""

import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import get_config

# /etc/thermoshift.env or local .env
load_dotenv("/etc/thermoshift.env")
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_USER = os.getenv("DB_USER", "thermoshift")
DB_PASSWORD = os.getenv("DB_PASSWORD", "mxJEssQM8i6HutY5jbkzAYIO")
DB_NAME = os.getenv("DB_NAME", "thermoshift")

_CONNINFO = psycopg.conninfo.make_conninfo(
    host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, dbname=DB_NAME
)

# 미배정 노드를 담아 두는 공간의 이름. devices.room_id 가 NOT NULL 이라
# 배정 전 노드도 어딘가에는 속해야 한다. 사용자가 프론트에서 실제 공간으로
# 옮기기 전까지 여기에 머문다.
UNASSIGNED_ROOM_NAME = "미배정"

# 게이트웨이가 다루는 metric 이름 → sensor_env 컬럼
_ENV_COLUMNS = {"temperature": "temperature", "humidity": "humidity", "co2": "co2"}

# 우리 액션 이름 → main 의 decision_type ENUM
_DECISION_TYPES = {
    "POWER_OFF": "off",
    "COOL_24_AUTO": "maintain",
    "COOL_25_AUTO": "maintain",
    "COOL_26_AUTO": "maintain",
}

# 우리 액션 이름 → main 의 command_type ENUM
_COMMAND_TYPES = {"POWER_OFF": "power_off"}

# 게이트웨이 control_mode → main 의 control_mode ENUM
# 게이트웨이 동작 모드 → main 스키마의 control_mode ENUM.
#
# 호출부가 이미 ENUM 값(monitoring/manual/rule/mpc)을 넘기는 경우도 있다.
# 컨트롤러는 "이 판단이 어떤 운전 방식에서 나왔는가" 를 공간 모드로 기록하기
# 때문이다. 그때는 그대로 통과시켜야 한다 — 예전에는 이 표에 없다는 이유로
# 전부 monitoring 으로 떨어져, rule 구간이 기록에서 사라졌다.
_DB_CONTROL_MODES = {"monitoring", "manual", "rule", "mpc"}

_CONTROL_MODES = {
    "shadow": "monitoring",
    "active": "rule",
    "manual_lockout": "manual",
    "failsafe": "monitoring",
}


def _control_mode_of(value: str) -> str:
    if value in _DB_CONTROL_MODES:
        return value
    return _CONTROL_MODES.get(value, "monitoring")


def normalize_uid(device_code: str) -> str:
    """device_uid 는 CHECK 제약상 대문자·숫자만 허용한다 (env_01 → ENV01)."""
    return re.sub(r"[^A-Z0-9]", "", device_code.upper())


def _target_temp_of(action: str) -> Optional[float]:
    """COOL_25_AUTO 같은 액션 이름에서 목표 온도를 뽑는다."""
    match = re.search(r"_(\d{2})_", action)
    return float(match.group(1)) if match else None


class Storage:
    def __init__(self, conninfo: str = None):
        self._pool = ConnectionPool(
            conninfo or _CONNINFO,
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row},
            open=True,
        )
        # device_code → device_id 는 바뀌지 않으므로 캐시한다. 센서 1건마다
        # 조회하면 5초 주기 × 노드 수만큼 불필요한 왕복이 생긴다.
        self._device_ids: dict[str, int] = {}
        self._lock = threading.Lock()

    def close(self) -> None:
        self._pool.close()

    # ------------------------------------------------------------------
    # 공간 · 디바이스
    # ------------------------------------------------------------------

    def resolve_room_id(self) -> Optional[int]:
        """이 게이트웨이가 담당하는 공간 ID.

        config 에 명시돼 있으면 그것을 쓰고, 없으면 실제 센서가 배정된
        공간을 따른다. '미배정' 공간은 후보에서 제외한다 — 거기 있는
        노드는 아직 사용자가 배치하지 않은 것이라 제어 대상이 아니다.
        """
        configured = get_config().app.room_id
        if configured:
            return int(configured)
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT d.room_id FROM devices d JOIN rooms r ON r.room_id = d.room_id"
                " WHERE r.name <> %s"
                " ORDER BY (d.device_type = 'env') DESC, d.device_id LIMIT 1",
                (UNASSIGNED_ROOM_NAME,),
            )
            row = cur.fetchone()
        return row["room_id"] if row else None

    def _unassigned_room_id(self, conn) -> int:
        """미배정 공간을 필요할 때 만들어 두고 그 ID를 준다."""
        with conn.cursor() as cur:
            cur.execute("SELECT room_id FROM rooms WHERE name = %s", (UNASSIGNED_ROOM_NAME,))
            row = cur.fetchone()
            if row:
                return row["room_id"]
            # rooms.owner_user_id 가 NOT NULL 이라 소유자가 필요하다.
            # 가장 먼저 가입한 계정을 쓴다.
            cur.execute(
                "SELECT user_id FROM users WHERE deleted_at IS NULL ORDER BY user_id LIMIT 1"
            )
            owner = cur.fetchone()
            if owner is None:
                raise RuntimeError(
                    "사용자가 한 명도 없어 미배정 공간을 만들 수 없습니다. "
                    "먼저 계정을 만드세요 (db/seed.sql 또는 회원가입)."
                )
            cur.execute(
                "INSERT INTO rooms (owner_user_id, name, location) VALUES (%s, %s, %s)"
                " RETURNING room_id",
                (owner["user_id"], UNASSIGNED_ROOM_NAME, "게이트웨이가 자동 등록"),
            )
            return cur.fetchone()["room_id"]

    def register_device(self, device_code: str, device_type: str, timestamp: str) -> int:
        """처음 보는 노드를 미배정 공간에 등록하고 last_seen_at 을 갱신한다.

        사용자가 프론트에서 실제 공간으로 옮기면 room_id 가 바뀌지만
        device_uid 는 그대로라 캐시가 계속 유효하다.
        """
        cached = self._device_ids.get(device_code)
        if cached is not None:
            with self._pool.connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE devices SET last_seen_at = %s, comm_status = 'normal'"
                    " WHERE device_id = %s",
                    (timestamp, cached),
                )
            return cached

        uid = normalize_uid(device_code)
        with self._lock, self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT device_id FROM devices WHERE device_uid = %s", (uid,))
                row = cur.fetchone()
                if row is None:
                    room_id = self._unassigned_room_id(conn)
                    cur.execute(
                        "INSERT INTO devices"
                        " (room_id, device_code, device_uid, device_type, last_seen_at)"
                        " VALUES (%s, %s, %s, %s, %s)"
                        " ON CONFLICT (device_uid) DO UPDATE SET last_seen_at = EXCLUDED.last_seen_at"
                        " RETURNING device_id",
                        (room_id, device_code, uid, device_type, timestamp),
                    )
                    row = cur.fetchone()
                else:
                    cur.execute(
                        "UPDATE devices SET last_seen_at = %s, comm_status = 'normal'"
                        " WHERE device_id = %s",
                        (timestamp, row["device_id"]),
                    )
            device_id = row["device_id"]
            self._device_ids[device_code] = device_id
            return device_id

    def _device_id_of(self, device_code: str) -> Optional[int]:
        cached = self._device_ids.get(device_code)
        if cached is not None:
            return cached
        uid = normalize_uid(device_code)
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT device_id FROM devices WHERE device_uid = %s", (uid,))
            row = cur.fetchone()
        if row is None:
            return None
        self._device_ids[device_code] = row["device_id"]
        return row["device_id"]

    # ------------------------------------------------------------------
    # 센서
    # ------------------------------------------------------------------

    def insert_sensor_reading(self, timestamp: str, device_code: str, metric: str,
                              value: float, quality: str, raw_payload: str) -> None:
        """metric 하나를 해당 센서 테이블에 넣는다.

        main 스키마는 온·습도·CO2 를 sensor_env 의 한 행에 함께 담는다.
        게이트웨이는 metric 별로 따로 부르므로, 같은 (device_id, measured_at)
        에 대해 UPSERT 로 컬럼을 채워 나간다.
        """
        device_id = self._device_id_of(device_code)
        if device_id is None:
            return
        flag = "ok" if quality.upper() == "OK" else "error"

        with self._pool.connection() as conn, conn.cursor() as cur:
            if metric in _ENV_COLUMNS:
                column = _ENV_COLUMNS[metric]
                flag_col = "temp_flag" if column == "temperature" else f"{column}_flag"
                cur.execute(
                    f"INSERT INTO sensor_env (device_id, {column}, {flag_col},"
                    " measured_at, received_at) VALUES (%s, %s, %s, %s, now())"
                    " ON CONFLICT (device_id, measured_at) DO UPDATE"
                    f" SET {column} = EXCLUDED.{column}, {flag_col} = EXCLUDED.{flag_col}",
                    (device_id, value, flag, timestamp),
                )
            elif metric == "pir":
                cur.execute(
                    "INSERT INTO sensor_pir (device_id, motion, flag, measured_at, received_at)"
                    " VALUES (%s, %s, %s, %s, now())"
                    " ON CONFLICT (device_id, measured_at) DO NOTHING",
                    (device_id, value > 0, flag, timestamp),
                )
            elif metric == "door":
                cur.execute(
                    "INSERT INTO sensor_door (device_id, door_state, flag, measured_at, received_at)"
                    " VALUES (%s, %s, %s, %s, now())"
                    " ON CONFLICT (device_id, measured_at) DO NOTHING",
                    (device_id, "open" if value > 0 else "closed", flag, timestamp),
                )

    # ------------------------------------------------------------------
    # 재실 추정 · 제어 판단
    # ------------------------------------------------------------------

    def insert_occupancy_estimate(self, timestamp: str, p_empty: float, p_transition: float,
                                  p_occupied: float, state: str, quality: str,
                                  reasons: List[str], room_id: Optional[int] = None) -> Optional[int]:
        """HMM 추정 결과를 남긴다.

        main 스키마는 확률을 하나만 들고 있으므로 채택된 상태의 확률을 쓰고,
        세 상태의 분포는 evidence_summary 에 함께 남겨 근거를 잃지 않는다.
        """
        room_id = room_id if room_id is not None else self.resolve_room_id()
        if room_id is None:
            return None
        probability = {"EMPTY": p_empty, "TRANSITION": p_transition,
                       "OCCUPIED": p_occupied}.get(state.upper(), 0.0)
        evidence = "; ".join(reasons)
        summary = (
            f"p(empty)={p_empty:.3f} p(transition)={p_transition:.3f} "
            f"p(occupied)={p_occupied:.3f} quality={quality}"
        )
        if evidence:
            summary = f"{summary} | {evidence}"

        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO occupancy_estimates"
                " (room_id, occupancy_state, probability, evidence_summary, estimated_at)"
                " VALUES (%s, %s, %s, %s, %s)"
                " ON CONFLICT (room_id, estimated_at) DO NOTHING"
                " RETURNING estimate_id",
                (room_id, state.lower(), round(probability, 3), summary[:500], timestamp),
            )
            row = cur.fetchone()
        return row["estimate_id"] if row else None

    def insert_control_decision(self, timestamp: str, control_mode: str, proposed_action: str,
                                executed: bool, occupancy_state: str,
                                temperature_c: Optional[float], co2_ppm: Optional[float],
                                reason_codes: List[str], room_id: Optional[int] = None,
                                estimate_id: Optional[int] = None,
                                decision_type: Optional[str] = None) -> Optional[int]:
        """제어 판단을 남긴다.

        main 스키마에는 executed·temperature_c·co2_ppm 컬럼이 없다. 실행
        여부는 hvac_commands.command_status 가 들고, 관측값은 sensor_env 에
        이미 있다. 다만 판단 시점의 근거를 한 줄로 읽을 수 있어야 하므로
        reason 텍스트에 함께 적는다.
        """
        room_id = room_id if room_id is not None else self.resolve_room_id()
        if room_id is None:
            return None

        observed = []
        if temperature_c is not None:
            observed.append(f"temp={temperature_c:.2f}C")
        if co2_ppm is not None:
            observed.append(f"co2={co2_ppm:.0f}ppm")
        observed.append(f"occupancy={occupancy_state}")
        observed.append(f"executed={'yes' if executed else 'no'}")
        reason = f"{','.join(reason_codes)} | {' '.join(observed)}"

        # 판단 유형은 정책이 정해 준다(precool/maintain/setback/ventilate/off).
        # 예전에는 액션 이름과 근거 문자열에서 되짚어 추측했는데, 정책이 실제로
        # 무엇을 하려 했는지와 어긋날 수 있었다. 넘어오지 않은 경우에만
        # 예전 방식으로 되짚는다.
        if decision_type is None:
            if any("CO2" in code or "VENT" in code for code in reason_codes):
                decision_type = "ventilate"
            else:
                decision_type = _DECISION_TYPES.get(proposed_action, "maintain")

        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO control_decisions"
                " (room_id, estimate_id, control_mode, decision_type, target_temp, reason, decided_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING decision_id",
                (room_id, estimate_id, _control_mode_of(control_mode),
                 decision_type, _target_temp_of(proposed_action), reason, timestamp),
            )
            return cur.fetchone()["decision_id"]

    # ------------------------------------------------------------------
    # 수동 제어 명령 큐
    # ------------------------------------------------------------------

    def fetch_room_settings(self, room_id: Optional[int]) -> Optional[dict]:
        """공간의 제어 설정을 읽는다. 사용자가 대시보드에서 바꾸는 값들이다.

        게이트웨이는 예전에 config.yaml 의 값만 봤다. 그래서 사용자가 화면에서
        목표 온도나 제어 모드를 바꿔도 아무 일도 일어나지 않았다. 판단 주기마다
        여기서 다시 읽어 화면의 설정이 곧바로 제어에 반영되게 한다.
        """
        if room_id is None:
            return None
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT room_id, name, control_mode, target_temp, temp_tolerance,"
                " co2_limit FROM rooms WHERE room_id = %s",
                (room_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "room_id": row["room_id"],
            "name": row["name"],
            "control_mode": row["control_mode"],
            "target_temp": float(row["target_temp"]),
            "temp_tolerance": float(row["temp_tolerance"]),
            "co2_limit": int(row["co2_limit"]),
        }

    def fetch_active_schedule(self, room_id: Optional[int], now: datetime
                              ) -> Optional[dict]:
        """지금 진행 중이거나 곧 시작할 예약 하나를 가져온다.

        예냉은 "언제 시작하는지" 를 알아야 리드타임을 계산할 수 있다.
        반복 예약은 repeat_days(1=월 … 7=일)에 오늘이 들어 있는지로 판단한다.
        """
        if room_id is None:
            return None
        weekday = now.isoweekday()
        today = now.date()
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT schedule_id, start_time, end_time, target_temp,
                          precooling_min
                   FROM schedules
                   WHERE room_id = %s AND is_active
                     AND valid_from <= %s
                     AND (valid_until IS NULL OR valid_until >= %s)
                     AND (repeat_days = '{}' OR %s = ANY(repeat_days))
                   ORDER BY start_time""",
                (room_id, today, today, weekday),
            )
            rows = cur.fetchall()

        best = None
        for r in rows:
            starts = datetime.combine(today, r["start_time"], tzinfo=now.tzinfo)
            ends = datetime.combine(today, r["end_time"], tzinfo=now.tzinfo)
            if ends < now:
                continue          # 오늘치는 이미 끝났다
            # 진행 중인 것이 있으면 그것이 우선, 없으면 가장 빨리 시작하는 것
            if best is None or starts < best["starts_at"]:
                best = {"schedule_id": r["schedule_id"], "starts_at": starts,
                        "ends_at": ends, "target_temp": float(r["target_temp"]),
                        "precooling_min": r["precooling_min"]}
        return best

    def fetch_pending_commands(self, room_id: Optional[int]) -> List[dict]:
        """프론트에서 들어온 수동 제어 명령 큐를 가져온다."""
        if room_id is None:
            return []
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT command_id, command_type, control_mode, target_temp, payload"
                " FROM hvac_commands WHERE room_id = %s AND command_status = 'pending'"
                " ORDER BY issued_at",
                (room_id,),
            )
            rows = cur.fetchall()
        return [
            {
                "id": r["command_id"],
                "action": self._action_of(r["command_type"], r["target_temp"]),
                "method": r["control_mode"],
                "payload_json": json.dumps(r["payload"] or {}),
            }
            for r in rows
        ]

    @staticmethod
    def _action_of(command_type: str, target_temp) -> str:
        """DB 의 command_type 을 게이트웨이가 아는 액션 이름으로 되돌린다."""
        if command_type == "power_off":
            return "POWER_OFF"
        if target_temp is not None:
            return f"COOL_{int(target_temp)}_AUTO"
        return "POWER_ON"

    def mark_command(self, command_id: int, status: str, error_code: Optional[str],
                     resolved_at: str) -> None:
        """명령 처리 결과를 기록한다.

        main 은 성공을 'acked' 로 표현하고, ck_cmd_acked 제약이
        verify_result='success' 를 함께 요구한다. 전력 검증 장비가 아직
        없으므로 실제 확인 없이 acked 로 올리지 않고 'sent' 까지만 쓴다.
        """
        verify_result = None if status != "failed" else "failed"
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE hvac_commands SET command_status = %s, result_message = %s,"
                " verify_result = %s, verified_at = %s WHERE command_id = %s",
                (status, error_code, verify_result,
                 resolved_at if verify_result else None, command_id),
            )

    # ------------------------------------------------------------------
    # 이벤트
    # ------------------------------------------------------------------

    def insert_ir_event(self, timestamp: str, direction: str, protocol: str, code_hash: str,
                        source: str, raw_payload: str, room_id: Optional[int] = None) -> None:
        room_id = room_id if room_id is not None else self.resolve_room_id()
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ir_events"
                " (room_id, direction, protocol, code_hash, source, raw_payload, occurred_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (room_id, direction, protocol, code_hash, source, raw_payload, timestamp),
            )

    def insert_system_event(self, timestamp: str, severity: str, event_type: str,
                            message: str, room_id: Optional[int] = None) -> None:
        room_id = room_id if room_id is not None else self.resolve_room_id()
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO event_logs"
                " (room_id, event_category, event_severity, message, occurred_at)"
                " VALUES (%s, %s, %s, %s, %s)",
                (room_id, _event_category(event_type), _event_severity(severity),
                 message[:500], timestamp),
            )


def _event_category(event_type: str) -> str:
    """게이트웨이의 자유형 event_type 을 main 의 event_category ENUM 으로."""
    key = event_type.lower()
    if "sensor" in key or "stale" in key:
        return "sensor_error"
    if "co2" in key:
        return "co2_exceed"
    if "temp" in key:
        return "temp_deviation"
    if "control" in key or "command" in key:
        return "control_fail"
    if "mqtt" in key or "network" in key or "wifi" in key:
        return "network"
    if "schedule" in key:
        return "schedule"
    if "power" in key or "energy" in key:
        return "energy"
    return "system"


def _event_severity(severity: str) -> str:
    key = severity.lower()
    if key in ("critical", "fatal", "error"):
        return "critical"
    if key in ("warning", "warn"):
        return "warning"
    return "info"


_storage_instance = None


def get_storage() -> Storage:
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = Storage()
    return _storage_instance
