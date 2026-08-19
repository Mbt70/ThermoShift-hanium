from fastapi import APIRouter
from pydantic import BaseModel

from api.db import get_conn

router = APIRouter(tags=["inquiries"])

_COLUMNS = "inquiry_id, room_id, command_id, user_id, message, created_at"


class CreateInquiryRequest(BaseModel):
    command_id: int | None = None
    user_id: int | None = None
    message: str


@router.get("/rooms/{room_id}/inquiries")
def list_inquiries(room_id: int):
    """GET /rooms/{room_id}/inquiries

    Response: list of inquiries for the room, newest first.
    [
      {
        "inquiry_id": int, "room_id": int, "command_id": int | null,
        "user_id": int | null, "message": str, "created_at": str
      },
      ...
    ]
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {_COLUMNS} FROM inquiries WHERE room_id = %s ORDER BY created_at DESC",
            (room_id,),
        )
        return cur.fetchall()


@router.post("/rooms/{room_id}/inquiries")
def create_inquiry(room_id: int, body: CreateInquiryRequest):
    """POST /rooms/{room_id}/inquiries - Response: same shape as one list_inquiries() entry."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO inquiries (room_id, command_id, user_id, message)
            VALUES (%s, %s, %s, %s)
            RETURNING {_COLUMNS}
            """,
            (room_id, body.command_id, body.user_id, body.message),
        )
        row = cur.fetchone()
        conn.commit()
    return row
