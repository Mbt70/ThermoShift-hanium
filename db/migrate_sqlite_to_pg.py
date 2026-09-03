"""구 SQLite 통합 DB 를 PostgreSQL v2.3 스키마로 이관한다.

  python db/migrate_sqlite_to_pg.py [--sqlite PATH] [--reset]

왜 단순 복사가 아닌가
---------------------
구 스키마는 게이트웨이가 급하게 만든 평면 구조였다. 센서값이 metric/value
한 표(sensor_readings)에 다 들어 있고, 식별자는 전부 TEXT UUID 였다. 새
스키마(db/001~008)는 센서를 종류별 표로 나누고(sensor_env/pir/door),
식별자를 bigint identity 로 쓰며, ENUM 과 CHECK 로 값을 강제한다. 그래서
이관은 피벗 + 식별자 재발급 + 값 매핑이 전부 필요하다.

이관 대상 (2026-07-10 ~ 08-25 실측):
  sensor_readings 39,313  ->  sensor_env / sensor_pir / sensor_door
  occupancy_estimates 4,103, control_decisions 4,103, 그 외 마스터·이벤트

여러 번 돌려도 안전하다. --reset 은 대상 표를 비우고 다시 넣는다.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from bisect import bisect_right
from datetime import datetime, timedelta, time as dtime
from pathlib import Path

import psycopg

DEFAULT_SQLITE = "/home/thermo/thermoshift-data/thermoshift.db"

# 배정 전 노드가 머무는 공간. 새 스키마의 devices.room_id 는 NOT NULL 이라
# 구 DB 에서 room_id 가 비어 있던 노드도 어딘가에는 속해야 한다.
# gateway/app/storage.py 의 UNASSIGNED_ROOM_NAME 과 같은 이름을 쓴다.
UNASSIGNED_ROOM_NAME = "미배정"

# 옮길 수 없는 비밀번호 자리에 넣는 표식. users.password_hash 가 NOT NULL 이라
# 무언가는 들어가야 하는데, bcrypt 해시가 아니면 대조가 항상 실패한다.
# (auth.py 의 _password_matches 가 예외를 삼키고 False 를 돌려준다.)
PASSWORD_RESET_REQUIRED = "!password-reset-required"

# 구 rooms.control_mode / control_commands.method  ->  control_mode ENUM
ROOM_MODE = {"rule": "rule", "manual": "manual", "predict": "mpc",
             "monitoring": "monitoring", "mpc": "mpc"}

# 구 control_decisions.control_mode 는 *게이트웨이 동작 모드*였지 공간의
# 제어 모드가 아니었다. shadow 는 판단만 하고 송신하지 않는 상태이므로
# 'monitoring' 에, active 는 규칙 제어이므로 'rule' 에 대응한다.
GATEWAY_MODE = {"active": "rule", "shadow": "monitoring",
                "manual_lockout": "manual", "failsafe": "monitoring"}

# 구 alerts.type / system_events.event_type  ->  event_category ENUM
EVENT_CATEGORY = {
    "sensor_offline": "sensor_error", "humidity_abnormal": "sensor_error",
    "co2_high": "co2_exceed", "CO2_ALERT": "co2_exceed",
    "temperature_abnormal": "temp_deviation",
    "control_failed": "control_fail", "network_error": "network",
    "door_open": "system", "power_abnormal": "energy",
}

WEEKDAY = {"mon": 1, "tue": 2, "wed": 3, "thu": 4,
           "fri": 5, "sat": 6, "sun": 7}

# 대상 표 — --reset 이 비우는 순서(자식부터)이자 이관 순서의 역순.
TABLES = [
    "inquiries", "simulations", "operation_sessions", "event_logs",
    "hvac_commands", "control_decisions", "occupancy_estimates", "ir_events",
    "power_readings", "sensor_door", "sensor_pir", "sensor_env",
    "schedules", "devices", "rooms", "users",
]


def ts(value):
    """구 DB 의 ISO8601 문자열을 datetime 으로. 빈 값은 None."""
    if not value:
        return None
    return datetime.fromisoformat(value)


def load_env_file(path="/etc/thermoshift.env"):
    """systemd 가 읽는 환경 파일을 이 프로세스에도 적용한다.

    부트스트랩이 만든 DB 비밀번호가 여기에만 있어서, 사람이 직접 돌릴 때도
    같은 값을 쓰게 하려는 것이다. 이미 환경변수가 있으면 건드리지 않는다.
    """
    p = Path(path)
    if not p.is_file():
        return
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    except PermissionError:
        pass


def conninfo():
    return psycopg.conninfo.make_conninfo(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        user=os.getenv("DB_USER", "thermoshift"),
        password=os.environ["DB_PASSWORD"],
        dbname=os.getenv("DB_NAME", "thermoshift"),
    )


def device_uid(code: str) -> str:
    """devices.device_uid 는 CHECK (device_uid ~ '^[A-Z0-9]+$') 를 받는다.

    구 DB 의 device id 는 'env_01' 처럼 소문자·밑줄이라 그대로는 들어가지
    않는다. 실물 MAC 주소를 모르므로 코드에서 결정적으로 만들어 둔다.
    노드가 실제로 붙으면 그때 MAC 으로 갱신하면 된다.
    """
    uid = "".join(ch for ch in code.upper() if ch.isalnum())
    return uid or "UNKNOWN"


# =====================================================================
def migrate(sq: sqlite3.Connection, pg: psycopg.Connection, reset: bool):
    sq.row_factory = sqlite3.Row
    cur = pg.cursor()
    log = lambda *a: print("   ", *a)

    if reset:
        cur.execute("TRUNCATE %s RESTART IDENTITY CASCADE"
                    % ", ".join(TABLES))
        print("== 대상 표 비움 (--reset)")

    if cur.execute("SELECT count(*) FROM users").fetchone()[0]:
        print("== 이미 데이터가 있습니다. 다시 넣으려면 --reset 을 쓰세요.")
        return

    # ---------------- users ----------------
    print("== users")
    user_id = {}
    needs_reset = []
    for r in sq.execute("SELECT * FROM users ORDER BY created_at"):
        stored = r["password_hash"] or ""
        # 구 게이트웨이는 pbkdf2_sha256$... 로 저장했지만 새 api 는 bcrypt 를
        # 쓴다(api/routers/auth.py). 형식이 다른 해시를 그대로 옮기면 그
        # 계정으로는 영원히 로그인할 수 없다. 옮기는 대신 절대 일치하지
        # 않는 표식을 넣고, 누구를 재설정해야 하는지 알려 준다.
        if not stored.startswith(("$2a$", "$2b$", "$2y$")):
            stored = PASSWORD_RESET_REQUIRED
            needs_reset.append(r["email"])
        uid = cur.execute(
            """INSERT INTO users (name, email, password_hash, created_at)
               VALUES (%s,%s,%s,%s) RETURNING user_id""",
            (r["name"], r["email"], stored, ts(r["created_at"])),
        ).fetchone()[0]
        user_id[r["email"]] = uid
    log(f"{len(user_id)}명")
    if needs_reset:
        log("! 비밀번호를 옮기지 못했습니다 (bcrypt 형식이 아님). "
            "아래 계정은 재설정해야 로그인됩니다:")
        for e in needs_reset:
            log(f"    {e}")
        log("  재설정:  curl -X PATCH localhost:8000/auth/<user_id>/password "
            "-H 'Content-Type: application/json' -d '{\"password\":\"...\"}'")
    if not user_id:
        sys.exit("users 가 비어 있습니다. 이관할 것이 없습니다.")
    default_owner = next(iter(user_id.values()))

    # ---------------- rooms ----------------
    print("== rooms")
    room_id = {}
    for r in sq.execute("SELECT * FROM rooms ORDER BY created_at"):
        owner = user_id.get(r["owner_email"], default_owner)
        rid = cur.execute(
            """INSERT INTO rooms (owner_user_id, name, location, control_mode,
                                  floor_plan_url, target_temp, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING room_id""",
            (owner, r["name"], r["location"],
             ROOM_MODE.get(r["control_mode"], "monitoring"),
             r["floor_plan_name"], r["target_temperature"],
             ts(r["created_at"])),
        ).fetchone()[0]
        room_id[r["id"]] = rid
    unassigned = cur.execute(
        """INSERT INTO rooms (owner_user_id, name, location, control_mode)
           VALUES (%s,%s,%s,'monitoring') RETURNING room_id""",
        (default_owner, UNASSIGNED_ROOM_NAME, "배정 전 노드"),
    ).fetchone()[0]
    log(f"{len(room_id)}개 + '{UNASSIGNED_ROOM_NAME}'")

    # ---------------- devices ----------------
    print("== devices")
    device_id = {}
    for r in sq.execute("SELECT * FROM devices ORDER BY id"):
        rid = room_id.get(r["room_id"], unassigned)
        # 지금은 어느 노드도 붙어 있지 않다. last_seen 이 있으면 과거에
        # 붙었다가 끊긴 것이므로 offline, 한 번도 없으면 unknown 이다.
        comm = "offline" if r["last_seen"] else "unknown"
        did = cur.execute(
            """INSERT INTO devices (room_id, device_code, device_uid,
                                    device_type, install_location,
                                    comm_status, is_enabled, last_seen_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING device_id""",
            (rid, r["id"], device_uid(r["id"]), r["type"], r["location"],
             comm, bool(r["enabled"]), ts(r["last_seen"])),
        ).fetchone()[0]
        device_id[r["id"]] = did
    log(f"{len(device_id)}대")

    # 센서 행의 room 을 알아내려면 장치가 어느 공간인지 알아야 한다.
    dev_room = {code: cur.execute(
        "SELECT room_id FROM devices WHERE device_id=%s", (did,)
    ).fetchone()[0] for code, did in device_id.items()}

    # ---------------- schedules ----------------
    print("== schedules")
    sched_id = {}
    for r in sq.execute("SELECT * FROM schedules"):
        rid = room_id.get(r["room_id"])
        if rid is None:
            continue
        days = []
        if r["repeat_enabled"]:
            try:
                days = sorted({WEEKDAY[d] for d in json.loads(r["repeat_days"])
                               if d in WEEKDAY})
            except (json.JSONDecodeError, TypeError):
                days = []
        valid_from = datetime.strptime(r["date"], "%Y-%m-%d").date()
        # ck_sched_no_infinite: 반복 일정은 종료일이 있어야 한다. 구 스키마엔
        # 종료일 개념이 없었으므로 실증 기간을 감안해 180일로 채운다.
        valid_until = valid_from + timedelta(days=180) if days else None
        hhmm = lambda s: dtime(*map(int, s.split(":")[:2]))
        sid = cur.execute(
            """INSERT INTO schedules (room_id, created_by, title, valid_from,
                   valid_until, start_time, end_time, repeat_days,
                   target_temp, precooling_min, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING schedule_id""",
            (rid, default_owner, r["title"], valid_from, valid_until,
             hhmm(r["start_time"]), hhmm(r["end_time"]), days,
             r["target_temperature"],
             r["precool_minutes_before"] if r["precool_enabled"] else 0,
             ts(r["created_at"])),
        ).fetchone()[0]
        sched_id[r["id"]] = sid
    log(f"{len(sched_id)}건")

    # ---------------- sensor_env (피벗) ----------------
    print("== sensor_env  (temperature/humidity/co2 를 한 행으로 피벗)")
    rows = sq.execute(
        """SELECT device_id, timestamp,
                  MAX(CASE WHEN metric='temperature' THEN value END) t,
                  MAX(CASE WHEN metric='humidity'    THEN value END) h,
                  MAX(CASE WHEN metric='co2'         THEN value END) c
           FROM sensor_readings
           WHERE metric IN ('temperature','humidity','co2')
           GROUP BY device_id, timestamp
           ORDER BY timestamp"""
    ).fetchall()
    env = []
    for r in rows:
        did = device_id.get(r["device_id"])
        if did is None or (r["t"] is None and r["h"] is None and r["c"] is None):
            continue
        m = ts(r["timestamp"])
        # 구 DB 에는 도착 시각이 없다. 측정 시각을 그대로 쓰고, 이 값이
        # 실제 수집 지연을 뜻하지 않는다는 점은 문서에 남긴다.
        env.append((did,
                    None if r["t"] is None else round(r["t"], 1),
                    None if r["h"] is None else round(r["h"], 1),
                    None if r["c"] is None else int(round(r["c"])),
                    m, m))
    cur.executemany(
        """INSERT INTO sensor_env (device_id, temperature, humidity, co2,
                                   measured_at, received_at)
           VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""", env)
    log(f"{len(env)}행")

    # ---------------- sensor_pir / sensor_door ----------------
    print("== sensor_pir / sensor_door")
    pir, door = [], []
    for r in sq.execute(
        """SELECT device_id, timestamp, metric, value FROM sensor_readings
           WHERE metric IN ('pir','door') ORDER BY timestamp"""
    ):
        did = device_id.get(r["device_id"])
        if did is None:
            continue
        m = ts(r["timestamp"])
        if r["metric"] == "pir":
            pir.append((did, bool(r["value"]), m, m))
        else:
            door.append((did, "open" if r["value"] else "closed", m, m))
    cur.executemany(
        """INSERT INTO sensor_pir (device_id, motion, measured_at, received_at)
           VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""", pir)
    cur.executemany(
        """INSERT INTO sensor_door (device_id, door_state, measured_at, received_at)
           VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""", door)
    log(f"pir {len(pir)}행 / door {len(door)}행")

    # ---------------- occupancy_estimates ----------------
    print("== occupancy_estimates")
    est_keys, est_rows = [], []
    for r in sq.execute("SELECT * FROM occupancy_estimates ORDER BY timestamp"):
        rid = room_id.get(r["room_id"])
        if rid is None:
            continue
        try:
            reasons = json.loads(r["reasons_json"] or "[]")
        except json.JSONDecodeError:
            reasons = []
        est_rows.append((rid, (r["state"] or "unknown").lower(),
                         round(r["p_occupied"], 3), "; ".join(reasons)[:500],
                         ts(r["timestamp"])))
    cur.executemany(
        """INSERT INTO occupancy_estimates (room_id, occupancy_state,
               probability, evidence_summary, estimated_at)
           VALUES (%s,%s,%s,%s,%s)
           ON CONFLICT (room_id, estimated_at) DO NOTHING""",
        est_rows)

    # 제어 판단을 추정에 연결하려면 (공간, 시각) -> id 색인이 필요하다.
    #
    # executemany 에 RETURNING 을 붙여 한 번에 받을 수도 있지만, psycopg3 의
    # executemany 는 값을 돌려주지 않고 커서에 결과집합을 쌓아 두며
    # ON CONFLICT DO NOTHING 으로 걸러진 행은 빈 결과집합이 되어 처리가
    # 지저분해진다. 넣고 나서 한 번 읽는 편이 단순하고 확실하다.
    by_room: dict[int, list] = {}
    for eid, rid, at in cur.execute(
        """SELECT estimate_id, room_id, estimated_at
           FROM occupancy_estimates ORDER BY room_id, estimated_at""").fetchall():
        by_room.setdefault(rid, []).append((at, eid))
    log(f"{sum(len(v) for v in by_room.values())}건")

    def nearest_estimate(rid, at):
        """판단 시각 직전의 추정을 찾는다.

        구 스키마에는 둘을 잇는 열이 아예 없었다. 다만 게이트웨이가 추정을
        먼저 쓰고 곧바로 판단을 쓰므로(수 ms 차) 직전 추정이 곧 그 판단의
        근거다. 5초를 넘으면 다른 주기의 것이므로 연결하지 않는다.
        """
        lst = by_room.get(rid)
        if not lst:
            return None
        i = bisect_right(lst, (at, 1 << 62)) - 1
        if i < 0:
            return None
        at0, eid = lst[i]
        return eid if (at - at0).total_seconds() <= 5 else None

    # ---------------- control_decisions ----------------
    print("== control_decisions")
    dec_rows = []
    for r in sq.execute("SELECT * FROM control_decisions ORDER BY timestamp"):
        rid = room_id.get(r["room_id"])
        if rid is None:
            continue
        at = ts(r["timestamp"])
        action = r["proposed_action"] or "POWER_OFF"
        # 구 게이트웨이는 켜기/끄기 둘뿐이었다. precool·setback·ventilate 는
        # 판단 유형으로 남기지 않았으므로 있는 그대로만 옮긴다.
        if action == "POWER_OFF":
            dtype, target = "off", None
        else:
            dtype = "maintain"
            parts = action.split("_")
            target = float(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
        try:
            reasons = json.loads(r["reason_codes_json"] or "[]")
        except json.JSONDecodeError:
            reasons = []
        dec_rows.append((rid, nearest_estimate(rid, at),
                         GATEWAY_MODE.get(r["control_mode"], "monitoring"),
                         dtype, target,
                         f"{action} | " + ", ".join(reasons), at))
    cur.executemany(
        """INSERT INTO control_decisions (room_id, estimate_id, control_mode,
               decision_type, target_temp, reason, decided_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""", dec_rows)
    linked = sum(1 for d in dec_rows if d[1] is not None)
    log(f"{len(dec_rows)}건 (추정 연결 {linked}건)")

    # ---------------- hvac_commands ----------------
    print("== hvac_commands")
    n_cmd = 0
    for r in sq.execute("SELECT * FROM control_commands ORDER BY created_at"):
        rid = room_id.get(r["room_id"])
        if rid is None:
            continue
        ir_dev = cur.execute(
            "SELECT device_id FROM devices WHERE room_id=%s AND device_type='ir'"
            " ORDER BY device_id LIMIT 1", (rid,)).fetchone()
        if ir_dev is None:
            continue
        action = r["action"] or "POWER_OFF"
        if action == "POWER_OFF":
            ctype, target = "power_off", None
        else:
            ctype = "set_temp"
            parts = action.split("_")
            target = float(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
        cur.execute(
            """INSERT INTO hvac_commands (room_id, device_id, issued_by,
                   command_type, control_mode, target_temp, command_status,
                   payload, issued_at, result_message)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (rid, ir_dev[0], user_id.get(r["issued_by"]), ctype,
             ROOM_MODE.get(r["method"], "manual"), target,
             r["status"] or "pending", r["payload_json"],
             ts(r["created_at"]), r["error_code"]))
        n_cmd += 1
    log(f"{n_cmd}건")

    # ---------------- ir_events ----------------
    print("== ir_events")
    ir_rows = [(room_id.get(r["room_id"]), r["direction"] or "tx",
                r["protocol"] or "unknown", r["code_hash"] or "",
                r["source"] or "unknown", r["raw_payload"], ts(r["timestamp"]))
               for r in sq.execute("SELECT * FROM ir_events ORDER BY timestamp")]
    cur.executemany(
        """INSERT INTO ir_events (room_id, direction, protocol, code_hash,
               source, raw_payload, occurred_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""", ir_rows)
    log(f"{len(ir_rows)}건")

    # ---------------- event_logs (alerts + system_events) ----------------
    print("== event_logs")
    ev = []
    for r in sq.execute("SELECT * FROM alerts ORDER BY created_at"):
        ev.append((room_id.get(r["room_id"]), device_id.get(r["device_id"]),
                   EVENT_CATEGORY.get(r["type"], "system"), r["severity"],
                   "resolved" if r["status"] == "resolved" else "open",
                   f"{r['title']}: {r['message']}" if r["message"] else r["title"],
                   ts(r["created_at"]), ts(r["read_at"]),
                   ts(r["read_at"]) if r["status"] == "resolved" else None))
    for r in sq.execute("SELECT * FROM system_events ORDER BY timestamp"):
        ev.append((room_id.get(r["room_id"]), None,
                   EVENT_CATEGORY.get(r["event_type"], "system"),
                   (r["severity"] or "info").lower(), "open",
                   (r["message"] or "")[:500], ts(r["timestamp"]), None, None))
    cur.executemany(
        """INSERT INTO event_logs (room_id, device_id, event_category,
               event_severity, status, message, occurred_at, read_at, resolved_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""", ev)
    log(f"{len(ev)}건")

    # ---------------- operation_sessions (복원) ----------------
    print("== operation_sessions  (게이트웨이 모드 전환에서 복원)")
    # 구 DB 에는 실증 구간 표가 없었다. 그런데 control_decisions.control_mode
    # 가 shadow(판단만 하고 송신 안 함) 와 active(실제 제어) 를 구분하고
    # 있었다. shadow 구간이 곧 baseline, active 구간이 곧 rule 이다.
    # KPI 비교의 근거를 만들어내지 않고 실제 기록에서 되살리는 것이다.
    n_sess = 0
    for rid in set(room_id.values()):
        runs, prev = [], None
        for at, mode in cur.execute(
            """SELECT decided_at, control_mode FROM control_decisions
               WHERE room_id=%s ORDER BY decided_at""", (rid,)).fetchall():
            m = "baseline" if mode == "monitoring" else (
                "rule" if mode == "rule" else None)
            if m is None:
                continue
            # 30분 넘게 끊기면 다른 실증 구간으로 본다(파이 재부팅 등).
            if prev and (m != prev[1] or (at - prev[0]).total_seconds() > 1800):
                runs.append([prev[2], prev[0], prev[1]])
                prev = (at, m, at)
            elif prev:
                prev = (at, prev[1], prev[2])
            else:
                prev = (at, m, at)
        if prev:
            runs.append([prev[2], prev[0], prev[1]])
        for started, ended, mode in runs:
            # 한두 번의 판단만 있는 구간은 실증 구간이라 부를 수 없다.
            if (ended - started).total_seconds() < 300:
                continue
            cur.execute(
                """INSERT INTO operation_sessions (room_id, mode, started_at,
                       ended_at, description)
                   VALUES (%s,%s,%s,%s,%s)""",
                (rid, mode, started, ended,
                 "구 게이트웨이 기록에서 복원 (shadow=baseline, active=rule)"))
            n_sess += 1
    log(f"{n_sess}구간")

    pg.commit()
    print("\n이관 완료.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sqlite", default=DEFAULT_SQLITE)
    ap.add_argument("--reset", action="store_true",
                    help="대상 표를 비우고 다시 넣는다")
    args = ap.parse_args()

    if not Path(args.sqlite).is_file():
        sys.exit(f"SQLite 파일이 없습니다: {args.sqlite}")

    load_env_file()
    # 읽기 전용으로 연다. 이관 도중 원본을 건드릴 이유가 없다.
    sq = sqlite3.connect(f"file:{args.sqlite}?mode=ro", uri=True)
    with psycopg.connect(conninfo()) as pg:
        migrate(sq, pg, args.reset)
    sq.close()


if __name__ == "__main__":
    main()
