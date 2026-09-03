#!/usr/bin/env python3
"""실측 센서 및 제어 이력 데이터셋 추출기 (Dataset Exporter for PINN & ML).

PostgreSQL DB로부터 실측 센서(온도, 습도, CO2)와 액추에이터 상태(펠티어 냉방, 히터 duty, 재실)를
시간축으로 동기화하여 PINN(Physics-Informed Neural Network) 학습용 CSV로 내보냅니다.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import psycopg

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from api.db import close_pool, get_conn, open_pool


def export_dataset(output_path: str = "dataset_pinn_thermal.csv", date_filter: str | None = None) -> str:
    print(f"📊 실측 데이터베이스에서 시계열 데이터 추출 중... (필터: {date_filter or '전체'})")

    open_pool()
    try:
        with get_conn() as conn, conn.cursor() as cur:
            # 1. 환경 센서 데이터 조회
            where_clause = ""
            params = []
            if date_filter:
                where_clause = "WHERE DATE(e.measured_at) = %s"
                params.append(date_filter)

            query = f"""
                SELECT
                    e.reading_id,
                    e.measured_at,
                    e.temperature,
                    e.humidity,
                    e.co2,
                    d.room_id
                FROM sensor_env e
                JOIN devices d USING (device_id)
                {where_clause}
                ORDER BY e.measured_at ASC
            """
            cur.execute(query, tuple(params))
            env_rows = cur.fetchall()

            # 2. 제어 판단 및 냉방 가동 여부 조회
            cur.execute("""
                SELECT
                    decided_at,
                    decision_type,
                    control_mode,
                    target_temp,
                    reason
                FROM control_decisions
                ORDER BY decided_at ASC
            """)
            decision_rows = cur.fetchall()
    finally:
        close_pool()

    if not env_rows:
        print("⚠️ 조건에 맞는 센서 데이터가 없습니다.")
        return ""

    df_env = pd.DataFrame(env_rows)
    df_dec = pd.DataFrame(decision_rows)

    df_env["measured_at"] = pd.to_datetime(df_env["measured_at"])
    df_env["temperature"] = df_env["temperature"].astype(float)
    df_env["humidity"] = df_env["humidity"].astype(float)
    df_env["co2"] = df_env["co2"].astype(float)

    # 30초 단위 리샘플링 및 정렬
    df_env = df_env.set_index("measured_at").resample("30s").mean().interpolate(method="time").reset_index()

    # 냉방 상태 플래그 매핑 (cooling_on: 1 if maintain/precool else 0)
    df_env["cooling_u"] = 0
    if not df_dec.empty:
        df_dec["decided_at"] = pd.to_datetime(df_dec["decided_at"])
        for _, row in df_dec.iterrows():
            if row["decision_type"] in ("maintain", "precool"):
                # 판단 시점 이후 15분간 가동 추정
                t_start = row["decided_at"]
                t_end = t_start + pd.Timedelta(minutes=15)
                mask = (df_env["measured_at"] >= t_start) & (df_env["measured_at"] <= t_end)
                df_env.loc[mask, "cooling_u"] = 1

    # 시간 미분 (dT/dt: ℃/min) 계산 (물리 방정식 타깃)
    df_env["dt_seconds"] = df_env["measured_at"].diff().dt.total_seconds().fillna(30.0)
    df_env["temp_diff"] = df_env["temperature"].diff().fillna(0.0)
    df_env["dT_dt"] = (df_env["temp_diff"] / df_env["dt_seconds"]) * 60.0  # ℃/min

    # CO2 변화율 (dC/dt: ppm/min)
    df_env["co2_diff"] = df_env["co2"].diff().fillna(0.0)
    df_env["dCO2_dt"] = (df_env["co2_diff"] / df_env["dt_seconds"]) * 60.0

    df_env.to_csv(output_path, index=False)
    print(f"✅ 추출 완료: {output_path} (총 {len(df_env):,}행, 기간: {df_env['measured_at'].min()} ~ {df_env['measured_at'].max()})")
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="dataset_pinn_thermal.csv")
    parser.add_argument("--date", default=None, help="특정 일자 (YYYY-MM-DD), 예: 2026-08-30")
    args = parser.parse_args()

    export_dataset(args.out, args.date)
