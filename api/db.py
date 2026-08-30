import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# .env 는 저장소 루트에 있다 (api/ 가 아니라). 파일이 없어도(배포 환경처럼
# 진짜 환경변수로 주는 경우) load_dotenv 는 조용히 넘어간다.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_USER = os.getenv("DB_USER", "thermoshift")
DB_PASSWORD = os.getenv("DB_PASSWORD", "thermoshift1234")
DB_NAME = os.getenv("DB_NAME", "thermoshift")

_CONNINFO = psycopg.conninfo.make_conninfo(
    host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, dbname=DB_NAME
)

# Every request was opening a brand-new TCP + auth handshake to Postgres
# (psycopg.connect() per call), which is most of why every click felt
# laggy - a pool reuses a small set of already-open connections instead.
_pool = ConnectionPool(
    _CONNINFO,
    min_size=1,
    max_size=10,
    kwargs={"row_factory": dict_row},
    open=False,
)
_pool.open()


@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    """Borrows a pooled connection with dict-row results, returning it to
    the pool (not closing it) on exit.

    Usage: `with get_conn() as conn, conn.cursor() as cur: ...`
    """
    with _pool.connection() as conn:
        yield conn
