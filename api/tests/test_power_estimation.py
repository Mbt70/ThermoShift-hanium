from datetime import datetime, timedelta, timezone

from api.services import power_estimation


def test_전력계_실측값을_릴레이_추정보다_우선한다():
    now = datetime.now(timezone.utc)
    result = power_estimation.calculate_power_snapshot(
        measured_power_w=47.3,
        measured_at=now,
        cooling_state="OFF",
        cooling_state_at=now,
    )
    assert result["power_w"] == 47.3
    assert result["source"] == "measured"
    assert result["estimated"] is False


def test_전력계가_없으면_최신_릴레이_ON과_정격가정으로_계산한다(monkeypatch):
    monkeypatch.setattr(power_estimation, "COOLING_RATED_POWER_W", 60.0)
    result = power_estimation.calculate_power_snapshot(
        measured_power_w=None,
        measured_at=None,
        cooling_state="ON",
        cooling_state_at=datetime.now(timezone.utc),
    )
    assert result["power_w"] == 60.0
    assert result["source"] == "estimated"
    assert result["estimated"] is True
    assert "relay" in result["basis"]


def test_릴레이_OFF면_추정_순간전력은_0이다():
    result = power_estimation.calculate_power_snapshot(
        measured_power_w=None,
        measured_at=None,
        cooling_state="OFF",
        cooling_state_at=datetime.now(timezone.utc),
    )
    assert result["power_w"] == 0.0
    assert result["estimated"] is True


def test_릴레이_상태가_오래됐으면_전력을_만들어내지_않는다():
    result = power_estimation.calculate_power_snapshot(
        measured_power_w=None,
        measured_at=None,
        cooling_state="ON",
        cooling_state_at=datetime.now(timezone.utc) - timedelta(seconds=121),
    )
    assert result["power_w"] is None
    assert result["source"] == "unavailable"
