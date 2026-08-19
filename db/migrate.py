"""ThermoShift 통합 SQLite DB 마이그레이션.

기존 thermoshift-edge DB의 데이터를 보존하면서 통합 스키마로 승격시킵니다.
반복 실행해도 안전합니다(idempotent).

사용법:
    python db/migrate.py                      # 기본 경로로 마이그레이션
    python db/migrate.py --seed-from <path>   # 기존 edge DB에서 데이터 가져오기
"""

import argparse
import os
import shutil
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "db" / "schema" / "schema.sql"

DEFAULT_DB_PATH = os.environ.get(
    "THERMOSHIFT_DB", "/home/thermo/thermoshift-data/thermoshift.db"
)

# 기존 edge 테이블에 없던 컬럼. (테이블, 컬럼, 정의)
ADDED_COLUMNS = [
    ("occupancy_estimates", "room_id", "TEXT"),
    ("control_decisions", "room_id", "TEXT"),
    ("ir_events", "room_id", "TEXT"),
    ("system_events", "room_id", "TEXT"),
    ("schedules", "target_temperature", "REAL NOT NULL DEFAULT 24.0"),
]


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def add_missing_columns(conn: sqlite3.Connection) -> list[str]:
    """기존 테이블에 room_id 등 신규 컬럼을 덧붙인다.

    CREATE TABLE IF NOT EXISTS 는 이미 있는 테이블을 건드리지 않으므로,
    edge가 먼저 만든 테이블은 여기서 별도로 확장해야 한다.
    """
    applied = []
    for table, column, decl in ADDED_COLUMNS:
        if not table_exists(conn, table):
            continue
        if column in column_names(conn, table):
            continue
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        applied.append(f"{table}.{column}")
    return applied


def backfill_room_id(conn: sqlite3.Connection, room_id: str) -> dict[str, int]:
    """room_id 가 비어 있는 과거 행을 지정한 공간에 귀속시킨다.

    gateway가 단일 공간 전제로 수집한 기존 데이터를 다중 공간 스키마에
    맞춰 옮기기 위한 일회성 보정이다.
    """
    counts = {}
    for table, _, _ in ADDED_COLUMNS:
        if not table_exists(conn, table):
            continue
        cur = conn.execute(
            f"UPDATE {table} SET room_id = ? WHERE room_id IS NULL", (room_id,)
        )
        counts[table] = cur.rowcount
    return counts


def register_seen_devices(conn: sqlite3.Connection) -> int:
    """sensor_readings 에 등장한 device_id 를 devices 테이블에 등록한다."""
    type_by_metric = {
        "temperature": "env",
        "humidity": "env",
        "co2": "env",
        "pir": "pir",
        "door": "door",
        "power": "plug",
    }
    rows = conn.execute(
        "SELECT device_id, metric, MAX(timestamp) FROM sensor_readings GROUP BY device_id, metric"
    ).fetchall()

    seen: dict[str, tuple[str, str]] = {}
    for device_id, metric, last_ts in rows:
        dev_type = type_by_metric.get(metric, "env")
        prev = seen.get(device_id)
        # env 타입을 우선 채택하고, last_seen 은 가장 최근 값으로 유지
        if prev is None or (prev[0] != "env" and dev_type == "env"):
            seen[device_id] = (dev_type, last_ts)
        elif last_ts and prev[1] and last_ts > prev[1]:
            seen[device_id] = (prev[0], last_ts)

    added = 0
    for device_id, (dev_type, last_ts) in seen.items():
        cur = conn.execute(
            "INSERT OR IGNORE INTO devices (id, room_id, type, name, location, enabled, last_seen)"
            " VALUES (?, NULL, ?, ?, '', 1, ?)",
            (device_id, dev_type, device_id, last_ts),
        )
        added += cur.rowcount
    return added


def main() -> int:
    parser = argparse.ArgumentParser(description="ThermoShift DB 마이그레이션")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="대상 DB 경로")
    parser.add_argument(
        "--seed-from",
        default="/home/thermo/thermoshift-edge/thermoshift_edge.db",
        help="대상 DB가 없을 때 복사해올 기존 edge DB",
    )
    parser.add_argument(
        "--backfill-room",
        help="room_id 가 비어 있는 과거 행을 이 공간 ID로 귀속",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if not db_path.exists() and args.seed_from and Path(args.seed_from).exists():
        # WAL 잔여분까지 포함해 일관된 사본을 뜨기 위해 sqlite backup API를 쓴다.
        src = sqlite3.connect(args.seed_from)
        dst = sqlite3.connect(db_path)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        print(f"기존 데이터 복사: {args.seed_from} -> {db_path}")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    with conn:
        # 순서 주의: schema.sql 이 room_id 인덱스를 만들기 때문에,
        # 기존 edge 테이블에 컬럼을 먼저 붙인 뒤 스키마를 적용해야 한다.
        added_cols = add_missing_columns(conn)
        apply_schema(conn)
        added_devices = register_seen_devices(conn)
        backfilled = {}
        if args.backfill_room:
            backfilled = backfill_room_id(conn, args.backfill_room)

    print(f"DB              : {db_path}")
    print(f"추가된 컬럼     : {', '.join(added_cols) if added_cols else '없음'}")
    print(f"등록된 디바이스 : {added_devices}건")
    if backfilled:
        for table, count in backfilled.items():
            print(f"  backfill {table}: {count}행")

    print("\n테이블별 행 수")
    for (name,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ):
        count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"  {name:<22} {count}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
