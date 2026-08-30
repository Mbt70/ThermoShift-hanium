import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# /etc/thermoshift.env or local .env
load_dotenv("/etc/thermoshift.env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_USER = os.getenv("DB_USER", "thermoshift")
DB_PASSWORD = os.getenv("DB_PASSWORD", "mxJEssQM8i6HutY5jbkzAYIO")
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
