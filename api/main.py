import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.db import close_pool, get_conn, open_pool
from api.routers import ai, auth, control, devices, events, inquiries, rooms, schedules
from api.security import get_current_user_id

@asynccontextmanager
async def lifespan(_app: FastAPI):
    open_pool()
    try:
        yield
    finally:
        close_pool()


app = FastAPI(title="ThermoShift API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS", "http://localhost:8501,http://localhost:8502"
        ).split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
_authenticated = [Depends(get_current_user_id)]
app.include_router(rooms.router, dependencies=_authenticated)
app.include_router(devices.router, dependencies=_authenticated)
app.include_router(schedules.router, dependencies=_authenticated)
app.include_router(control.router, dependencies=_authenticated)
app.include_router(events.router, dependencies=_authenticated)
app.include_router(inquiries.router, dependencies=_authenticated)
app.include_router(ai.router)


@app.get("/health")
def health():
    """GET /health

    Response:
    {
      "status": "ok" | "error",
      "db": "connected" | "disconnected",
      "check": 1 | null  # result of SELECT 1
    }
    """
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 AS check")
            row = cur.fetchone()
        return {"status": "ok", "db": "connected", "check": row["check"]}
    except Exception:
        return {"status": "error", "db": "disconnected", "check": None}
