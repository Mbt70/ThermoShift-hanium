"""실측 센서 기록을 학습용 에폭 표로 만든다.

게이트웨이는 30초마다 한 번 판단하고, 그때 feature_engine 이 만든 피처를
본다. 학습도 **똑같은 피처** 위에서 해야 파라미터가 그대로 옮겨간다.
그래서 여기서는 원본 측정값을 30초 격자에 올린 뒤, feature_engine 의 정의를
그대로 다시 계산한다. 정의가 갈라지면 학습한 값이 현장에서 다른 뜻이 된다.

데이터 출처는 두 곳을 모두 지원한다.
  - PostgreSQL (운영) — sensor_env / sensor_pir / sensor_door
  - SQLite   (구 기록) — sensor_readings 평면 표

빈 시간대를 억지로 메우지 않는다. 10분 넘게 관측이 끊기면 다른 세션으로
쪼갠다. 파이가 꺼져 있던 구간을 이어 붙이면 HMM 이 있지도 않은 상태 전이를
배우기 때문이다.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ml.co2_baseline import RollingCo2Baseline

# 게이트웨이의 판단 주기. config.control.decision_interval_sec 와 같아야 한다.
EPOCH_SEC = 30

# 이 시간 넘게 관측이 없으면 다른 세션이다.
SESSION_GAP = timedelta(minutes=10)

# feature_engine 과 같은 값 — 최근성 판정 기준.
RECENT_SEC = 120

# 기울기를 재는 창.
SLOPE_MINUTES = 5


@dataclass
class Reading:
    at: datetime
    temperature: float | None = None
    humidity: float | None = None
    co2: float | None = None


@dataclass
class OccReading:
    at: datetime
    motion: bool | None = None
    door_open: bool | None = None


@dataclass
class Epoch:
    """한 판단 주기의 피처. 이름은 feature_engine.compute_features() 와 같다."""
    at: datetime
    pir_recent: bool
    pir_age_sec: float
    door_recent: bool
    door_age_sec: float
    co2: float | None
    co2_slope_5m: float
    co2_delta_baseline: float | None
    temperature: float | None
    temperature_slope_5m: float
    env_fresh: bool
    occ_fresh: bool


@dataclass
class Session:
    """관측이 끊기지 않은 한 구간."""
    started_at: datetime
    ended_at: datetime
    epochs: list[Epoch] = field(default_factory=list)

    @property
    def hours(self) -> float:
        return (self.ended_at - self.started_at).total_seconds() / 3600


# =====================================================================
# 적재
# =====================================================================
def load_sqlite(path: str, device_env="env_01", device_occ="occ_01"
                ) -> tuple[list[Reading], list[OccReading]]:
    """구 SQLite 의 평면 sensor_readings 를 읽어 종류별로 나눈다."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    env: dict[datetime, Reading] = {}
    for r in con.execute(
        """SELECT timestamp, metric, value FROM sensor_readings
           WHERE device_id=? AND metric IN ('temperature','humidity','co2')
           ORDER BY timestamp""", (device_env,)):
        at = datetime.fromisoformat(r["timestamp"])
        e = env.setdefault(at, Reading(at))
        setattr(e, r["metric"], r["value"])

    occ: dict[datetime, OccReading] = {}
    for r in con.execute(
        """SELECT timestamp, metric, value FROM sensor_readings
           WHERE device_id=? AND metric IN ('pir','door')
           ORDER BY timestamp""", (device_occ,)):
        at = datetime.fromisoformat(r["timestamp"])
        o = occ.setdefault(at, OccReading(at))
        if r["metric"] == "pir":
            o.motion = bool(r["value"])
        else:
            o.door_open = bool(r["value"])
    con.close()
    return sorted(env.values(), key=lambda x: x.at), sorted(occ.values(), key=lambda x: x.at)


def load_postgres(room_id: int | None = None
                  ) -> tuple[list[Reading], list[OccReading]]:
    """운영 DB 에서 읽는다. 공간을 지정하지 않으면 첫 공간을 쓴다."""
    import psycopg

    conninfo = psycopg.conninfo.make_conninfo(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        user=os.getenv("DB_USER", "thermoshift"),
        password=os.environ["DB_PASSWORD"],
        dbname=os.getenv("DB_NAME", "thermoshift"),
    )
    with psycopg.connect(conninfo) as conn, conn.cursor() as cur:
        if room_id is None:
            row = cur.execute(
                """SELECT room_id FROM rooms WHERE name <> '미배정'
                   ORDER BY room_id LIMIT 1""").fetchone()
            if row is None:
                return [], []
            room_id = row[0]

        env = [Reading(at, t and float(t), h and float(h), c and float(c))
               for at, t, h, c in cur.execute(
                   """SELECT e.measured_at, e.temperature, e.humidity, e.co2
                      FROM sensor_env e JOIN devices d USING (device_id)
                      WHERE d.room_id = %s ORDER BY e.measured_at""",
                   (room_id,)).fetchall()]

        occ: dict[datetime, OccReading] = {}
        for at, motion in cur.execute(
            """SELECT p.measured_at, p.motion FROM sensor_pir p
               JOIN devices d USING (device_id)
               WHERE d.room_id = %s ORDER BY p.measured_at""",
                (room_id,)).fetchall():
            occ.setdefault(at, OccReading(at)).motion = motion
        for at, state in cur.execute(
            """SELECT s.measured_at, s.door_state FROM sensor_door s
               JOIN devices d USING (device_id)
               WHERE d.room_id = %s ORDER BY s.measured_at""",
                (room_id,)).fetchall():
            occ.setdefault(at, OccReading(at)).door_open = (state == "open")

    return env, sorted(occ.values(), key=lambda x: x.at)


# =====================================================================
# 피처 계산
# =====================================================================
def _slope_per_minute(window: list[tuple[datetime, float]]) -> float:
    """최소제곱 기울기 (단위/분). feature_engine._calculate_slope 와 같은 식."""
    if len(window) < 2:
        return 0.0
    t0 = window[0][0]
    xs = [(t - t0).total_seconds() / 60.0 for t, _ in window]
    ys = [v for _, v in window]
    n = len(xs)
    sx, sy = sum(xs), sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sxx = sum(x * x for x in xs)
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0
    return (n * sxy - sx * sy) / denom


def _split_sessions(times: list[datetime]) -> list[tuple[datetime, datetime]]:
    if not times:
        return []
    spans = [[times[0], times[0]]]
    for a, b in zip(times, times[1:]):
        if b - a > SESSION_GAP:
            spans.append([b, b])
        else:
            spans[-1][1] = b
    return [(s, e) for s, e in spans]


def build_sessions(env: list[Reading], occ: list[OccReading],
                   min_epochs: int = 10) -> list[Session]:
    """30초 격자 에폭으로 세션들을 만든다.

    문 '이벤트' 는 상태가 바뀐 순간만 센다. 닫힌 채로 있는 것은 사건이
    아니기 때문이다 (feature_engine 도 door_event 로 같은 구분을 한다).
    """
    all_times = sorted({r.at for r in env} | {o.at for o in occ})
    sessions: list[Session] = []

    # 문 상태 변화 시각을 미리 뽑아 둔다.
    door_events: list[datetime] = []
    prev_door: bool | None = None
    for o in occ:
        if o.door_open is None:
            continue
        if prev_door is not None and o.door_open != prev_door:
            door_events.append(o.at)
        prev_door = o.door_open

    motion_times = [o.at for o in occ if o.motion]
    env_times = [r.at for r in env]

    for start, end in _split_sessions(all_times):
        # 기준선은 세션 안에서만 굴린다. 세션 사이에 몇 주가 비어 있으면
        # 그때의 CO2 를 지금 기준선으로 쓸 수 없다.
        baseline = RollingCo2Baseline()
        session = Session(start, end)

        env_in = [r for r in env if start <= r.at <= end]
        for r in env_in:
            baseline.add(r.at, r.co2)

        occ_in_span = any(start <= t <= end for t in [o.at for o in occ])

        t = start
        ei = 0
        while t <= end:
            # --- 최근성 ---
            recent_motion = [x for x in motion_times if x <= t]
            pir_age = ((t - recent_motion[-1]).total_seconds()
                       if recent_motion else 999999.0)
            recent_door = [x for x in door_events if x <= t]
            door_age = ((t - recent_door[-1]).total_seconds()
                        if recent_door else 999999.0)

            # --- 창 안의 환경값 ---
            lo = t - timedelta(minutes=SLOPE_MINUTES)
            while ei < len(env_in) and env_in[ei].at < lo:
                ei += 1
            win = [r for r in env_in[ei:] if r.at <= t]
            co2_win = [(r.at, r.co2) for r in win if r.co2 is not None]
            temp_win = [(r.at, r.temperature) for r in win if r.temperature is not None]

            co2_now = co2_win[-1][1] if co2_win else None
            temp_now = temp_win[-1][1] if temp_win else None
            base = baseline.value(t)
            delta = (max(0.0, co2_now - base)
                     if (co2_now is not None and base is not None) else None)

            # 마지막 관측이 얼마나 오래됐는지로 신선도를 본다.
            last_env = max((r.at for r in env_in if r.at <= t), default=None)
            last_occ = max((o.at for o in occ if o.at <= t), default=None)

            session.epochs.append(Epoch(
                at=t,
                pir_recent=pir_age <= RECENT_SEC,
                pir_age_sec=pir_age,
                door_recent=door_age <= RECENT_SEC,
                door_age_sec=door_age,
                co2=co2_now,
                co2_slope_5m=_slope_per_minute(co2_win),
                co2_delta_baseline=delta,
                temperature=temp_now,
                temperature_slope_5m=_slope_per_minute(temp_win),
                env_fresh=(last_env is not None
                           and (t - last_env).total_seconds() <= 120),
                occ_fresh=(last_occ is not None
                           and (t - last_occ).total_seconds() <= 180),
            ))
            t += timedelta(seconds=EPOCH_SEC)

        # 재실 센서가 아예 없던 세션은 학습에 넣지 않는다. PIR 없는 구간을
        # '움직임 없음' 으로 읽으면 공실 확률만 잔뜩 배운다.
        if len(session.epochs) >= min_epochs and occ_in_span:
            sessions.append(session)

    return sessions


def summarize(sessions: list[Session]) -> str:
    lines = []
    total_ep = sum(len(s.epochs) for s in sessions)
    total_h = sum(s.hours for s in sessions)
    lines.append(f"세션 {len(sessions)}개 · 에폭 {total_ep}개 · 관측 {total_h:.2f}시간")
    for s in sessions:
        pir = sum(1 for e in s.epochs if e.pir_recent)
        door = sum(1 for e in s.epochs if e.door_recent)
        lines.append(
            f"  {s.started_at:%m-%d %H:%M}~{s.ended_at:%H:%M} "
            f"{s.hours:5.2f}h  에폭 {len(s.epochs):4d}  "
            f"PIR최근 {pir:4d}({pir/max(1,len(s.epochs)):.0%})  "
            f"문최근 {door:3d}")
    return "\n".join(lines)
