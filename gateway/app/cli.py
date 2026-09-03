"""게이트웨이 운영용 CLI.

    python -m app.cli status            # 현재 센서·재실·제어 상태
    python -m app.cli set-mode active   # 제어 모드 변경 (재시작 필요)
    python -m app.cli force-off --execute
    python -m app.cli experiment start calib   # 45분 교정 가진 실험
    python -m app.cli experiment status
    python -m app.cli experiment stop

접속 정보는 storage 와 같은 환경변수(DB_HOST 등)를 쓴다.
"""

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

CONFIG_PATH = str(Path(__file__).resolve().parents[1] / "config" / "config.yaml")


def _age_text(moment) -> str:
    if moment is None:
        return "-"
    delta = int((datetime.now(timezone.utc) - moment).total_seconds())
    return f"{delta} sec ago"


def print_status():
    # storage 를 그대로 쓰면 커넥션 풀 설정을 한 곳에서만 관리할 수 있다.
    from app.storage import get_storage

    storage = get_storage()
    with storage._pool.connection() as conn, conn.cursor() as cur:
        print("ThermoShift Gateway Status")
        print("--------------------------")

        mode = "UNKNOWN"
        if os.path.exists(CONFIG_PATH):
            import yaml

            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            mode = cfg.get("app", {}).get("control_mode", "UNKNOWN").upper()
        print(f"Mode                 : {mode}")

        cur.execute(
            "SELECT device_code, device_type, comm_status, last_seen_at"
            " FROM devices ORDER BY device_code"
        )
        for row in cur.fetchall():
            print(
                f"{row['device_code'].upper():<8} ({row['device_type']:<4})"
                f" {row['comm_status']:<8} last seen {_age_text(row['last_seen_at'])}"
            )
        print()

        cur.execute(
            "SELECT temperature, humidity, co2, measured_at FROM sensor_env"
            " ORDER BY measured_at DESC LIMIT 1"
        )
        env = cur.fetchone()
        if env:
            if env["temperature"] is not None:
                print(f"Temperature          : {env['temperature']} C")
            if env["humidity"] is not None:
                print(f"Humidity             : {env['humidity']} %")
            if env["co2"] is not None:
                print(f"CO2                  : {env['co2']} ppm")
            print(f"Measured at          : {env['measured_at']}")
        print()

        cur.execute(
            "SELECT occupancy_state, probability, evidence_summary FROM occupancy_estimates"
            " ORDER BY estimated_at DESC LIMIT 1"
        )
        occ = cur.fetchone()
        if occ:
            print(f"Occupancy state      : {occ['occupancy_state']}")
            print(f"Probability          : {occ['probability']}")
            print(f"Evidence             : {occ['evidence_summary']}")
        print()

        cur.execute(
            "SELECT decision_type, target_temp, reason, decided_at FROM control_decisions"
            " ORDER BY decided_at DESC LIMIT 1"
        )
        dec = cur.fetchone()
        if dec:
            print(f"Decision             : {dec['decision_type']}")
            if dec["target_temp"] is not None:
                print(f"Target temp          : {dec['target_temp']} C")
            print(f"Reason               : {dec['reason']}")
            print(f"Decided at           : {dec['decided_at']}")

        cur.execute(
            "SELECT count(*) AS n FROM hvac_commands WHERE command_status = 'pending'"
        )
        pending = cur.fetchone()["n"]
        if pending:
            print()
            print(f"Pending commands     : {pending}")


def set_mode(mode: str):
    import yaml

    if not os.path.exists(CONFIG_PATH):
        print(f"Config not found: {CONFIG_PATH}")
        return
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    if mode == "active":
        # 실장비 확인: IR 코드가 자리표시자면 에어컨은 아무것도 쏘지 않는다.
        codes = cfg.get("ir", {}).get("codes", {})
        if any("PLACEHOLDER" in str(v) for v in codes.values()):
            print("Error: IR codes still have placeholders. Active mode denied.")
            print("       Learn the remote codes first (docs/deployment.md).")
            return

    cfg.setdefault("app", {})["control_mode"] = mode
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    print(f"Mode set to {mode}. Restart the service to apply.")


def force_off(execute: bool):
    """냉방을 강제로 끈다. --execute 없이는 무엇을 할지 보여주기만 한다."""
    from app.config import get_config

    config = get_config()
    topic = config.ir.cooling_topic
    if not execute:
        print(f"[dry-run] would publish OFF to {topic}")
        print("          add --execute to actually send")
        return

    import paho.mqtt.publish as publish

    publish.single(topic, "OFF", hostname=config.mqtt.host, port=config.mqtt.port)
    print(f"Published OFF to {topic}")


PLANS = {
    "calib": ("compact_calibration_plan", "45분 교정 — c(히터 감도)와 d(표류) 확정"),
    "prbs": ("prbs_plan", "PRBS 5.2시간 — 서너 시간을 낼 수 있을 때만"),
}


def experiment_start(plan_key: str, note=None):
    """가진 실험을 연다.

    켜기 전에 확인할 것 세 가지는 config.example.yaml 의 heater 절에 있다.
    특히 교반팬이 안 돌면 단일 존 가정이 깨져서, 결과가 '잘 맞는 것처럼
    보이는 무의미한 숫자' 가 된다.
    """
    from datetime import timedelta

    from app import excitation
    from app.config import get_config
    from app.storage import get_storage

    builder_name, _ = PLANS[plan_key]
    plan = getattr(excitation, builder_name)()

    config = get_config()
    if not config.heater.enabled:
        print("heater.enabled 가 false 입니다. config.yaml 에서 켜고 게이트웨이를")
        print("다시 띄운 뒤 실행하세요 — 지금 시작하면 duty 0 만 기록됩니다.")
        return

    warnings = excitation.check_prbs_design(
        excitation.DEFAULT_BIT_SEC, excitation.DEFAULT_N_BITS, tau_min=70.0,
    ) if plan_key == "prbs" else []
    for warning in warnings:
        print(f"  경고: {warning}")

    storage = get_storage()
    room_id = storage.resolve_room_id()
    if room_id is None:
        print("담당 공간을 찾지 못했습니다.")
        return

    now = datetime.now(timezone.utc)
    run_id = storage.start_experiment(
        room_id, plan.name, plan.to_dict(), now,
        now + timedelta(seconds=plan.total_sec), note,
    )
    if run_id is None:
        print("이미 진행 중인 실험이 있습니다. 먼저 stop 하세요.")
        return

    print(f"실험 {run_id} 시작: {plan.summary()}")
    print(f"  {plan.description}")
    print(f"  끝나는 시각: {(now + timedelta(seconds=plan.total_sec)).astimezone()}")
    print("  구간:")
    cursor = 0.0
    for duty, duration in plan.segments:
        print(f"    +{cursor/60:5.0f}분  duty {duty:3d}%  ({duration/60:.0f}분)")
        cursor += duration


def experiment_status():
    from app.storage import get_storage

    storage = get_storage()
    room_id = storage.resolve_room_id()
    run = storage.fetch_active_experiment(room_id)
    if run is None:
        print("진행 중인 실험이 없습니다.")
    else:
        elapsed = (datetime.now(timezone.utc) - run["started_at"]).total_seconds()
        print(f"실험 {run['run_id']} ({run['plan_name']}) 진행 중")
        print(f"  경과 {elapsed/60:.1f}분 / 총 "
              f"{(run['ends_at'] - run['started_at']).total_seconds()/60:.0f}분")

    with storage._pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT recorded_at, requested_duty, applied_duty, occupants_equiv,"
            "       blocked_reason"
            " FROM heater_log ORDER BY recorded_at DESC LIMIT 5"
        )
        rows = cur.fetchall()
    if rows:
        print("  최근 히터 이력:")
        for r in rows:
            blocked = f"  차단: {r['blocked_reason']}" if r["blocked_reason"] else ""
            print(f"    {r['recorded_at'].astimezone():%H:%M:%S}  "
                  f"지령 {r['requested_duty']:3d}%  실제 {r['applied_duty']:3d}%  "
                  f"({r['occupants_equiv']}명 상당){blocked}")


def experiment_stop():
    from app.storage import get_storage

    storage = get_storage()
    room_id = storage.resolve_room_id()
    run = storage.fetch_active_experiment(room_id)
    if run is None:
        print("진행 중인 실험이 없습니다.")
        return
    storage.stop_experiment(run["run_id"], datetime.now(timezone.utc))
    print(f"실험 {run['run_id']} 중단했습니다. 다음 주기에 히터가 꺼집니다.")


def main():
    parser = argparse.ArgumentParser(description="ThermoShift Gateway CLI")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status")

    mode_parser = subparsers.add_parser("set-mode")
    mode_parser.add_argument(
        "mode", choices=["shadow", "active", "manual_lockout", "failsafe"]
    )

    off_parser = subparsers.add_parser("force-off")
    off_parser.add_argument("--execute", action="store_true")

    exp_parser = subparsers.add_parser("experiment", help="가진 실험 제어")
    exp_sub = exp_parser.add_subparsers(dest="exp_command")
    start_parser = exp_sub.add_parser("start")
    start_parser.add_argument("plan", choices=sorted(PLANS))
    start_parser.add_argument("--note", default=None)
    exp_sub.add_parser("status")
    exp_sub.add_parser("stop")

    args = parser.parse_args()

    if args.command == "status":
        print_status()
    elif args.command == "set-mode":
        set_mode(args.mode)
    elif args.command == "force-off":
        force_off(args.execute)
    elif args.command == "experiment":
        if args.exp_command == "start":
            experiment_start(args.plan, args.note)
        elif args.exp_command == "status":
            experiment_status()
        elif args.exp_command == "stop":
            experiment_stop()
        else:
            exp_parser.print_help()
    else:
        parser.print_help()

    # 커넥션 풀을 명시적으로 닫는다. 안 닫으면 psycopg 가 종료 때
    # "couldn't stop thread pool-1-worker-0" 경고를 네 줄씩 뱉는데,
    # 시연 중에 이런 소음이 나면 진짜 오류와 구분이 안 된다.
    try:
        from app.storage import get_storage
        get_storage().close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
