import sys
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from shared.api_client import api_get, api_post

ADMIN_PHONE = "1522-0000"


def submit_inquiry(*, room_id: int, log_id: int | None = None, user_id: int | None = None, message: str) -> dict:
    return api_post(
        f"/rooms/{room_id}/inquiries",
        json={"command_id": log_id, "user_id": user_id, "message": message},
    )


def list_inquiries(room_id: int) -> list[dict]:
    return api_get(f"/rooms/{room_id}/inquiries") or []
