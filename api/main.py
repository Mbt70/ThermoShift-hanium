from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.db import get_conn
from api.routers import auth, control, devices, events, rooms, schedules

app = FastAPI(title="ThermoShift API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev only
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(rooms.router)
app.include_router(devices.router)
app.include_router(schedules.router)
app.include_router(control.router)
app.include_router(events.router)


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
