from pydantic import BaseModel
from typing import Optional, Any, List, Dict
from datetime import datetime

class EnvData(BaseModel):
    device_id: str
    timestamp: datetime
    temperature_c: Optional[float] = None
    humidity_rh: Optional[float] = None
    co2_ppm: Optional[float] = None

class OccData(BaseModel):
    device_id: str
    timestamp: datetime
    pir: bool
    door: str
    door_event: bool

class IrData(BaseModel):
    device_id: str
    timestamp: datetime
    protocol: Optional[str] = None
    raw: Optional[Any] = None
    code_hash: str

class OccupancyProbabilities(BaseModel):
    empty: float
    transition: float
    occupied: float

class ControlDecision(BaseModel):
    timestamp: datetime
    control_mode: str
    occupancy_state: str
    occupancy_probabilities: OccupancyProbabilities
    temperature_c: Optional[float] = None
    co2_ppm: Optional[float] = None
    proposed_action: str
    executed: bool
    reason_codes: List[str]
