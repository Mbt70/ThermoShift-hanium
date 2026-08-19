"""시간대 변환.

저장은 항상 UTC로 하고, API 응답은 로컬 시간대(offset 포함) ISO로 내보낸다.
프론트가 그대로 fromisoformat 해서 쓸 수 있게 하기 위한 것으로,
제어 로그와 알림 등 사용자에게 시각을 보여주는 모든 응답에 같은 규칙을 적용한다.
"""

import os
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo(os.environ.get("THERMOSHIFT_TZ", "Asia/Seoul"))


def to_local_iso(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(LOCAL_TZ).isoformat()


def local_day_range(day) -> tuple[str, str]:
    """로컬 날짜 하루 → UTC ISO 경계값 두 개."""
    start_local = datetime.combine(day, time.min, tzinfo=LOCAL_TZ)
    end_local = start_local + timedelta(days=1)
    return (
        start_local.astimezone(timezone.utc).isoformat(),
        end_local.astimezone(timezone.utc).isoformat(),
    )
