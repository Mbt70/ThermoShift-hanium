"""CO2 기준선(외기 수준) 추정.

왜 필요한가
-----------
재실 추정은 "지금 CO2 가 사람이 없을 때보다 얼마나 높은가"(co2_delta_baseline)
를 근거로 쓴다. 그런데 gateway/app/feature_engine.py 의 `_get_co2_baseline()`
은 `return 500.0` 하드코딩이었다. 실측 최소값이 549ppm 이므로 이 기준선은
항상 최소 49ppm 낮게 잡히고, 그만큼 delta 가 부풀려져 **아무도 없을 때조차
재실 쪽으로 기운다**. 실제로 저장된 추정 4,103건 중 3,804건이 TRANSITION 에
머물렀던 것과 무관하지 않다.

어떻게 추정하는가
-----------------
사람이 없는 시간대의 CO2 는 외기 수준으로 수렴한다. 따라서 최근 창의 낮은
분위수가 곧 기준선이다. 평균이나 최소값을 쓰지 않는 이유:

  - 평균은 재실 시간이 길면 그만큼 따라 올라간다.
  - 최소값은 센서 튐(스파이크 하강) 한 번에 통째로 끌려간다.

그래서 5% 분위수를 쓰고, 외기 CO2 의 물리적 하한(약 400ppm)으로 한 번 더
막는다. 관측이 부족하면 추정하지 않고 None 을 돌려준다 — 근거 없는 숫자를
만들어 내는 것보다 "모른다" 가 낫다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# 실외 대기 CO2 농도. 이보다 낮은 기준선은 물리적으로 나올 수 없으므로
# 센서 드리프트나 계산 오류로 본다.
OUTDOOR_FLOOR_PPM = 400.0

# 기준선을 잡을 분위수. 낮을수록 '완전 공실' 에 가깝지만 잡음에 약해진다.
BASELINE_QUANTILE = 0.05

# 이 개수보다 적은 표본으로는 분위수를 믿을 수 없다.
MIN_SAMPLES = 30

# 기준선을 되돌아보는 창. 하루를 보면 야간 공실 구간이 반드시 포함된다.
DEFAULT_WINDOW = timedelta(hours=24)


def quantile(values: list[float], q: float) -> float:
    """선형 보간 분위수. numpy 없이 게이트웨이에서도 쓰려고 직접 둔다."""
    if not values:
        raise ValueError("빈 표본")
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def estimate(samples: list[tuple[datetime, float]],
             now: datetime | None = None,
             window: timedelta = DEFAULT_WINDOW) -> float | None:
    """(시각, co2) 목록에서 기준선을 추정한다. 근거가 모자라면 None.

    samples 는 정렬돼 있지 않아도 된다. now 를 주면 그 시점 기준으로
    window 만큼 되돌아본다.
    """
    if not samples:
        return None
    now = now or max(t for t, _ in samples)
    cutoff = now - window
    vals = [v for t, v in samples if cutoff <= t <= now and v is not None]
    if len(vals) < MIN_SAMPLES:
        return None
    return max(quantile(vals, BASELINE_QUANTILE), OUTDOOR_FLOOR_PPM)


class RollingCo2Baseline:
    """게이트웨이가 들고 다니는 기준선 추정기.

    30초마다 값을 하나씩 받아 창을 밀고, 필요할 때 기준선을 돌려준다.
    재계산이 잦으므로 매번 정렬하지 않고 캐시를 둔다.
    """

    def __init__(self, window: timedelta = DEFAULT_WINDOW,
                 refresh: timedelta = timedelta(minutes=5)):
        self._samples: list[tuple[datetime, float]] = []
        self._window = window
        self._refresh = refresh
        self._cached: float | None = None
        self._cached_at: datetime | None = None

    def add(self, at: datetime, co2: float | None) -> None:
        if co2 is None:
            return
        self._samples.append((at, co2))
        cutoff = at - self._window
        if self._samples[0][0] < cutoff:
            self._samples = [s for s in self._samples if s[0] >= cutoff]

    def value(self, now: datetime) -> float | None:
        """현재 기준선. 근거가 모자라면 None 을 돌려준다.

        호출부는 None 을 받으면 co2_delta_baseline 을 근거에서 빼야 한다.
        기본값을 끼워 넣으면 없는 근거가 있는 것처럼 되기 때문이다.
        """
        if (self._cached_at is None
                or now - self._cached_at >= self._refresh):
            self._cached = estimate(self._samples, now, self._window)
            self._cached_at = now
        return self._cached

    @property
    def sample_count(self) -> int:
        return len(self._samples)
