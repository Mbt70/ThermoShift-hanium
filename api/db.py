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

# 하드코딩된 기본값을 두지 않는다 - 예전에는 .env 가 없어도 개발용 비밀번호로
# 조용히 접속을 시도했는데, 그 값이 이 저장소가 public 이라 이미 노출된
# 상태였다. 없으면 여기서 바로 멈추는 게 낫다.
_REQUIRED_ENV = ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME")
_missing = [name for name in _REQUIRED_ENV if not os.getenv(name)]
if _missing:
    raise RuntimeError(
        "DB 접속 정보 환경변수가 없습니다: " + ", ".join(_missing) + ".\n"
        "저장소 루트에서 .env.example 을 .env 로 복사해 값을 채우세요:\n"
        "    cp .env.example .env\n"
        "EC2/Docker 배포에서는 .env 를 docker compose --env-file 로 넘기거나 "
        "/etc/thermoshift.env 에 두세요."
    )

DB_HOST = os.environ["DB_HOST"]
DB_PORT = os.environ["DB_PORT"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_NAME = os.environ["DB_NAME"]

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


def open_pool() -> None:
    """애플리케이션 시작 시 연결을 만들고 DB 준비 여부를 확인한다."""
    _pool.open(wait=True)


def close_pool() -> None:
    """애플리케이션 종료 시 worker thread와 연결을 정리한다."""
    _pool.close()


@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    """Borrows a pooled connection with dict-row results, returning it to
    the pool (not closing it) on exit.

    Usage: `with get_conn() as conn, conn.cursor() as cur: ...`
    """
    with _pool.connection() as conn:
        yield conn
