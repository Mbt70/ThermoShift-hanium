"""열모델(a, b, d)을 실측으로 교정한다.

    python -m ml.train_thermal                       # 구 SQLite 기록으로
    python -m ml.train_thermal --source postgres
    python -m ml.train_thermal --since 2026-09-01T13:00

결과는 ml/params/thermal.json 에 쓴다. 파일이 없으면 게이트웨이는 코드에
박힌 가정값을 쓰고, 그 사실을 '가정값' 으로 표시한다.

식별에 필요한 자료가 모자라면 값을 만들어 내지 않고 무엇이 부족한지와
어떤 실험을 하면 되는지를 출력한다.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from ml.thermal_model import (STEP_TEST_GUIDE, ThermalModel, assess, identify)

DEFAULT_SQLITE = "/home/thermo/thermoshift-data/thermoshift.db"
PARAM_PATH = Path(__file__).resolve().parent / "params" / "thermal.json"


def load_sqlite_samples(path: str, since: datetime | None
                        ) -> list[tuple[datetime, float, int]]:
    """(시각, 온도, 냉방여부). 냉방여부는 제어 판단 기록에서 되살린다."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    # 냉방이 켜져 있던 구간: POWER_OFF 가 아닌 판단이 실제로 실행된 시점부터
    # 다음 POWER_OFF 실행까지. 실행되지 않은 판단은 송신이 없었으므로
    # 냉방 상태를 바꾸지 않는다.
    spans: list[tuple[datetime, datetime | None]] = []
    on_at: datetime | None = None
    for r in con.execute(
        """SELECT timestamp, proposed_action FROM control_decisions
           WHERE executed = 1 ORDER BY timestamp"""):
        at = datetime.fromisoformat(r["timestamp"])
        if r["proposed_action"] == "POWER_OFF":
            if on_at:
                spans.append((on_at, at))
                on_at = None
        elif on_at is None:
            on_at = at
    if on_at:
        spans.append((on_at, None))

    def cooling(at: datetime) -> int:
        return int(any(s <= at and (e is None or at < e) for s, e in spans))

    rows = []
    for r in con.execute(
        """SELECT timestamp, value FROM sensor_readings
           WHERE metric='temperature' ORDER BY timestamp"""):
        at = datetime.fromisoformat(r["timestamp"])
        if since and at < since:
            continue
        rows.append((at, float(r["value"]), cooling(at)))
    con.close()
    return rows


def load_pg_samples(since: datetime | None, room_id: int | None
                    ) -> list[tuple[datetime, float, int]]:
    import psycopg
    conninfo = psycopg.conninfo.make_conninfo(
        host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
        user=os.getenv("DB_USER", "thermoshift"),
        password=os.getenv("DB_PASSWORD", "thermoshift1234"),
        dbname=os.getenv("DB_NAME", "thermoshift"))
    with psycopg.connect(conninfo) as conn, conn.cursor() as cur:
        if room_id is None:
            row = cur.execute("SELECT room_id FROM rooms WHERE name <> '미배정'"
                              " ORDER BY room_id LIMIT 1").fetchone()
            if row is None:
                return []
            room_id = row[0]
        spans, on_at = [], None
        for at, ctype in cur.execute(
            """SELECT issued_at, command_type FROM hvac_commands
               WHERE room_id=%s AND command_status IN ('sent','acked')
               ORDER BY issued_at""", (room_id,)).fetchall():
            if ctype == "power_off":
                if on_at:
                    spans.append((on_at, at)); on_at = None
            elif on_at is None:
                on_at = at
        if on_at:
            spans.append((on_at, None))
        cooling = lambda at: int(any(
            s <= at and (e is None or at < e) for s, e in spans))
        rows = [(at, float(t), cooling(at)) for at, t in cur.execute(
            """SELECT e.measured_at, e.temperature FROM sensor_env e
               JOIN devices d USING (device_id)
               WHERE d.room_id=%s AND e.temperature IS NOT NULL
                 AND (%s::timestamptz IS NULL OR e.measured_at >= %s)
               ORDER BY e.measured_at""", (room_id, since, since)).fetchall()]
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", choices=["sqlite", "postgres"], default="sqlite")
    ap.add_argument("--sqlite", default=DEFAULT_SQLITE)
    ap.add_argument("--room-id", type=int, default=None)
    ap.add_argument("--since", type=datetime.fromisoformat, default=None)
    ap.add_argument("--out", default=str(PARAM_PATH))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("== 자료 적재")
    samples = (load_pg_samples(args.since, args.room_id)
               if args.source == "postgres"
               else load_sqlite_samples(args.sqlite, args.since))
    if not samples:
        raise SystemExit("온도 기록이 없습니다.")

    temps = [t for _, t, _ in samples]
    n_cool = sum(u for _, _, u in samples)
    print(f"   표본 {len(samples)}개  {samples[0][0]:%Y-%m-%d %H:%M} ~ {samples[-1][0]:%H:%M}")
    print(f"   온도 {min(temps):.2f} ~ {max(temps):.2f}℃ (폭 {max(temps)-min(temps):.2f}℃)")
    print(f"   냉방 가동 표본 {n_cool}개 / 정지 {len(samples)-n_cool}개")

    print("\n== 식별")
    result = identify(samples)
    if result.model is None:
        print("   교정하지 못했습니다. 이유:")
        for r in result.reasons:
            print(f"     ! {r}")
        if result.diagnostics.get("r2") is not None:
            d = result.diagnostics
            print(f"   (참고 — 그래도 맞춰 보면 a={d['a']:.5f} b={d['b']:+.5f} "
                  f"d={d['d']:+.5f} R²={d['r2']:.3f}. 위 이유 때문에 쓰지 않습니다.)")
        print()
        print(STEP_TEST_GUIDE)
        fallback = ThermalModel()
        print(f"   지금은 가정값으로 동작합니다 — 시정수 {fallback.time_constant_min:.0f}분, "
              f"냉각률 {fallback.b:+.3f}℃/분 (calibrated=false)")
        raise SystemExit(2)

    m = result.model
    print(f"   a={m.a:.5f} /분  (시정수 {m.time_constant_min:.1f}분)")
    print(f"   b={m.b:+.5f} ℃/분  (냉방 가동 시 냉각률)")
    print(f"   d={m.d:+.5f} ℃/분  (외기·내부발열 표류)")
    print(f"   R²={m.r2:.3f}   냉방 정상상태 {m.steady_state(True):.1f}℃ / "
          f"무냉방 {m.steady_state(False):.1f}℃")
    print("\n== 예냉 리드타임")
    for t0 in (26.0, 27.0, 28.0, 29.0):
        lt = m.lead_time_minutes(t0, 24.0)
        print(f"   {t0:.1f}℃ → 24.0℃ : "
              + (f"{lt:.0f}분" if lt is not None else "도달 불가 (냉방 용량 부족)"))

    if args.dry_run:
        print("\n(--dry-run: 저장하지 않음)")
        return
    m.save(args.out)
    print(f"\n저장: {args.out}")


if __name__ == "__main__":
    main()
