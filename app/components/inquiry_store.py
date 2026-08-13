import json
import uuid
from datetime import datetime
from pathlib import Path

_STORE_PATH = Path(__file__).resolve().parents[2] / ".data" / "inquiries.json"

ADMIN_PHONE = "1522-0000"


def _load_inquiries() -> list[dict]:
    if not _STORE_PATH.exists():
        return []
    return json.loads(_STORE_PATH.read_text(encoding="utf-8"))


def _save_inquiries(inquiries: list[dict]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(
        json.dumps(inquiries, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def submit_inquiry(*, room_id: str, log_id: str, message: str) -> dict:
    inquiries = _load_inquiries()
    inquiry = {
        "id": uuid.uuid4().hex,
        "room_id": room_id,
        "log_id": log_id,
        "message": message,
        "created_at": datetime.now().isoformat(),
    }
    inquiries.append(inquiry)
    _save_inquiries(inquiries)
    return inquiry
