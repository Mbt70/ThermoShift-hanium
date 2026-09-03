"""CO₂ 질량보존 관측치를 이용한 Kalman 센서 융합 프로토타입.

산업공학적 배경 (IE Background):
------------------------------
기존 PIR(적외선 모션) 센서는 재실자가 가만히 앉아 공부하거나 업무를 볼 때
'공실'로 오판하는 치명적인 정적 감지 한계(Static Blind Spot)를 가집니다.
또한 기존 HMM은 재실 여부(Binary/3-state)만 알 수 있을 뿐, '몇 명이 있는가?'를
알지 못해 인체 발열 부하를 제어 외란으로 연결하기 어렵습니다.

본 알고리즘은 **CO₂ 질량 보존 방정식(Mass Balance Dynamics)**으로 순간
인원수 관측치를 만들고, 1차원 선형 Kalman update와 PIR 규칙을 결합하여:
1. 방 안의 재실 인원수 N(t)를 연속적(Continuous)으로 추정하고,
2. 대표 발열량 가정으로 내부 열부하의 제어 입력값을 산출합니다.

이 구현은 상태 [CO₂, 인원수]에 비선형 전이·관측 Jacobian을 적용하는 EKF가
아니다. 또한 환기량(ACH)과 공간 체적을 현장에서 교정하기 전에는 연구용
추정치이며, 성능 검증값으로 사용하지 않는다.

지배 방정식 (Governing Equation):
--------------------------------
V * dC(t)/dt = G_per_person * N(t) - Q_vent * (C(t) - C_outdoor)

  - V: 실내 체적 (m³)
  - C(t): 실내 CO₂ 농도 (ppm)
  - C_outdoor: 외기 CO₂ 농도 (기본 420 ppm)
  - G_per_person: 성인 1인당 호흡 CO₂ 발생률 (~0.0052 L/s = ~18.72 L/h)
  - Q_vent: 환기 유량 (m³/h) = V * ACH (Air Changes per Hour)
  - N(t): 추정 재실 인원수 (명)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class PhysicsOccupancyEstimate:
    estimated_headcount: float       # 추정 인원수 (연속값, e.g. 1.8명)
    rounded_headcount: int          # 반올림 인원수 (e.g. 2명)
    occupancy_state: str            # "EMPTY" | "SINGLE" | "MULTI"
    confidence: float               # 신뢰도 (0.0 ~ 1.0)
    internal_heat_gain_w: float     # 대표 발열량 가정에 따른 인체 발열 부하(W)
    min_ventilation_rate_m3h: float # 설계용 간이 환기 시나리오값 (m³/h)
    co2_generation_rate_ppm_min: float # CO2 발생률 (ppm/min)


class PhysicsInformedOccupancyEstimator:
    def __init__(
        self,
        room_volume_m3: float = 45.0,        # 실내 체적 (기본 45m³)
        outdoor_co2_ppm: float = 420.0,      # 외기 CO2 농도
        base_ach: float = 0.35,              # 기본 자연 환기 횟수 (1/h)
        co2_gen_per_person_l_h: float = 18.72, # 1인당 호흡 CO2 (L/h)
        heat_gain_per_person_w: float = 100.0, # 활동량에 따라 교정할 대표값
    ):
        if (room_volume_m3 <= 0 or base_ach <= 0
                or co2_gen_per_person_l_h <= 0 or heat_gain_per_person_w <= 0):
            raise ValueError("room volume, ACH, CO2 generation, and heat gain must be positive")
        self.volume_m3 = room_volume_m3
        self.c_out = outdoor_co2_ppm
        self.ach = base_ach
        self.g_co2 = co2_gen_per_person_l_h
        self.heat_gain_per_person_w = heat_gain_per_person_w
        
        # 1ppm CO2 in room volume = V * 1e-6 m³ = V * 1e-3 L
        # 1인당 호흡 발생 농도 변화율: (G / V_L) * 1e6 = G / (V_m3 * 1e3) * 1e6 = (G * 1000) / V ppm/h
        self.ppm_per_person_per_hour = (self.g_co2 * 1000.0) / (self.volume_m3 * 1000.0) * 1e3
        self.ppm_per_person_per_min = self.ppm_per_person_per_hour / 60.0

        # 칼만 필터 상태 추정치: N_hat (인원수)
        self.headcount_hat = 0.0
        self.p_var = 1.0     # 추정 오차 공분산
        self.q_noise = 0.05  # 프로세스 노이즈 (인원 이동 빈도)
        self.r_noise = 0.4   # 센서 노이즈

    def update(
        self,
        current_co2_ppm: float,
        co2_slope_ppm_min: float,   # 최근 5~10분 CO2 기울기 (ppm/min)
        pir_motion: bool,
        door_event_recent: bool = False,
        dt_minutes: float = 1.0,
    ) -> PhysicsOccupancyEstimate:
        """CO2 동역학과 PIR 모션을 융합하여 실시간 재실 인원수를 추정한다."""
        # 1. 자연 환기 손실률 계산
        # V * dC/dt = G*N - Q*(C - C_out)
        # dC/dt = (G*N)/V - ACH * (C - C_out) / 60
        decay_slope = (self.ach / 60.0) * max(0.0, current_co2_ppm - self.c_out)
        
        # 순수 CO2 발생률 = 관측된 기울기 + 환기 손실률
        net_gen_slope = co2_slope_ppm_min + decay_slope
        
        # 질량보존 법칙으로부터 물리 역산한 순간 인원수 (Raw Physics Inversion)
        if net_gen_slope <= 0.05:
            raw_headcount = 0.0
        else:
            raw_headcount = max(0.0, net_gen_slope / max(0.01, self.ppm_per_person_per_min))

        # 2. 칼만 필터 예측 단계 (Prediction)
        n_pred = self.headcount_hat
        p_pred = self.p_var + self.q_noise * dt_minutes

        # 3. PIR 센서 신호에 의한 측정값 보정 (Sensor Fusion)
        if not pir_motion and current_co2_ppm < (self.c_out + 80.0):
            # 모션도 없고 CO2도 외기 수준이면 확실한 공실
            z_meas = 0.0
            r_adaptive = 0.1
        elif pir_motion and raw_headcount < 0.3:
            # 모션은 있는데 CO2가 아직 덜 올랐을 때 (최소 1명 보장)
            z_meas = 1.0
            r_adaptive = 0.5
        else:
            z_meas = min(15.0, raw_headcount)
            r_adaptive = self.r_noise

        # 4. 칼만 필터 갱신 단계 (Update)
        kalman_gain = p_pred / (p_pred + r_adaptive)
        self.headcount_hat = n_pred + kalman_gain * (z_meas - n_pred)
        self.headcount_hat = max(0.0, self.headcount_hat)
        self.p_var = (1.0 - kalman_gain) * p_pred

        # 5. 상태 해석 및 인체 발열 부하 산출
        est_n = round(self.headcount_hat, 2)
        rounded_n = int(round(est_n))
        
        if est_n < 0.25:
            state = "EMPTY"
        elif est_n < 1.5:
            state = "SINGLE"
        else:
            state = "MULTI"

        # 100 W는 기본 대표값일 뿐이며 활동량에 맞춰 생성자에서 바꿀 수 있다.
        internal_heat_w = round(est_n * self.heat_gain_per_person_w, 1)

        # 간이 설계 시나리오. 바닥면적·공간용도 없이 ASHRAE 62.1 준수값을
        # 계산할 수 없으므로 표준 준수 환기량으로 표시하지 않는다.
        min_vent_m3h = round(max(20.0, est_n * 27.0 + 15.0), 1)

        # 신뢰도 지표 (추정 오차 분산의 역수 함수)
        confidence = round(max(0.5, min(0.98, 1.0 / (1.0 + self.p_var))), 2)

        return PhysicsOccupancyEstimate(
            estimated_headcount=est_n,
            rounded_headcount=rounded_n,
            occupancy_state=state,
            confidence=confidence,
            internal_heat_gain_w=internal_heat_w,
            min_ventilation_rate_m3h=min_vent_m3h,
            co2_generation_rate_ppm_min=round(net_gen_slope, 2),
        )
