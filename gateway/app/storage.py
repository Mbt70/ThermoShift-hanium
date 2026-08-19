import sqlite3
import json
import os
from pathlib import Path
from typing import List, Optional
from app.config import get_config

# 스키마는 저장소 한 곳(db/schema/schema.sql)에서만 관리한다.
# gateway가 따로 CREATE TABLE 을 들고 있으면 api 와 스키마가 어긋난다.
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "db" / "schema" / "schema.sql"

class Storage:
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = get_config().app.db_path
        
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
            
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self):
        """공용 스키마를 적용한다. 이미 있으면 아무것도 하지 않는다.

        기존 DB에 컬럼을 덧붙이는 마이그레이션은 db/migrate.py 가 담당한다.
        """
        if not SCHEMA_PATH.exists():
            raise FileNotFoundError(f"스키마 파일을 찾을 수 없습니다: {SCHEMA_PATH}")
        with self.conn:
            self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    def resolve_room_id(self) -> Optional[str]:
        """이 게이트웨이가 담당하는 공간 ID.

        config 에 명시돼 있으면 그것을 쓰고, 없으면 devices 테이블에서
        공간에 배정된 디바이스의 room_id 를 따른다. 아직 아무 디바이스도
        배정되지 않았다면 None 이고, 그 상태로 남긴 로그는 나중에
        db/migrate.py --backfill-room 으로 귀속시킬 수 있다.
        """
        configured = get_config().app.room_id
        if configured:
            return configured
        row = self.conn.execute(
            "SELECT room_id FROM devices WHERE room_id IS NOT NULL "
            "ORDER BY (type = 'env') DESC, id LIMIT 1"
        ).fetchone()
        return row[0] if row else None

    def register_device(self, device_id: str, device_type: str, timestamp: str) -> None:
        """처음 보는 디바이스를 미배정 상태로 등록하고 last_seen 을 갱신한다.

        사용자가 프론트에서 공간에 배정하기 전까지 room_id 는 NULL 이다.
        """
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO devices (id, room_id, type, name, location, enabled, last_seen)"
                " VALUES (?, NULL, ?, ?, '', 1, ?)",
                (device_id, device_type, device_id, timestamp),
            )
            self.conn.execute(
                "UPDATE devices SET last_seen = ? WHERE id = ?", (timestamp, device_id)
            )

    def fetch_pending_commands(self, room_id: Optional[str]) -> List[dict]:
        """프론트에서 들어온 수동 제어 명령 큐를 가져온다."""
        if room_id is None:
            return []
        rows = self.conn.execute(
            "SELECT id, action, method, payload_json FROM control_commands "
            "WHERE room_id = ? AND status = 'pending' ORDER BY created_at",
            (room_id,),
        ).fetchall()
        return [
            {"id": r[0], "action": r[1], "method": r[2], "payload_json": r[3]} for r in rows
        ]

    def mark_command(self, command_id: str, status: str, error_code: Optional[str],
                     resolved_at: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE control_commands SET status = ?, error_code = ?, resolved_at = ? WHERE id = ?",
                (status, error_code, resolved_at, command_id),
            )

    def insert_sensor_reading(self, timestamp: str, device_id: str, metric: str, value: float, quality: str, raw_payload: str):
        with self.conn:
            self.conn.execute(
                "INSERT INTO sensor_readings (timestamp, device_id, metric, value, quality, raw_payload) VALUES (?, ?, ?, ?, ?, ?)",
                (timestamp, device_id, metric, value, quality, raw_payload)
            )

    def insert_occupancy_estimate(self, timestamp: str, p_empty: float, p_transition: float, p_occupied: float, state: str, quality: str, reasons: List[str], room_id: Optional[str] = None):
        with self.conn:
            self.conn.execute(
                "INSERT INTO occupancy_estimates (timestamp, room_id, p_empty, p_transition, p_occupied, state, quality, reasons_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (timestamp, room_id if room_id is not None else self.resolve_room_id(),
                 p_empty, p_transition, p_occupied, state, quality, json.dumps(reasons))
            )

    def insert_control_decision(self, timestamp: str, control_mode: str, proposed_action: str, executed: bool, occupancy_state: str, temperature_c: Optional[float], co2_ppm: Optional[float], reason_codes: List[str], room_id: Optional[str] = None):
        with self.conn:
            self.conn.execute(
                "INSERT INTO control_decisions (timestamp, room_id, control_mode, proposed_action, executed, occupancy_state, temperature_c, co2_ppm, reason_codes_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (timestamp, room_id if room_id is not None else self.resolve_room_id(),
                 control_mode, proposed_action, executed, occupancy_state, temperature_c, co2_ppm, json.dumps(reason_codes))
            )

    def insert_ir_event(self, timestamp: str, direction: str, protocol: str, code_hash: str, source: str, raw_payload: str, room_id: Optional[str] = None):
        with self.conn:
            self.conn.execute(
                "INSERT INTO ir_events (timestamp, room_id, direction, protocol, code_hash, source, raw_payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (timestamp, room_id if room_id is not None else self.resolve_room_id(),
                 direction, protocol, code_hash, source, raw_payload)
            )

    def insert_system_event(self, timestamp: str, severity: str, event_type: str, message: str, room_id: Optional[str] = None):
        with self.conn:
            self.conn.execute(
                "INSERT INTO system_events (timestamp, room_id, severity, event_type, message) VALUES (?, ?, ?, ?, ?)",
                (timestamp, room_id if room_id is not None else self.resolve_room_id(),
                 severity, event_type, message)
            )

_storage_instance = None

def get_storage() -> Storage:
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = Storage()
    return _storage_instance
