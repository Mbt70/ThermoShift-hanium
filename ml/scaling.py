"""12 L 목업과 실제 공간 사이의 배포 경계와 초기 가정.

심사위원 핵심 질문 대응:
Q: "12L 아크릴 상자에서 실험한 결과가 왜 실제 30~50m³ 방에서도 유효한가?"
A: "목업에서 검증하는 것은 센서→추정→예측→제어의 아키텍처와 실험
   절차입니다. 실제 공간에서는 같은 RC 모델 구조와 MPC 코드를 재사용하되,
   R, C, 내부발열, 환기량, 액추에이터 효율은 현장 데이터로 다시 식별합니다."

목업과 45m³ 공간은 표면적/부피비, 자연대류, 혼합, 열용량이 달라 목업의
파라미터나 절감률을 1:1 이전할 수 없다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ThermalDomainParams:
    name: str                   # "Mockup (12L Chamber)" or "Real Room (45m³ Office)"
    volume_m3: float            # 체적 (m³)
    floor_area_m2: float        # 바닥 면적 (m²)
    air_heat_capacity_j_k: float # 유효 열용량 C (J/K)
    thermal_resistance_k_w: float # 유효 열저항 R (K/W)
    time_constant_min: float    # 시정수 tau = R * C (분)
    cooling_capacity_w: float   # 냉각 능력 (W)
    internal_heat_gain_w: float # 내부 발열 (재실자 + 기기) (W)
    cooling_power_w: float      # 냉방기 소비 전력 (W)
    cop: float                  # 성능 계수 (COP = Cooling Capacity / Electric Power)


# 1. 목업 챔버 기준 파라미터 (12L 아크릴 챔버, 펠티어 소자, 10W 히팅패드)
MOCKUP_DOMAIN = ThermalDomainParams(
    name="12L Mockup Chamber (실증 목업)",
    volume_m3=0.012,            # 20cm x 20cm x 30cm = 0.012 m³
    floor_area_m2=0.04,         # 0.2m x 0.2m
    air_heat_capacity_j_k=3000.0, # 교정 전: 공기 + 벽체 유효 열용량
    thermal_resistance_k_w=1.0 / 0.7, # 교정 전 UA=0.7 W/K의 역수
    time_constant_min=(3000.0 / 0.7) / 60.0,  # 교정 전 약 71분
    cooling_capacity_w=25.0,    # 펠티어 유효 냉각 열량
    internal_heat_gain_w=10.0,  # 합성 재실자(히팅패드 100% 가동 시)
    cooling_power_w=36.0,       # 12V * 3A = 36W
    cop=25.0 / 36.0,            # 펠티어 COP ≈ 0.7
)

# 2. 실제 공간 기준 파라미터 (소형 오피스/스터디룸, 3~4인용)
REAL_OFFICE_DOMAIN = ThermalDomainParams(
    name="Real Space (소형 사무실 45m³)",
    volume_m3=45.0,             # 4.5m x 4m x 2.5m = 45 m³
    floor_area_m2=18.0,         # 약 5.5평
    air_heat_capacity_j_k=1.2e6,# 공기(54kg) + 콘크리트/벽체 열용량 (약 1.2 MJ/K)
    thermal_resistance_k_w=0.008, # 건물 외벽 및 창호 단열
    time_constant_min=(1.2e6 * 0.008) / 60.0, # 약 160분
    cooling_capacity_w=2500.0,  # 7평형 인버터 벽걸이 에어컨 정격 냉방 2.5kW
    internal_heat_gain_w=350.0, # 재실자 3인 (100W/인) + PC/조명 (50W)
    cooling_power_w=650.0,      # 인버터 정격 소비전력 약 650W
    cop=2500.0 / 650.0,         # 인버터 에어컨 COP ≈ 3.85
)


def scale_parameters(
    source_model_a: float,      # 1/tau (1/min)
    source_model_b: float,      # 냉각률 (℃/min, 음수)
    source_model_d: float,      # 표류항 (℃/min)
    from_domain: ThermalDomainParams = MOCKUP_DOMAIN,
    to_domain: ThermalDomainParams = REAL_OFFICE_DOMAIN,
) -> dict:
    """대상 공간의 독립 가정으로 초기값을 만들고 재교정 필요성을 표시한다.

    source_model_*은 추적 가능성을 위해 반환할 뿐 대상 파라미터 산출에는
    사용하지 않는다. 이 함수의 결과는 실공간 제어·성과 주장에 사용할 수 없다.
    """
    # 체적비
    vol_ratio = to_domain.volume_m3 / from_domain.volume_m3
    # 열용량비
    c_ratio = to_domain.air_heat_capacity_j_k / from_domain.air_heat_capacity_j_k
    # 열저항비
    r_ratio = to_domain.thermal_resistance_k_w / from_domain.thermal_resistance_k_w
    # 냉각 능력비
    q_cool_ratio = to_domain.cooling_capacity_w / from_domain.cooling_capacity_w

    # 실제 공간의 시정수 및 a 계수
    tau_scaled_min = to_domain.time_constant_min
    a_scaled = 1.0 / tau_scaled_min

    # 실제 공간의 냉각률 b 계수 (℃/min = Q_cool / C * 60)
    b_scaled = -(to_domain.cooling_capacity_w / to_domain.air_heat_capacity_j_k) * 60.0

    # 실제 공간의 표류항 d 계수 (외기 28℃, 내부발열 고려)
    t_out_nominal = 28.0
    d_scaled = a_scaled * t_out_nominal + (to_domain.internal_heat_gain_w / to_domain.air_heat_capacity_j_k) * 60.0

    return {
        "vol_ratio": round(vol_ratio, 1),
        "tau_mockup_min": round(from_domain.time_constant_min, 1),
        "tau_real_min": round(to_domain.time_constant_min, 1),
        "scaled_a": round(a_scaled, 6),
        "scaled_b": round(b_scaled, 5),
        "scaled_d": round(d_scaled, 5),
        "source_cop": round(from_domain.cop, 2),
        "target_cop": round(to_domain.cop, 2),
        "requires_site_recalibration": True,
        "transfer_scope": "CONTROL_ARCHITECTURE_ONLY",
        "source_model": {
            "a": source_model_a, "b": source_model_b, "d": source_model_d,
        },
        "scientific_rationale": (
            f"체적은 {from_domain.volume_m3:.3f}m³와 {to_domain.volume_m3:.1f}m³로 "
            f"약 {vol_ratio:.0f}배 다릅니다. RC 모델의 구조와 MPC 절차만 재사용하고, "
            "R·C·외란·액추에이터 효율은 대상 공간에서 다시 식별해야 합니다."
        ),
    }
