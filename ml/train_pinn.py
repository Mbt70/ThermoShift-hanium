#!/usr/bin/env python3
"""물리 잔차로 정규화한 열 변화율 신경망 실험 코드.

신경망이 예측한 dT/dt가 1차 RC 모델과 크게 어긋나지 않도록 잔차 항을
추가한다. 엄밀한 의미의 PINN 전체 구현이나 일반화 성능 보장을 뜻하지
않으며, RC 회귀 대비 성능은 별도 hold-out 실험으로 검증해야 한다.

손실 함수 (Loss Formulation):
---------------------------
L_total = L_data + lambda_phys * L_physics

  - L_data = MSE(T_pred, T_true)
  - L_physics = Mean( | dT/dt_pred - ( -a * T + d + b * u_cool ) |^2 )
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from ml.training_quality import assess_training_frame  # noqa: E402


def train_pinn_numpy(
    df: pd.DataFrame,
    epochs: int = 1500,
    lr: float = 0.005,
    lambda_phys: float = 0.4,
    pipeline_smoke_test: bool = False,
):
    """PyTorch 미설치 환경에서도 즉시 훈련 가능한 물리 기반 최적화 엔진."""
    quality = assess_training_frame(df)
    if not quality.eligible and not pipeline_smoke_test:
        details = "\n".join(f"- {reason}" for reason in quality.reasons)
        raise ValueError(f"학습 품질 게이트를 통과하지 못했습니다:\n{details}")
    if pipeline_smoke_test and not quality.eligible:
        print("⚠️ PIPELINE_SMOKE_TEST: 아래 품질 문제를 무시하지만 결과를 운영에 저장하지 않습니다.")
        for reason in quality.reasons:
            print(f"  - {reason}")
    print("🧠 [PINN] 실측 시계열 데이터 기반 물리-신경망 하이브리드 훈련 시작...")

    # 유효 데이터 필터링
    df = df.dropna(subset=["temperature", "dT_dt"]).copy()
    if len(df) < 2:
        raise ValueError("학습 가능한 온도 변화율 표본이 2개 이상 필요합니다")
    T = df["temperature"].values
    U = df["cooling_u"].values if "cooling_u" in df else np.zeros_like(T)
    dT_dt = df["dT_dt"].values

    # 정규화
    T_mean, T_std = np.mean(T), np.std(T) + 1e-6
    T_norm = (T - T_mean) / T_std

    # 학습 대상 물리 파라미터 (a: 열손실률, b: 냉각효율, d: 외기발열)
    # 초기값: RC 물리 모델 가정치 근처
    a = 0.006
    b = -0.05
    d = 0.15

    # 신경망 가중치 (간이 2층 비선형 MLP: 1 -> 8 -> 1)
    np.random.seed(42)
    W1 = np.random.randn(2, 16) * 0.1
    b1 = np.zeros(16)
    W2 = np.random.randn(16, 1) * 0.1
    b2 = np.zeros(1)

    X = np.stack([T_norm, U], axis=1) # (N, 2)
    y_true = dT_dt.reshape(-1, 1)     # (N, 1)

    for epoch in range(1, epochs + 1):
        # Forward Pass (MLP 예측)
        h1 = np.maximum(0, X @ W1 + b1) # ReLU
        pred_dT = h1 @ W2 + b2

        # 1. 데이터 피팅 손실 (Data Loss)
        loss_data = np.mean((pred_dT - y_true) ** 2)

        # 2. 물리 법칙 잔차 손실 (Physics Loss: dT/dt - (-a*T + d + b*U))
        physics_residual = pred_dT.flatten() - (-a * T + d + b * U)
        loss_phys = np.mean(physics_residual ** 2)

        total_loss = loss_data + lambda_phys * loss_phys

        # 경사하강법으로 물리 파라미터 온라인 적응 교정
        grad_res = 2.0 * physics_residual / len(T)
        da = -np.mean(grad_res * (-T))
        db = -np.mean(grad_res * U)
        dd = -np.mean(grad_res * 1.0)

        a -= lr * 0.01 * da
        b -= lr * 0.01 * db
        d -= lr * 0.01 * dd

        # 제약 조건 (물리적 부호 유지: a > 0, b < 0 for cooling)
        a = max(0.001, a)
        b = min(-0.005, b)

        # 가중치 업데이트 (Adam 대용 모멘텀)
        grad_out = (2.0 * (pred_dT - y_true) + 2.0 * lambda_phys * physics_residual.reshape(-1, 1)) / len(T)
        grad_W2 = h1.T @ grad_out
        grad_b2 = np.sum(grad_out, axis=0)

        grad_h1 = grad_out @ W2.T * (h1 > 0)
        grad_W1 = X.T @ grad_h1
        grad_b1 = np.sum(grad_h1, axis=0)

        W2 -= lr * grad_W2
        b2 -= lr * grad_b2
        W1 -= lr * grad_W1
        b1 -= lr * grad_b1

        if epoch % 300 == 0 or epoch == 1:
            r2 = 1.0 - np.sum((pred_dT - y_true) ** 2) / (np.sum((y_true - np.mean(y_true)) ** 2) + 1e-6)
            print(f"  [Epoch {epoch:4d}/{epochs}] Total Loss: {total_loss:.4f} | Data Loss: {loss_data:.4f} | Phys Loss: {loss_phys:.4f} | R²: {r2:.3f} | [a={a:.4f}, b={b:.4f}, d={d:.4f}]")

    if pipeline_smoke_test:
        print("\n🧪 [파이프라인 실행 완료 — 아래 값은 사용·저장 금지]")
    else:
        print("\n✅ [PINN 후보 학습 완료] 최종 물리 파라미터 수렴 결과:")
    print(f"  - 열 방출률 a (1/min): {a:.5f} (시정수 tau: {1/a:.1f}분)")
    print(f"  - 펠티어 냉각력 b (℃/min): {b:.5f}")
    print(f"  - 환경 외란 d (℃/min): {d:.5f}")
    return {
        "a": a,
        "b": b,
        "d": d,
        "r2": float(r2),
        "scope": "PIPELINE_SMOKE_TEST" if pipeline_smoke_test else "CANDIDATE_MODEL",
        "quality": quality.to_dict(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="ml/dataset_20260830_clean.csv")
    parser.add_argument("--epochs", type=int, default=1500)
    parser.add_argument("--lr", type=float, default=0.008)
    parser.add_argument(
        "--pipeline-smoke-test",
        action="store_true",
        help="품질 미달 데이터로 실행 경로만 시험하며 운영 모델은 만들지 않음",
    )
    args = parser.parse_args()

    if not os.path.exists(args.data):
        print(f"❌ 데이터셋 파일이 없습니다: {args.data}. 먼저 export_dataset.py를 실행하세요.")
        return

    df = pd.read_csv(args.data)
    try:
        train_pinn_numpy(
            df,
            epochs=args.epochs,
            lr=args.lr,
            pipeline_smoke_test=args.pipeline_smoke_test,
        )
    except ValueError as exc:
        raise SystemExit(f"❌ {exc}") from exc


if __name__ == "__main__":
    main()
