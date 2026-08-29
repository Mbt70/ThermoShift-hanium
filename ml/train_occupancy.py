"""재실 HMM 파라미터를 실측으로 추정한다.

    python -m ml.train_occupancy                      # 구 SQLite 기록으로
    python -m ml.train_occupancy --source postgres    # 운영 DB 로
    python -m ml.train_occupancy --holdout 0.3        # 검증 비중 조정

결과는 ml/params/occupancy.json 에 쓰고, 게이트웨이가 시작할 때 읽는다.
파일이 없으면 게이트웨이는 기존 수기 값으로 그대로 동작한다 — 학습이
필수 경로가 되면 안 되기 때문이다.

검증 방식
---------
라벨이 없으므로 정확도를 잴 수 없다. 대신 **검증 구간의 로그우도**를 본다.
"이 모델이 실제로 관측된 센서열을 얼마나 잘 설명하는가" 이고, 기존 수기
모델과 같은 자로 비교할 수 있다. 학습에 쓰지 않은 뒷부분으로 잰다.

정확도(F1)를 보고하려면 사람이 직접 재실 여부를 적어 둔 구간이 있어야
한다. 그 라벨을 만들기 전에는 F1 을 계산하지 않는다.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from ml.dataset import (build_sessions, load_postgres, load_sqlite, summarize)
from ml.occupancy_model import (OccupancyModel, STATES, baum_welch_map,
                                check_identifiability, encode)

# 사전분포 세기 후보. 작을수록 데이터를, 클수록 기존 수기 값을 따른다.
# 어느 쪽이 맞는지는 표본 크기에 달려 있으므로 검증 로그우도로 고른다.
SWEEP = [10.0, 20.0, 40.0, 80.0, 160.0, 320.0, 640.0]

DEFAULT_SQLITE = "/home/thermo/thermoshift-data/thermoshift.db"
PARAM_PATH = Path(__file__).resolve().parent / "params" / "occupancy.json"


def split(sequences: list[list[dict]], holdout: float):
    """각 시퀀스의 뒷부분을 검증으로 뗀다.

    시퀀스를 통째로 나누지 않는 이유는 세션이 2개뿐이라서다. 하나를 통째로
    빼면 학습 자료가 절반이 된다. 시간순 뒷부분을 떼면 '앞을 보고 뒤를
    맞히는' 형태가 되어 시계열 검증으로도 옳다.
    """
    train, valid = [], []
    for seq in sequences:
        cut = int(len(seq) * (1 - holdout))
        if cut >= 2:
            train.append(seq[:cut])
        if len(seq) - cut >= 2:
            valid.append(seq[cut:])
    return train, valid


def per_epoch_ll(model: OccupancyModel, seqs: list[list[dict]]) -> float:
    n = sum(len(s) for s in seqs)
    return model.loglikelihood(seqs) / n if n else float("nan")


def describe(model: OccupancyModel) -> str:
    L = []
    L.append("  전이확률 (30초)")
    L.append("           " + "".join(f"{s:>12}" for s in STATES))
    for i, s in enumerate(STATES):
        L.append(f"    {s:<10}" + "".join(f"{v:12.4f}" for v in model.transition[i]))
    L.append("  관측 확률")
    L.append(f"    {'P(PIR최근=1|s)':<22}" + "".join(f"{v:9.3f}" for v in model.pir))
    L.append(f"    {'P(문최근=1|s)':<22}" + "".join(f"{v:9.3f}" for v in model.door))
    for i, s in enumerate(STATES):
        L.append(f"    CO2기울기|{s:<11}" +
                 "  하강 %.3f  평탄 %.3f  상승 %.3f" % tuple(model.co2_slope[i]))
    for i, s in enumerate(STATES):
        L.append(f"    CO2초과 |{s:<11}" +
                 "  낮음 %.3f  중간 %.3f  높음 %.3f" % tuple(model.co2_delta[i]))
    return "\n".join(L)


def state_mix(model: OccupancyModel, seqs: list[list[dict]]) -> list[float]:
    """모델이 각 상태에 얼마나 시간을 배분하는지(사후 평균)."""
    tot = [0.0] * 3
    n = 0
    for seq in seqs:
        gamma, _, _ = model.forward_backward(seq)
        for g in gamma:
            for i in range(3):
                tot[i] += g[i]
            n += 1
    return [t / n for t in tot] if n else [0.0] * 3


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", choices=["sqlite", "postgres"], default="sqlite")
    ap.add_argument("--sqlite", default=DEFAULT_SQLITE)
    ap.add_argument("--room-id", type=int, default=None)
    ap.add_argument("--holdout", type=float, default=0.25)
    ap.add_argument("--iterations", type=int, default=200)
    ap.add_argument("--out", default=str(PARAM_PATH))
    ap.add_argument("--dry-run", action="store_true", help="파일로 저장하지 않는다")
    ap.add_argument("--force", action="store_true",
                    help="검증이 나빠져도 저장한다 (권장하지 않음)")
    ap.add_argument("--no-sweep", action="store_true",
                    help="사전분포 세기 탐색을 건너뛴다")
    args = ap.parse_args()

    print("== 데이터 적재")
    if args.source == "postgres":
        env, occ = load_postgres(args.room_id)
    else:
        env, occ = load_sqlite(args.sqlite)
    sessions = build_sessions(env, occ)
    if not sessions:
        raise SystemExit("학습할 세션이 없습니다. 재실 센서 기록이 있는지 확인하세요.")
    print(summarize(sessions))

    sequences = [[encode(e) for e in s.epochs] for s in sessions]
    train, valid = split(sequences, args.holdout)
    n_train = sum(len(s) for s in train)
    n_valid = sum(len(s) for s in valid)
    print(f"\n== 분할  학습 {n_train} 에폭 / 검증 {n_valid} 에폭")

    baseline = OccupancyModel()   # 기존 수기 파라미터
    print("\n== 기존(수기) 모델")
    print(describe(baseline))

    b_tr, b_va = per_epoch_ll(baseline, train), per_epoch_ll(baseline, valid)

    print("\n== MAP-EM 학습 (사전분포 세기를 검증 로그우도로 선택)")
    strengths = [40.0] if args.no_sweep else SWEEP
    print(f"    {'세기':>7}{'반복':>6}{'학습LL':>10}{'검증LL':>10}   판정")
    results = []
    for k in strengths:
        m, hist = baum_welch_map(train, iterations=args.iterations,
                                 strength_emission=k,
                                 strength_transition=k * 10)
        tr, va = per_epoch_ll(m, train), per_epoch_ll(m, valid)
        warns = check_identifiability(m)
        results.append((va, k, m, tr, warns))
        mark = "경고 %d건" % len(warns) if warns else "정상"
        print(f"    {k:7.0f}{len(hist):6d}{tr:10.4f}{va:10.4f}   {mark}")

    # 경고가 없는 것 중에서 검증이 가장 좋은 것을 고른다. 검증 점수가 아무리
    # 높아도 상태 해석이 뒤집힌 모델은 제어에 쓸 수 없기 때문이다.
    clean = [r for r in results if not r[4]]
    pool = clean or results
    m_va, best_k, model, m_tr, warns = max(pool, key=lambda r: r[0])
    if not clean:
        print("    ! 모든 후보에 경고가 있습니다 — 검증 점수만으로 골랐습니다.")
    print(f"    선택: 세기 {best_k:.0f}")
    print(describe(model))

    print("\n== 검증 (에폭당 평균 로그우도, 높을수록 잘 설명)")
    print(f"    {'':16}{'학습':>10}{'검증':>10}")
    print(f"    {'기존(수기)':<16}{b_tr:10.4f}{b_va:10.4f}")
    print(f"    {'학습된 모델':<16}{m_tr:10.4f}{m_va:10.4f}")
    gain = m_va - b_va
    print(f"    검증 개선 {gain:+.4f} / 에폭"
          + ("  (개선)" if gain > 0 else "  (개선 없음)"))

    mix = state_mix(model, sequences)
    print(f"\n== 상태 시간 배분  EMPTY {mix[0]:.1%} · TRANSITION {mix[1]:.1%} · OCCUPIED {mix[2]:.1%}")

    warns = check_identifiability(model)
    if warns:
        print("\n== 경고")
        for w in warns:
            print(f"  ! {w}")

    model.metadata = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "source": args.source,
        "sessions": len(sessions),
        "observed_hours": round(sum(s.hours for s in sessions), 2),
        "epochs_train": n_train,
        "epochs_valid": n_valid,
        "loglik_per_epoch": {"baseline_valid": round(b_va, 4),
                             "model_valid": round(m_va, 4),
                             "gain": round(gain, 4)},
        "state_mix": [round(x, 4) for x in mix],
        "warnings": warns,
        # 표본이 적다는 사실을 파일 안에 남긴다. 나중에 이 파라미터를 근거로
        # 쓸 때 어느 정도 자료에서 나온 것인지 바로 보이게 하려는 것이다.
        "note": ("표본이 적으면 사전분포(기존 수기 값) 쪽에 머문다. "
                 "며칠분이 쌓인 뒤 같은 명령으로 재학습하면 데이터 쪽으로 움직인다."),
        "caveat": ("사전분포 세기를 같은 검증 구간으로 골랐으므로 검증 개선치에는 "
                   "선택편향이 섞여 있다. 관측이 며칠분 쌓이면 검증 구간을 따로 "
                   "떼어 다시 재는 것이 옳다."),
    }

    model.metadata["prior_strength"] = best_k

    if args.dry_run:
        print("\n(--dry-run: 저장하지 않음)")
        return

    # 배포 게이트 — 둘 중 하나라도 걸리면 저장하지 않는다.
    #
    # 학습이 돌아갔다는 것과 그 결과를 제어에 써도 된다는 것은 다른 얘기다.
    # 검증이 나빠졌거나 상태 해석이 뒤집힌 파라미터를 내보내면, 게이트웨이는
    # 그걸 그대로 믿고 사람이 있는 방의 냉방을 끈다. 기존 수기 값이
    # 최소한 그런 실수는 하지 않는다.
    blockers = []
    if gain <= 0:
        blockers.append(f"검증 로그우도가 기존보다 낮습니다 ({gain:+.4f}/에폭). "
                        "관측이 더 쌓여야 합니다.")
    blockers += warns

    if blockers and not args.force:
        print("\n== 저장하지 않음 — 아래 이유로 제어에 쓰기에 적절하지 않습니다")
        for b in blockers:
            print(f"  ! {b}")
        print("\n  게이트웨이는 기존 수기 파라미터로 그대로 동작합니다.")
        print("  관측을 더 모은 뒤 같은 명령을 다시 돌리세요.")
        print("  (판단을 무시하고 저장하려면 --force)")
        raise SystemExit(1)

    if blockers:
        print("\n== --force: 아래 경고를 무시하고 저장합니다")
        for b in blockers:
            print(f"  ! {b}")

    model.save(args.out)
    print(f"\n저장: {args.out}")


if __name__ == "__main__":
    main()
