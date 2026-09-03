"""목업용 다목적 경제적 MPC 프로토타입.

산업공학적 정식화 (Industrial Engineering & Optimization Formulation):
----------------------------------------------------------------------
본 컨트롤러는 전통적인 고정 설정온도 추종(Tracking Control)을 탈피하여,
에너지 비용(Economic Cost)과 열적 쾌적도(ISO 7730 PMV)를 파레토 최적화(Pareto Optimization)합니다.

  min_{u_0, ..., u_{N-1}}  J = sum_{k=0}^{N-1} [
        C_scenario(k) * u_k * dt                            # 1. 에너지 비용 대리지표
      + w_comfort * P_occ(k) * DiscomfortPenalty(PMV_k) * dt # 2. ISO 7730 PMV 쾌적도 이탈 페널티
      + w_switch * |u_k - u_{k-1}|                          # 3. 액추에이터 변동 억제
  ]

  model
    T_{k+1} = T_k + dt * [ -a * T_k + d_ext + d_internal(N_occ) + b * u_k ]  # 물리 동역학
    u_k in {0, 1}                                                           # 액추에이터 제약

PMV 허용대역 이탈은 현재 hard constraint가 아니라 목적함수의 soft penalty다.
전력계가 연결되고 열모델이 교정되기 전까지 출력되는 절감률은 실증 성과가
아니라 동일 모델 안에서 고정 설정온도 기준정책과 비교한 [SIM] 값이다.

특징 (Key Novelties):
--------------------
1. Physics-Guided Feedforward: 재실 인원 또는 합성 열부하와 현장 식별 계수를
   이용해 내부발열 외란을 예측에 반영한다. 계수 미교정 시 이 항은 비활성화한다.
2. Tariff Scenario Awareness: 피크 시간대 가중치를 높이는 시나리오와 예약
   예냉 후보를 비교한다. 실제 요금제 연동은 후속 검증 항목이다.
3. Small-Data Design: 1차 RC 구조의 소수 파라미터만 현장별로 식별한다.
   소량 데이터가 정확도나 안정성을 자동으로 보장하지는 않는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

from ml.comfort_model import calculate_pmv, ComfortMetrics
from ml.thermal_model import ThermalModel


@dataclass
class MPCOutput:
    optimal_action: str             # "POWER_OFF" | "COOL_24_AUTO" | "COOL_25_AUTO"
    decision_type: str              # "precool" | "maintain" | "setback" | "off"
    target_temp_c: float
    current_pmv: float
    predicted_pmv_60min: float
    simulated_energy_reduction_pct: float
    objective_cost: float
    reasons: List[str]
    trajectory_temp: List[Tuple[float, float]] # (분, 예측온도)
    pareto_metrics: Dict[str, Any]             # 전통 On/Off 제어 대비 파레토 비교 지표


class ModelPredictiveController:
    def __init__(
        self,
        horizon_minutes: int = 60,
        dt_minutes: float = 2.0,
        w_energy: float = 0.45,         # 에너지 비용 가중치
        w_comfort: float = 14.0,        # 재실 시 쾌적도 가중치
        w_switch: float = 1.2,          # 제어 빈도 억제 가중치
    ):
        self.horizon_minutes = horizon_minutes
        self.dt_minutes = dt_minutes
        self.steps = int(horizon_minutes / dt_minutes)
        self.w_energy = w_energy
        self.w_comfort = w_comfort
        self.w_switch = w_switch

    def _fixed_setpoint_baseline(
        self, current_temp_c: float, target_temp_c: float,
        a: float, b: float, d: float,
    ) -> List[int]:
        """동일 RC 모델에서 비교할 단순 thermostat 기준정책.

        ±0.5℃ hysteresis를 둔다. 실측 baseline이 아니라 [SIM] 비교군이며,
        발표에서 실제 에너지 절감률로 사용하면 안 된다.
        """
        temp = current_temp_c
        on = temp > target_temp_c + 0.5
        sequence: List[int] = []
        for _ in range(self.steps):
            if temp > target_temp_c + 0.5:
                on = True
            elif temp < target_temp_c - 0.5:
                on = False
            u = int(on)
            sequence.append(u)
            temp += (-a * temp + d + b * u) * self.dt_minutes
        return sequence

    def solve(
        self,
        current_temp_c: float,
        humidity_pct: float,
        p_occupied: float,              # HMM 재실 확률 (0.0 ~ 1.0)
        thermal_model: Optional[ThermalModel] = None,
        target_temp_setting: float = 24.0,
        schedule_in_minutes: Optional[float] = None, # 다음 예약까지 남은 시간 (분)
        current_cooling_on: bool = False,
        headcount_estimate: float = 0.0,             # 물리 기반 추정 인원수 (명)
        heat_drift_c_per_min_per_person: float = 0.0,
        peak_hour: bool = False,                     # TOU 피크 요금 시간대 여부
    ) -> MPCOutput:
        """MPC 롤링 호라이즌 최적화를 수행하여 파레토 최적 제어 결정을 도출한다."""
        if thermal_model is None:
            thermal_model = ThermalModel()

        a = thermal_model.a
        b = thermal_model.b
        
        # 인체/합성 열부하 feedforward. 계수는 공간 열용량과 열원 스케일에
        # 따라 달라지므로 코드에 대표값을 박지 않고 실험으로 식별해 주입한다.
        internal_heat_drift = (
            headcount_estimate * heat_drift_c_per_min_per_person
        )
        d = thermal_model.d + internal_heat_drift
        dt = self.dt_minutes

        # 목업 시나리오 가중치다. 실제 요금 단가라고 주장하지 않는다.
        tariff_weight = 1.5 if peak_hour else 1.0
        eff_energy_weight = self.w_energy * tariff_weight

        # 1. 현재 ISO 7730 PMV 평가
        current_comfort = calculate_pmv(current_temp_c, humidity_pct)

        # 2. 미래 재실 확률 프로파일
        p_occ_profile = []
        for step in range(self.steps):
            t_min = step * dt
            if schedule_in_minutes is not None and t_min >= schedule_in_minutes:
                p_occ_profile.append(1.0)
            else:
                p_occ_profile.append(p_occupied)

        # 3. 제어 후보 시퀀스 공간 생성
        candidate_policies = [
            ("ALL_OFF", [0] * self.steps),
            ("ALL_ON", [1] * self.steps),
        ]

        # 선냉방(Precooling) 후보군
        for t_start_step in range(1, self.steps):
            u_seq = [0] * t_start_step + [1] * (self.steps - t_start_step)
            candidate_policies.append((f"PRECOOL_{int(t_start_step*dt)}m", u_seq))

        # 듀티 사이클(Setback 절전) 후보군 (50%, 66% 가동)
        candidate_policies.append(("DUTY_50", [1, 0] * (self.steps // 2)))
        candidate_policies.append(("DUTY_66", [1, 1, 0] * (self.steps // 3)))

        # 4. 각 정책의 목적함수 J 계산
        best_cost = float("inf")
        best_u_seq = [0] * self.steps
        best_temp_traj = []

        for name, u_seq in candidate_policies:
            cost = 0.0
            temp = current_temp_c
            traj = [(0.0, temp)]
            prev_u = 1 if current_cooling_on else 0

            for k in range(self.steps):
                u = u_seq[k]
                d_temp = (-a * temp + d + b * u) * dt
                temp = temp + d_temp
                traj.append(((k + 1) * dt, temp))

                # 에너지 소비 비용
                cost += eff_energy_weight * float(u) * dt

                # 불쾌도 페널티: PMV 쾌적 대역(|PMV| <= 0.45) 밖 이탈 시 볼록 2차 페널티
                step_pmv = calculate_pmv(temp, humidity_pct).pmv
                if abs(step_pmv) > 0.45:
                    discomfort = ((abs(step_pmv) - 0.45) * 5.0) ** 2
                else:
                    discomfort = 0.0
                cost += self.w_comfort * p_occ_profile[k] * discomfort * dt

                # 스위칭 진동 억제
                if u != prev_u:
                    cost += self.w_switch
                prev_u = u

            if cost < best_cost:
                best_cost = cost
                best_u_seq = u_seq
                best_temp_traj = traj

        # 5. 최적 제어 결정 해석
        next_action_u = best_u_seq[0]
        final_temp = best_temp_traj[-1][1]
        final_pmv = calculate_pmv(final_temp, humidity_pct).pmv

        reasons = []
        duty_cycle = sum(best_u_seq) / len(best_u_seq)
        
        baseline_u = self._fixed_setpoint_baseline(
            current_temp_c, target_temp_setting, a, b, d,
        )
        baseline_runtime = sum(baseline_u) * dt
        optimized_runtime = sum(best_u_seq) * dt
        simulated_reduction_pct = (
            round(100.0 * (baseline_runtime - optimized_runtime) / baseline_runtime, 1)
            if baseline_runtime > 0 else 0.0
        )
        # 음수도 숨기지 않는다. 해당 시나리오에서 쾌적도를 위해 더 사용했다는 뜻이다.

        def switch_count(sequence: List[int], initial: int) -> int:
            count = 0
            previous = initial
            for value in sequence:
                if value != previous:
                    count += 1
                previous = value
            return count

        initial_u = int(current_cooling_on)
        baseline_switches = switch_count(baseline_u, initial_u)
        optimized_switches = switch_count(best_u_seq, initial_u)
        switch_reduction_pct = (
            round(100.0 * (baseline_switches - optimized_switches) / baseline_switches, 1)
            if baseline_switches > 0 else 0.0
        )

        if next_action_u == 1:
            if schedule_in_minutes is not None and schedule_in_minutes > 0:
                decision_type = "precool"
                target_c = target_temp_setting
                action = f"COOL_{int(round(target_c))}_AUTO"
                reasons.append(f"MPC 최적화: {schedule_in_minutes:.0f}분 뒤 예약 대상 선냉방(Pre-cooling) 가동")
                reasons.append(f"열역학 시정수 역산으로 예약 시점 PMV {final_pmv:+.2f} 도달 궤적 추종")
            else:
                decision_type = "maintain"
                target_c = current_comfort.optimal_temp_c
                action = f"COOL_{int(round(target_c))}_AUTO"
                reasons.append(f"MPC 최적화: 재실 온열감(PMV {current_comfort.pmv:+.2f}) 해소를 위한 냉방 가동")
                reasons.append(f"목표 중립온도 {target_c:.1f}℃ (예측 만족도 {100-current_comfort.ppd:.0f}%)")
        else:
            if current_comfort.comfort_score >= 80 and p_occupied > 0.4:
                decision_type = "setback"
                target_c = current_comfort.setback_temp_c
                reasons.append(f"MPC 최적화: 쾌적 밴드(PMV {current_comfort.pmv:+.2f}) 유지 중")
                action = "POWER_OFF"
                reasons.append(f"쾌적 허용대역 안에서 설정 기준을 {target_c:.1f}℃로 완화")
                reasons.append(
                    f"[SIM] 고정 설정온도 기준정책 대비 가동시간 변화 "
                    f"{simulated_reduction_pct:+.1f}%"
                )
            else:
                decision_type = "off"
                target_c = target_temp_setting
                action = "POWER_OFF"
                reasons.append(f"MPC 최적화: 공실(재실확률 {p_occupied:.2f}) 또는 자연 냉각 구간")
                reasons.append("불필요한 펠티어 가동을 피해 전력 사용을 억제")

        pmv_values = [calculate_pmv(t, humidity_pct).pmv for _, t in best_temp_traj[1:]]
        comfort_violation_rate = (
            round(100.0 * sum(abs(v) > 0.5 for v in pmv_values) / len(pmv_values), 1)
            if pmv_values else 0.0
        )
        pareto_metrics = {
            "scope": "SIMULATION_ESTIMATE",
            "baseline_policy": "fixed_setpoint_hysteresis_0.5C",
            "baseline_runtime_min": round(baseline_runtime, 1),
            "optimized_runtime_min": round(optimized_runtime, 1),
            "runtime_reduction_pct": simulated_reduction_pct,
            "comfort_violation_rate_pct": comfort_violation_rate,
            "baseline_switch_count": baseline_switches,
            "optimized_switch_count": optimized_switches,
            "actuator_switch_reduction_pct": switch_reduction_pct,
            "headcount_or_equivalent": round(headcount_estimate, 2),
            "heat_drift_c_per_min": round(internal_heat_drift, 5),
            "heat_feedforward_status": (
                "CALIBRATED_INPUT_REQUIRED"
                if heat_drift_c_per_min_per_person <= 0
                else "ENABLED_WITH_CONFIGURED_GAIN"
            ),
        }

        return MPCOutput(
            optimal_action=action,
            decision_type=decision_type,
            target_temp_c=target_c,
            current_pmv=current_comfort.pmv,
            predicted_pmv_60min=round(final_pmv, 2),
            simulated_energy_reduction_pct=simulated_reduction_pct,
            objective_cost=round(best_cost, 2),
            reasons=reasons,
            trajectory_temp=best_temp_traj,
            pareto_metrics=pareto_metrics,
        )
