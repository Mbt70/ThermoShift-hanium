import os
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_USER = os.getenv("DB_USER", "thermoshift")
DB_PASSWORD = os.getenv("DB_PASSWORD", "thermoshift1234")
DB_NAME = os.getenv("DB_NAME", "thermoshift")


@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    """Opens a psycopg connection with dict-row results, closing it on exit.

    Usage: `with get_conn() as conn, conn.cursor() as cur: ...`
    """
    conn = psycopg.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=DB_NAME,
        row_factory=dict_row,
    )
    try:
        yield conn
    finally:
        conn.close()
