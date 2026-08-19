import yaml
import os
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

class MQTTConfig(BaseModel):
    host: str
    port: int
    client_id: str
    topics: List[str]

class AppConfig(BaseModel):
    db_path: str
    control_mode: str
    log_level: str
    # 이 게이트웨이가 담당하는 공간. 비워 두면 devices 테이블에서
    # 배정된 공간을 자동으로 찾는다.
    room_id: Optional[str] = None

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

class Config(BaseModel):
    mqtt: MQTTConfig
    app: AppConfig
    control: ControlConfig
    hmm: HMMConfig
    ir: IRConfig

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
