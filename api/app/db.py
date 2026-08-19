"""SQLite 연결 관리.

통합 DB(단일 진실원)를 읽고 쓴다. 경로는 THERMOSHIFT_DB 환경변수로 바꿀 수 있다.
gateway가 같은 파일에 동시에 쓰기 때문에 WAL 모드를 전제로 한다.
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DB_PATH = Path(
    os.environ.get("THERMOSHIFT_DB", "/home/thermo/thermoshift-data/thermoshift.db")
)
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "db" / "schema" / "schema.sql"


def _configure(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # gateway가 쓰기 락을 잡고 있을 때 즉시 실패하지 않고 기다린다.
    conn.execute("PRAGMA busy_timeout = 5000")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    _configure(conn)
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """요청 단위 연결. 예외 발생 시 롤백한다."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """스키마를 적용한다. 이미 있으면 아무것도 하지 않는다."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def rows_to_dicts(rows) -> list[dict]:
    return [dict(row) for row in rows]
