"""문 개폐 구간에서 환기량(ACH)을 식별한다.

    python -m ml.analyze_ventilation                    # 구 SQLite 기록
    python -m ml.analyze_ventilation --source postgres  # 운영 DB

문을 여닫는 것 자체가 환기량에 대한 계단 입력이므로, 따로 실험을 만들지
않고도 기록에서 Q/V 를 뽑을 수 있다 — 자료가 충분하다는 전제에서.

충분하지 않으면 값을 만들어 내지 않고, 어느 구간이 왜 못 쓰는지와 어떤
측정을 하면 되는지를 출력한다.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime

from ml.ventilation import (MEASUREMENT_PROTOCOL, Segment, compare, identify)

DEFAULT_SQLITE = "/home/thermo/thermoshift-data/thermoshift.db"


def load_sqlite(path: str):
    """(co2, pir, door, temp) 를 돌려준다."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    g = lambda dev, met: [(datetime.fromisoformat(r["timestamp"]), r["value"])
                          for r in con.execute(
        "SELECT timestamp,value FROM sensor_readings WHERE device_id=? AND metric=?"
        " ORDER BY timestamp", (dev, met))]
    out = (g("env_01", "co2"), g("occ_01", "pir"), g("occ_01", "door"),
           g("env_01", "temperature"))
    con.close()
    return out


def load_postgres(room_id: int | None):
    import psycopg
    ci = psycopg.conninfo.make_conninfo(
        host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
        user=os.getenv("DB_USER", "thermoshift"),
        password=os.getenv("DB_PASSWORD", "thermoshift1234"),
        dbname=os.getenv("DB_NAME", "thermoshift"))
    with psycopg.connect(ci) as conn, conn.cursor() as cur:
        if room_id is None:
            row = cur.execute("SELECT room_id FROM rooms WHERE name <> '미배정'"
                              " ORDER BY room_id LIMIT 1").fetchone()
            if row is None:
                return [], [], [], []
            room_id = row[0]
        co2 = [(t, float(v)) for t, v in cur.execute(
            """SELECT e.measured_at, e.co2 FROM sensor_env e
               JOIN devices d USING (device_id)
               WHERE d.room_id=%s AND e.co2 IS NOT NULL
               ORDER BY e.measured_at""", (room_id,)).fetchall()]
        pir = [(t, 1.0 if m else 0.0) for t, m in cur.execute(
            """SELECT p.measured_at, p.motion FROM sensor_pir p
               JOIN devices d USING (device_id)
               WHERE d.room_id=%s ORDER BY p.measured_at""", (room_id,)).fetchall()]
        door = [(t, 1.0 if s == "open" else 0.0) for t, s in cur.execute(
            """SELECT s.measured_at, s.door_state FROM sensor_door s
               JOIN devices d USING (device_id)
               WHERE d.room_id=%s ORDER BY s.measured_at""", (room_id,)).fetchall()]
        temp = [(t, float(v)) for t, v in cur.execute(
            """SELECT e.measured_at, e.temperature FROM sensor_env e
               JOIN devices d USING (device_id)
               WHERE d.room_id=%s AND e.temperature IS NOT NULL
               ORDER BY e.measured_at""", (room_id,)).fetchall()]
    return co2, pir, door, temp


def build_segments(co2, pir, door, temp=None, max_sec: float = 7200) -> list[Segment]:
    if not door:
        return []
    spans, state, start = [], bool(door[0][1]), door[0][0]
    for t, v in door[1:]:
        if bool(v) != state:
            spans.append((state, start, t))
            state, start = bool(v), t
    spans.append((state, start, door[-1][0]))

    segs = []
    for st, a, b in spans:
        # 아주 긴 구간은 센서가 꺼져 있던 공백이지 '닫힘' 이 아니다.
        if not (0 < (b - a).total_seconds() <= max_sec):
            continue
        samples = [(t, c) for t, c in co2 if a <= t <= b]
        pw = [bool(v) for t, v in pir if a <= t <= b]
        # 전반/후반 PIR 점유율 — 인원이 유지됐는지 보는 지표
        d1 = d2 = None
        if len(pw) >= 10:
            h = len(pw) // 2
            d1 = sum(pw[:h]) / h
            d2 = sum(pw[h:]) / (len(pw) - h)
        tw = None
        if temp:
            w = [v for t, v in temp if a <= t <= b]
            if len(w) >= 3:
                tw = max(w) - min(w)
        segs.append(Segment("open" if st else "closed", a, b, samples, d1, d2, tw))
    return segs


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", choices=["sqlite", "postgres"], default="sqlite")
    ap.add_argument("--sqlite", default=DEFAULT_SQLITE)
    ap.add_argument("--room-id", type=int, default=None)
    args = ap.parse_args()

    co2, pir, door, temp = (load_postgres(args.room_id) if args.source == "postgres"
                            else load_sqlite(args.sqlite))
    print(f"== 자료  CO2 {len(co2)}행 · PIR {len(pir)}행 · 문 {len(door)}행")

    segs = build_segments(co2, pir, door, temp)
    if not segs:
        raise SystemExit("문 개폐 구간을 찾지 못했습니다.")
    print(f"== 구간 {len(segs)}개 "
          f"(열림 {sum(1 for s in segs if s.state=='open')} / "
          f"닫힘 {sum(1 for s in segs if s.state=='closed')})\n")

    ests = [identify(s) for s in segs]
    print(f"{'상태':4} {'구간':21} {'초':>6} {'CO2폭':>6} {'PIR변화':>8} {'온도폭':>7} {'ACH':>7} {'R²':>6}  판정")
    print("-" * 88)
    for e in ests:
        s = e.segment
        ach = f"{e.ach:7.2f}" if e.ach is not None else "      —"
        r2 = f"{e.r2:6.3f}" if e.r2 is not None else "     —"
        verdict = "사용 가능" if e.k_per_min is not None else e.reasons[0][:38]
        shift = f"{s.pir_duty_shift:.0%}" if s.pir_duty_shift is not None else "—"
        tw = f"{s.temp_swing_c:.2f}" if s.temp_swing_c is not None else "—"
        print(f"{'열림' if s.state=='open' else '닫힘':4} "
              f"{s.started_at:%m-%d %H:%M}~{s.ended_at:%H:%M} {s.duration_sec:6.0f} "
              f"{s.co2_range:6.0f} {shift:>8} {tw:>7} {ach} {r2}  {verdict}")

    usable = [e for e in ests if e.k_per_min is not None]
    print(f"\n== 식별 성공 {len(usable)} / {len(ests)}")

    summary, problems = compare(ests)
    if usable:
        for st in ("open", "closed"):
            d = summary[st]
            if d["n"]:
                print(f"   {'문 열림' if st=='open' else '문 닫힘'}: "
                      f"ACH {d['ach']}  평균 {d['mean_ach']:.2f}")

    if problems:
        print("\n== 결론을 내지 못했습니다")
        for p in problems:
            print(f"  ! {p}")
        print()
        print(MEASUREMENT_PROTOCOL)
        raise SystemExit(2)

    print("\n== 결론")
    print(f"   문 닫힘 ACH {summary['closed']['mean_ach']:.2f} → "
          f"열림 ACH {summary['open']['mean_ach']:.2f} "
          f"({summary['open']['mean_ach']/summary['closed']['mean_ach']:.1f}배)")


if __name__ == "__main__":
    main()
