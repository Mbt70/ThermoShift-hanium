"""오프라인 로컬 버퍼 (SQLite).

EC2 이전(2026-09) 이후 게이트웨이(파이)와 PostgreSQL(EC2)은 Tailscale
사설망을 넘어 통신한다. 지금까지는 그 구간이 끊기면 Storage 의 각
insert_* 가 예외를 던지고, main.py 의 run_loop 은 로그만 남긴 채 그
주기의 측정값·판단을 그냥 버렸다 — 파이가 살아 있어도 네트워크만 끊기면
데이터가 조용히 유실됐다는 뜻이다.

이 모듈은 그 유실을 막는다. DB 쓰기가 연결 실패로 못 나가면 같은 인자를
여기(SQLite, 파이 로컬 디스크)에 순서대로 쌓아 두고, Storage.flush_pending()
이 연결이 돌아왔을 때 순서대로 다시 밀어 넣는다. 재실 추정 같은 큰 계산은
다시 하지 않는다 — 그 시점의 판단 결과 자체를 그대로 보존해 두는 것이라
"몇 분 뒤에 뒤늦게 계산한 값"이 아니라 "그때 실제로 있었던 값"이 들어간다.
"""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

# gateway/app/local_buffer.py 에서 한 단계 위가 gateway/. 저장소 루트가
# 아니라 gateway/ 밑에 두는 이유는 이게 이 게이트웨이 프로세스 전용의
# 임시 재전송 큐이지, api·web 이 참조하는 데이터가 아니기 때문이다.
_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "buffer.sqlite3"


class LocalBuffer:
    """실패한 쓰기를 (메서드 이름, 인자) 로 저장해 두는 FIFO 큐.

    MQTT 콜백 스레드와 제어 루프 스레드 양쪽에서 쓰이므로 락으로 보호한다.
    """

    def __init__(self, db_path: Path | str = _DEFAULT_DB_PATH):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS pending_writes ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " queued_at TEXT NOT NULL DEFAULT (datetime('now')),"
            " method TEXT NOT NULL,"
            " kwargs_json TEXT NOT NULL)"
        )
        self._conn.commit()

    def enqueue(self, method: str, kwargs: dict[str, Any]) -> None:
        """kwargs 는 Storage 의 해당 메서드를 나중에 **kwargs 로 다시 부를
        인자다 — JSON 으로 직렬화되므로 str/float/bool/None/list 정도만
        담을 수 있다 (Storage 의 insert_* 는 전부 이 범위 안에서 받는다)."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO pending_writes (method, kwargs_json) VALUES (?, ?)",
                (method, json.dumps(kwargs, default=str)),
            )
            self._conn.commit()

    def pending(self, limit: int = 200) -> list[tuple[int, str, dict]]:
        """오래된 것부터 최대 limit 개. 순서를 지켜야 재생 결과가 원래
        타임라인과 맞는다."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, method, kwargs_json FROM pending_writes ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
        return [(row_id, method, json.loads(kwargs_json)) for row_id, method, kwargs_json in rows]

    def discard(self, row_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM pending_writes WHERE id = ?", (row_id,))
            self._conn.commit()

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT count(*) FROM pending_writes").fetchone()
        return row[0]
