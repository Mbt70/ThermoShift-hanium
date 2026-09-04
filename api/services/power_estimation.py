"""전력계가 없는 목업의 순간 입력전력 추정.

실측 전력값이 있으면 언제나 그것을 우선한다. 없을 때만 ESP32가 회신한
펠티어 릴레이 상태와 명시적인 전기 가정으로 계산하며, 결과에 estimated와
basis를 함께 넣어 실측처럼 오해되지 않게 한다.
"""

from datetime import datetime, timezone
import os


def _positive_env(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


COOLING_VOLTAGE_V = _positive_env("THERMOSHIFT_COOLING_VOLTAGE_V", 12.0)
COOLING_CURRENT_A = _positive_env("THERMOSHIFT_COOLING_CURRENT_A", 5.0)
COOLING_RATED_POWER_W = round(COOLING_VOLTAGE_V * COOLING_CURRENT_A, 2)
STATE_MAX_AGE_SEC = 120


def _age_seconds(value: datetime | None) -> float | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - value).total_seconds())


def calculate_power_snapshot(
    *,
    measured_power_w: float | None,
    measured_at: datetime | None,
    cooling_state: str | None,
    cooling_state_at: datetime | None,
) -> dict:
    """실측 우선, 없으면 ``P = V × I × relay`` 로 순간전력을 계산한다."""
    if measured_power_w is not None:
        return {
            "power_w": round(float(measured_power_w), 2),
            "measured_at": measured_at,
            "source": "measured",
            "estimated": False,
            "basis": "power_meter",
            "cooling_state": cooling_state,
            "state_measured_at": cooling_state_at,
        }

    normalized = str(cooling_state or "").upper()
    state_age = _age_seconds(cooling_state_at)
    state_fresh = (
        normalized in {"ON", "OFF"}
        and state_age is not None
        and state_age <= STATE_MAX_AGE_SEC
    )
    if not state_fresh:
        return {
            "power_w": None,
            "measured_at": None,
            "source": "unavailable",
            "estimated": False,
            "basis": "relay_state_missing_or_stale",
            "cooling_state": normalized if normalized in {"ON", "OFF"} else "UNKNOWN",
            "state_measured_at": cooling_state_at,
        }

    power_w = COOLING_RATED_POWER_W if normalized == "ON" else 0.0
    return {
        "power_w": power_w,
        "measured_at": cooling_state_at,
        "source": "estimated",
        "estimated": True,
        "basis": (
            f"P=V×I×relay ({COOLING_VOLTAGE_V:g}V×"
            f"{COOLING_CURRENT_A:g}A×{1 if normalized == 'ON' else 0})"
        ),
        "rated_power_w": COOLING_RATED_POWER_W,
        "cooling_state": normalized,
        "state_measured_at": cooling_state_at,
        "limitations": "펠티어·동일 회선 팬의 설계 가정이며 10W 수동 히터는 제외",
    }
