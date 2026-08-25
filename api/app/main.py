"""ThermoShift API.

역할은 둘로 좁혀져 있다.
  - 읽기: gateway가 통합 SQLite에 남긴 센서·재실·제어 로그를 프론트가 쓰는 형태로 제공
  - 쓰기: 공간/디바이스/예약/사용자 등 운영 메타데이터와 사용자 제어 명령 큐

실시간 제어 판단 자체는 gateway(app/controller.py)가 담당한다.
API는 제어 로직을 직접 실행하지 않는다 — 명령이 두 곳에서 나가는 것을 막기 위해서다.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import DB_PATH, get_conn, init_db
from .routers import ai, alerts, auth, control, devices, rooms, schedules

logging.basicConfig(
    level=os.environ.get("THERMOSHIFT_LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    logger.info("ThermoShift API 시작. DB=%s", DB_PATH)
    yield


app = FastAPI(
    title="ThermoShift API",
    description="실내 열환경 최적화 시스템의 데이터·제어 API",
    version="0.1.0",
    lifespan=lifespan,
)

# 프론트는 다른 출처(로컬 8501, Vercel 도메인)에서 뜨므로 CORS를 연다.
# 인증은 Authorization 헤더의 토큰으로 하고 쿠키를 쓰지 않으므로
# allow_credentials 는 꺼 둔다. 켜 두면 브라우저가 와일드카드를 거부하고,
# 무엇보다 CSRF 표면이 생긴다.
allowed_origins = [
    o.strip() for o in os.environ.get("THERMOSHIFT_ALLOWED_ORIGINS", "*").split(",") if o.strip()
]
if allowed_origins == ["*"]:
    logger.warning(
        "CORS가 모든 출처에 열려 있습니다. 공인 주소로 배포할 때는 "
        "THERMOSHIFT_ALLOWED_ORIGINS 에 프론트 도메인을 지정하세요."
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(rooms.router)
app.include_router(devices.router)
app.include_router(control.router)
app.include_router(alerts.router)
app.include_router(schedules.router)
app.include_router(ai.router)


@app.get("/api/health")
def health():
    """DB 연결과 데이터 적재 상태를 한눈에 보여주는 헬스체크."""
    with get_conn() as conn:
        counts = {}
        for table in ("rooms", "devices", "sensor_readings", "control_decisions",
                      "occupancy_estimates", "alerts", "control_commands"):
            counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        last_reading = conn.execute(
            "SELECT MAX(timestamp) FROM sensor_readings"
        ).fetchone()[0]
    return {
        "status": "ok",
        "db_path": str(DB_PATH),
        "counts": counts,
        "last_sensor_reading": last_reading,
    }
