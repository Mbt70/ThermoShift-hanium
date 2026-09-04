"""열모델/PINN 학습 전에 데이터 식별 가능성과 출처를 검사한다."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from ml.thermal_model import (
    MIN_COOLING_SAMPLES,
    MIN_IDLE_SAMPLES,
    MIN_SAMPLES,
    MIN_TEMP_RANGE_C,
)


@dataclass(frozen=True)
class TrainingQualityReport:
    eligible: bool
    reasons: list[str]
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _bool_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes"})


def assess_training_frame(df: pd.DataFrame) -> TrainingQualityReport:
    """PINN 입력이 학습·검증 가능한지 보수적으로 판정한다.

    행 수만 보는 것으로는 부족하다. 온도 여기가 있어야 하고, 냉각 ON/OFF가
    모두 있어야 하며, ON 구간은 실제 장치 ACK로 확인돼야 한다. 또한 무작위
    행 분할 대신 run 단위 분할이 가능하도록 run_id를 요구한다.
    """
    reasons: list[str] = []
    metrics: dict[str, Any] = {"rows": len(df)}
    required = {"run_id", "measured_at", "temperature", "dT_dt", "cooling_u"}
    missing = sorted(required - set(df.columns))
    if missing:
        reasons.append("필수 열이 없습니다: " + ", ".join(missing))
        return TrainingQualityReport(False, reasons, metrics)

    temperatures = pd.to_numeric(df["temperature"], errors="coerce")
    cooling = pd.to_numeric(df["cooling_u"], errors="coerce")
    derivatives = pd.to_numeric(df["dT_dt"], errors="coerce")
    valid = temperatures.notna() & cooling.notna() & derivatives.notna()
    metrics["valid_rows"] = int(valid.sum())

    if int(valid.sum()) < MIN_SAMPLES:
        reasons.append(
            f"유효 표본이 {int(valid.sum())}개뿐입니다 (최소 {MIN_SAMPLES})."
        )

    valid_temperatures = temperatures[temperatures.notna()]
    spread = (
        float(valid_temperatures.max() - valid_temperatures.min())
        if not valid_temperatures.empty else 0.0
    )
    metrics["temperature_range_c"] = round(spread, 4)
    if spread < MIN_TEMP_RANGE_C:
        reasons.append(
            f"온도 변화폭이 {spread:.2f}°C뿐입니다 (최소 {MIN_TEMP_RANGE_C}°C)."
        )

    invalid_u = cooling.dropna()[~cooling.dropna().isin([0, 1])]
    if not invalid_u.empty:
        reasons.append("cooling_u는 이진값 0/1이어야 합니다.")
    n_on = int((cooling == 1).sum())
    n_off = int((cooling == 0).sum())
    metrics.update({"cooling_on_rows": n_on, "cooling_off_rows": n_off})
    if n_on < MIN_COOLING_SAMPLES:
        reasons.append(f"냉각 ON 표본이 {n_on}개입니다 (최소 {MIN_COOLING_SAMPLES}).")
    if n_off < MIN_IDLE_SAMPLES:
        reasons.append(f"냉각 OFF 표본이 {n_off}개입니다 (최소 {MIN_IDLE_SAMPLES}).")

    stamps = pd.to_datetime(df["measured_at"], errors="coerce", utc=True)
    if stamps.isna().any():
        reasons.append("해석할 수 없는 measured_at 값이 있습니다.")
    elif not stamps.is_monotonic_increasing:
        reasons.append("measured_at이 시간순으로 정렬돼 있지 않습니다.")
    else:
        gaps = stamps.diff().dt.total_seconds().dropna()
        max_gap = float(gaps.max()) if not gaps.empty else 0.0
        metrics["max_gap_sec"] = round(max_gap, 3)
        if max_gap > 120:
            reasons.append(f"표본 사이 최대 공백이 {max_gap:.1f}초로 너무 깁니다.")

    if "actuation_verified" not in df.columns:
        reasons.append("액추에이터 실제 상태를 확인하는 actuation_verified 열이 없습니다.")
    else:
        verified = _bool_series(df["actuation_verified"])
        unverified_on = int(((cooling == 1) & ~verified).sum())
        metrics["unverified_cooling_on_rows"] = unverified_on
        if unverified_on:
            reasons.append(f"냉각 ON {unverified_on}개 표본에 장치 ACK가 없습니다.")

    if "training_eligible" not in df.columns:
        reasons.append("데이터 품질 승인 열(training_eligible)이 없습니다.")
    else:
        approved = _bool_series(df["training_eligible"])
        if not bool(approved.all()):
            reasons.append("품질 검토에서 학습 부적합으로 표시된 표본이 포함돼 있습니다.")

    run_ids = df["run_id"].dropna().astype(str).unique().tolist()
    metrics["run_ids"] = run_ids
    return TrainingQualityReport(not reasons, reasons, metrics)
