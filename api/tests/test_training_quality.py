from datetime import datetime, timedelta, timezone

import pandas as pd

from ml.training_quality import assess_training_frame


def _frame(rows: int = 80) -> pd.DataFrame:
    start = datetime(2026, 9, 4, tzinfo=timezone.utc)
    return pd.DataFrame({
        "run_id": [2] * rows,
        "measured_at": [start + timedelta(seconds=30 * i) for i in range(rows)],
        "temperature": [24.0 + i * 0.02 for i in range(rows)],
        "dT_dt": [0.04] * rows,
        "cooling_u": [0] * 40 + [1] * (rows - 40),
        "actuation_verified": [True] * rows,
        "training_eligible": [True] * rows,
    })


def test_충분하고_ACK가_있는_run은_학습_가능하다():
    report = assess_training_frame(_frame())
    assert report.eligible
    assert report.reasons == []


def test_온도_여기가_작으면_거절한다():
    frame = _frame()
    frame["temperature"] = 24.0
    report = assess_training_frame(frame)
    assert not report.eligible
    assert any("온도 변화폭" in reason for reason in report.reasons)


def test_냉각_ON_ACK가_없으면_거절한다():
    frame = _frame()
    frame.loc[frame["cooling_u"] == 1, "actuation_verified"] = False
    report = assess_training_frame(frame)
    assert not report.eligible
    assert any("장치 ACK" in reason for reason in report.reasons)


def test_파일럿_부적합_표시를_무시하지_않는다():
    frame = _frame()
    frame["training_eligible"] = False
    report = assess_training_frame(frame)
    assert not report.eligible
    assert any("학습 부적합" in reason for reason in report.reasons)
