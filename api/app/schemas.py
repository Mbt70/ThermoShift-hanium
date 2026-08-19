"""요청/응답 스키마."""

from typing import Optional
from pydantic import BaseModel, Field


# --- 인증 ---

class RegisterRequest(BaseModel):
    name: str = Field(min_length=1)
    email: str
    password: str = Field(min_length=4)


class LoginRequest(BaseModel):
    email: str
    password: str


class UserUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    password: Optional[str] = Field(default=None, min_length=4)


# --- 공간 ---

class RoomCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    location: str = ""
    floor_plan_name: Optional[str] = None
    owner_email: str


class RoomUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    location: Optional[str] = None
    floor_plan_name: Optional[str] = None
    target_temperature: Optional[float] = Field(default=None, ge=16, le=30)
    control_mode: Optional[str] = Field(default=None, pattern="^(rule|manual|predict)$")
    auto_control: Optional[bool] = None


# --- 디바이스 ---

class DeviceUpdateRequest(BaseModel):
    room_id: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = Field(default=None, pattern="^(env|pir|door|ir|plug)$")
    location: Optional[str] = None
    enabled: Optional[bool] = None


# --- 제어 ---

class CommandRequest(BaseModel):
    action: str = Field(min_length=1)          # POWER_OFF | COOL_24_AUTO | SET_TARGET ...
    method: str = Field(default="manual", pattern="^(rule|manual|predict)$")
    issued_by: Optional[str] = None
    payload: Optional[dict] = None


class CommandStatusUpdate(BaseModel):
    status: str = Field(pattern="^(pending|sent|failed)$")
    error_code: Optional[str] = None


# --- 예약 ---

class ScheduleRequest(BaseModel):
    title: str = ""
    date: str                                   # YYYY-MM-DD
    start_time: str                             # HH:MM
    end_time: str
    target_temperature: float = Field(default=24.0, ge=16, le=30)
    precool_enabled: bool = False
    precool_minutes_before: int = 20
    repeat_enabled: bool = False
    repeat_days: list[str] = Field(default_factory=list)
