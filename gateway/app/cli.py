"""게이트웨이 운영용 CLI.

    python -m app.cli status            # 현재 센서·재실·제어 상태
    python -m app.cli set-mode active   # 제어 모드 변경 (재시작 필요)
    python -m app.cli force-off --execute

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

    args = parser.parse_args()

    if args.command == "status":
        print_status()
    elif args.command == "set-mode":
        set_mode(args.mode)
    elif args.command == "force-off":
        force_off(args.execute)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
