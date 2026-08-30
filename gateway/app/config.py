import yaml
import os
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

class HMMConfig(BaseModel):
    transition_matrix_30s: List[List[float]]

class IRConfig(BaseModel):
    codes: Dict[str, str]
    # 펠티어(냉각 릴레이) 명령 토픽. 평문 "ON"/"OFF" 를 받는다.
    cooling_topic: str = "thermoshift/ir_01/cooling/cmd"
    # 에어컨 IR 명령 토픽. JSON 을 받는다. IR 프로파일 학습 후 동작한다.
    aircon_topic: str = "esp32/device/ir_01/control"

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

class Config(BaseModel):
    mqtt: MQTTConfig
    app: AppConfig
    control: ControlConfig
    hmm: HMMConfig
    ir: IRConfig
    heater: HeaterConfig = Field(default_factory=HeaterConfig)

def load_config(path: str = "config/config.yaml") -> Config:
    if not os.path.exists(path):
        # fallback to example if running tests or manual setup
        if os.path.exists("config/config.example.yaml"):
            path = "config/config.example.yaml"
        elif os.path.exists("../config/config.example.yaml"):
            path = "../config/config.example.yaml"
        else:
            raise FileNotFoundError(f"Config file not found: {path}")
    
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    return Config(**data)

# Global config instance
_config_instance = None

def get_config() -> Config:
    global _config_instance
    if _config_instance is None:
        _config_instance = load_config()
    return _config_instance
