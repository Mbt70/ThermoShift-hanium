import argparse
import sqlite3
import time
import json
import os
from datetime import datetime, timezone

DB_PATH = "/home/thermo/thermoshift-edge/thermoshift_edge.db"
CONFIG_PATH = "/home/thermo/thermoshift-edge/config/config.yaml"

def print_status():
    if not os.path.exists(DB_PATH):
        print("Database not found.")
        return
        
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    print("ThermoShift Edge Status")
    print("-----------------------")
    
    # Mode
    mode = "UNKNOWN"
    if os.path.exists(CONFIG_PATH):
        import yaml
        with open(CONFIG_PATH, "r") as f:
            cfg = yaml.safe_load(f)
            mode = cfg.get("app", {}).get("control_mode", "UNKNOWN").upper()
    print(f"Mode                 : {mode}")

    # Latest sensors
    cur.execute("SELECT device_id, metric, value, timestamp FROM sensor_readings ORDER BY timestamp DESC LIMIT 50")
    rows = cur.fetchall()
    
    last_seen = {}
    temp = hum = co2 = None
    
    for r in rows:
        dev, metric, val, ts = r[0], r[1], r[2], r[3]
        if dev not in last_seen:
            dt = datetime.fromisoformat(ts)
            now = datetime.now(timezone.utc)
            last_seen[dev] = int((now - dt).total_seconds())
        if temp is None and metric == "temperature": temp = val
        if hum is None and metric == "humidity": hum = val
        if co2 is None and metric == "co2": co2 = val

    for dev, age in last_seen.items():
        print(f"{dev.upper()} last seen      : {age} sec ago")
        
    print()
    if temp is not None: print(f"Temperature          : {temp} C")
    if hum is not None: print(f"Humidity             : {hum} %")
    if co2 is not None: print(f"CO2                  : {co2} ppm")
    print()
    
    cur.execute("SELECT p_empty, p_transition, p_occupied, state FROM occupancy_estimates ORDER BY timestamp DESC LIMIT 1")
    occ_row = cur.fetchone()
    if occ_row:
        print(f"P(Empty)             : {occ_row[0]:.2f}")
        print(f"P(Transition)        : {occ_row[1]:.2f}")
        print(f"P(Occupied)          : {occ_row[2]:.2f}")
        print(f"Occupancy state      : {occ_row[3]}")
    
    print()
    cur.execute("SELECT proposed_action, executed, reason_codes_json FROM control_decisions ORDER BY timestamp DESC LIMIT 1")
    ctrl_row = cur.fetchone()
    if ctrl_row:
        print(f"Proposed action      : {ctrl_row[0]}")
        print(f"Executed             : {'YES' if ctrl_row[1] else 'NO'}")
        reasons = json.loads(ctrl_row[2]) if ctrl_row[2] else []
        if reasons:
            print("Reason               :")
            for r in reasons:
                print(f"- {r}")
                
def main():
    parser = argparse.ArgumentParser(description="ThermoShift Edge CLI")
    subparsers = parser.add_subparsers(dest="command")
    
    subparsers.add_parser("status")
    
    tail_parser = subparsers.add_parser("tail")
    tail_parser.add_argument("--lines", type=int, default=10)
    
    mode_parser = subparsers.add_parser("set-mode")
    mode_parser.add_argument("mode", choices=["shadow", "active", "manual_lockout", "failsafe"])
    
    off_parser = subparsers.add_parser("force-off")
    off_parser.add_argument("--execute", action="store_true")
    
    subparsers.add_parser("ir-learn")
    subparsers.add_parser("replay")
    
    args = parser.parse_args()
    
    if args.command == "status":
        print_status()
    elif args.command == "set-mode":
        import yaml
        if not os.path.exists(CONFIG_PATH):
            print("Config not found.")
            return
        with open(CONFIG_PATH, "r") as f:
            cfg = yaml.safe_load(f)
            
        if args.mode == "active":
            print("Warning: ensure IR codes are registered before active mode.")
            # check ir codes
            codes = cfg.get("ir", {}).get("codes", {})
            if "POWER_OFF_RAW_HASH_PLACEHOLDER" in codes.values():
                print("Error: IR codes still have placeholders. Active mode denied.")
                return
                
        cfg["app"]["control_mode"] = args.mode
        with open(CONFIG_PATH, "w") as f:
            yaml.safe_dump(cfg, f)
        print(f"Mode set to {args.mode}. Restart service to apply.")
    else:
        print(f"Command {args.command} not fully implemented in this MVP.")

if __name__ == "__main__":
    main()
