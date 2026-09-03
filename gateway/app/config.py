from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class MQTTConfig(BaseModel):
    host: str
    port: int
    client_id: str
    topics: List[str]

class AppConfig(BaseModel):
    # 접속 정보는 config 가 아니라 환경변수(DB_HOST/DB_PORT/DB_USER/
    # DB_PASSWORD/DB_NAME)로 준다. api/db.py 와 같은 규칙을 쓰고,
    # 비밀번호가 저장소에 커밋되는 것을 막기 위해서다.
    control_mode: str
    log_level: str
    # 이 게이트웨이가 담당하는 공간. 비워 두면 devices 테이블에서
    # 배정된 공간을 자동으로 찾는다.
    room_id: Optional[int] = None

class ControlConfig(BaseModel):
    decision_interval_sec: int
    target_temperature_c: float
    cooling_on_temperature_c: float
    cooling_on_duration_sec: int
    cooling_off_temperature_c: float
    cooling_off_duration_sec: int
    minimum_on_time_sec: int
    minimum_off_time_sec: int
    empty_confirmation_sec: int
    manual_lockout_sec: int
    command_rate_limit_sec: int
    co2_ventilation_warning_ppm: float
    co2_ventilation_warning_duration_sec: int
    co2_critical_ppm: float
    env_data_stale_sec: int
    occ_data_stale_sec: int
    # 인원 상당 1명당 온도 표류(℃/min). 가진 실험으로 식별하기 전에는 0으로
    # 두어, 근거 없는 인체 발열 feedforward가 실제 제어에 들어가지 않게 한다.
    internal_heat_drift_c_per_min_per_person: float = Field(default=0.0, ge=0)
    actuator_power_w: Optional[float] = Field(default=None, gt=0)
    # 정규화된 에너지·PMV slack·스위칭 항의 가중치. 통제 실험 전 기본값은
    # 설계값이며 민감도 분석과 Pareto plot으로 최종 선정해야 한다.
    mpc_weight_energy: float = Field(default=0.45, ge=0)
    mpc_weight_comfort: float = Field(default=14.0, ge=0)
    mpc_weight_switch: float = Field(default=1.2, ge=0)

class HMMConfig(BaseModel):
    transition_matrix_30s: List[List[float]]

class IRConfig(BaseModel):
    codes: Dict[str, str]
    # 펠티어(냉각 릴레이) 명령 토픽. 평문 "ON"/"OFF" 를 받는다.
    cooling_topic: str = "thermoshift/ir_01/cooling/cmd"
    # 에어컨 IR 명령 토픽. JSON 을 받는다. IR 프로파일 학습 후 동작한다.
    aircon_topic: str = "esp32/device/ir_01/control"
    # 테스트/수동 강제 구동용 ("ON", "OFF", None)
    manual_override: Optional[str] = None

class HeaterConfig(BaseModel):
    """합성 재실자(히팅패드) 설정. app/heater.py 참고.

    기본값만으로 동작하므로 config.yaml 에 heater 절이 없어도 된다 —
    기존 설정 파일이 그대로 뜨게 하려는 것이다.
    """
    # 히터 duty(%) 명령 토픽. 평문 정수 0~100 을 받는다.
    topic: str = "thermoshift/ir_01/heater/cmd"
    # 합성 재실자를 실제로 구동할지. False 면 duty 0 만 계속 보낸다.
    # (그래도 보내야 노드 워치독이 게이트웨이가 살아 있음을 안다.)
    enabled: bool = False
    # 테스트용 수동 고정 duty (0~100, None이면 실험 계획 참조)
    manual_duty: Optional[int] = None

class OccupancyEstimatorConfig(BaseModel):
    """실공간 CO₂ 질량보존 기반 인원수 추정 설정.

    목업 히터는 열만 만들고 사람의 CO₂ 발생을 재현하지 않으므로 목업에서는
    끈다. 실제 공간에서 체적·환기횟수를 측정한 뒤에만 활성화한다.
    """
    enabled: bool = False
    room_volume_m3: float = Field(default=45.0, gt=0)
    outdoor_co2_ppm: float = Field(default=420.0, ge=250, le=1000)
    base_ach: float = Field(default=0.35, gt=0)

class Config(BaseModel):
    mqtt: MQTTConfig
    app: AppConfig
    control: ControlConfig
    hmm: HMMConfig
    ir: IRConfig
    heater: HeaterConfig = Field(default_factory=HeaterConfig)
    occupancy_estimator: OccupancyEstimatorConfig = Field(
        default_factory=OccupancyEstimatorConfig
    )

def load_config(path: str = "config/config.yaml") -> Config:
    requested = Path(path)
    gateway_root = Path(__file__).resolve().parents[1]
    candidates = [
        requested,
        gateway_root / requested,
        gateway_root / "config" / "config.yaml",
        gateway_root / "config" / "config.example.yaml",
    ]
    resolved = next((candidate for candidate in candidates if candidate.is_file()), None)
    if resolved is None:
        raise FileNotFoundError(
            "Config file not found; checked: "
            + ", ".join(str(candidate) for candidate in candidates)
        )

    with resolved.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Config(**data)

# Global config instance
_config_instance = None

def get_config() -> Config:
    global _config_instance
    if _config_instance is None:
        _config_instance = load_config()
    return _config_instance
