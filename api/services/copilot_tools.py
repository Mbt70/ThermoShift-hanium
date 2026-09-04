"""ThermoShift 운영 코파일럿이 사용할 제한된 도구 계약.

이 모듈의 도구는 조회·계산 또는 제어 *제안*만 수행한다. MQTT 발행이나
hvac_commands INSERT는 하지 않는다. 실제 실행은 기존 인증된 제어 API와
gateway 안전 정책을 반드시 거친다.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from ml.mpc_controller import ModelPredictiveController
from ml.thermal_model import ThermalModel

_ROOT = Path(__file__).resolve().parents[2]
_THERMAL_PARAMS = _ROOT / "ml" / "params" / "thermal.json"


TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "get_live_snapshot",
        "scope": "READ_ONLY",
        "description": "최신 온도·습도·CO₂·재실·문·전력과 측정 시각 조회",
        "arguments": {},
    },
    {
        "name": "get_recent_decisions",
        "scope": "READ_ONLY",
        "description": "최근 제어 판단과 근거 조회",
        "arguments": {"limit": "1~20, 기본 5"},
    },
    {
        "name": "get_experiment_status",
        "scope": "READ_ONLY",
        "description": "최근 실험 run, 품질 범위와 진행 상태 조회",
        "arguments": {},
    },
    {
        "name": "get_model_status",
        "scope": "READ_ONLY",
        "description": "열모델이 실측 교정값인지 가정값인지 조회",
        "arguments": {},
    },
    {
        "name": "simulate_mpc",
        "scope": "SIMULATION_ONLY",
        "description": "장치를 작동시키지 않고 쾌적도·에너지 목적함수 계산",
        "arguments": {
            "temperature_c": "10~45",
            "humidity_pct": "0~100",
            "p_occupied": "0~1",
            "current_cooling_on": "boolean, 기본 false",
        },
    },
    {
        "name": "propose_control_action",
        "scope": "PROPOSAL_ONLY",
        "description": "제어 명령을 실행하지 않고 사용자 승인 카드 생성",
        "arguments": {
            "command_type": "power_off|power_on|set_temp",
            "target_temp": "set_temp일 때 16~30",
            "reason": "제안 근거",
        },
    },
)

TOOL_NAMES = frozenset(tool["name"] for tool in TOOL_DEFINITIONS)


def get_model_status() -> dict[str, Any]:
    if _THERMAL_PARAMS.exists():
        try:
            model = ThermalModel.load(_THERMAL_PARAMS)
            source = "ml/params/thermal.json"
        except (OSError, ValueError, TypeError):
            model = ThermalModel()
            source = "fallback_after_invalid_parameter_file"
    else:
        model = ThermalModel()
        source = "built_in_assumption"
    return {
        "model": "first_order_rc",
        "source": source,
        "calibrated": model.calibrated,
        "a_per_min": model.a,
        "b_c_per_min": model.b,
        "d_c_per_min": model.d,
        "time_constant_min": round(model.time_constant_min, 2),
        "r2": model.r2,
        "control_use": "VALIDATED" if model.calibrated else "ASSUMPTION_ONLY",
    }


def simulate_mpc(arguments: dict[str, Any]) -> dict[str, Any]:
    temperature = float(arguments["temperature_c"])
    humidity = float(arguments["humidity_pct"])
    p_occupied = float(arguments["p_occupied"])
    if not 10 <= temperature <= 45:
        raise ValueError("temperature_c must be between 10 and 45")
    if not 0 <= humidity <= 100:
        raise ValueError("humidity_pct must be between 0 and 100")
    if not 0 <= p_occupied <= 1:
        raise ValueError("p_occupied must be between 0 and 1")

    model_status = get_model_status()
    model = (
        ThermalModel.load(_THERMAL_PARAMS)
        if _THERMAL_PARAMS.exists() and model_status["source"] == "ml/params/thermal.json"
        else ThermalModel()
    )
    result = ModelPredictiveController().solve(
        current_temp_c=temperature,
        humidity_pct=humidity,
        p_occupied=p_occupied,
        thermal_model=model,
        current_cooling_on=bool(arguments.get("current_cooling_on", False)),
    )
    payload = asdict(result)
    payload["scope"] = "SIMULATION_ONLY"
    payload["model_status"] = model_status
    payload["device_command_created"] = False
    return payload


def propose_control_action(room_id: int, arguments: dict[str, Any]) -> dict[str, Any]:
    command_type = str(arguments.get("command_type", "")).strip().lower()
    if command_type not in {"power_off", "power_on", "set_temp"}:
        raise ValueError("unsupported command_type")
    target = arguments.get("target_temp")
    if command_type == "set_temp":
        if target is None or not 16 <= float(target) <= 30:
            raise ValueError("set_temp requires target_temp between 16 and 30")
        target = float(target)
    else:
        target = None

    reason = str(arguments.get("reason") or "운영 코파일럿 제안")[:300]
    return {
        "scope": "PROPOSAL_ONLY",
        "requires_explicit_user_approval": True,
        "executed": False,
        "room_id": room_id,
        "command": {
            "command_type": command_type,
            "target_temp": target,
            "control_mode": "manual",
            "payload": {"source": "copilot_approved_proposal", "reason": reason},
        },
        "approval_endpoint": f"/rooms/{room_id}/commands",
        "safety_contract": [
            "demo session cannot approve",
            "API ownership check required",
            "gateway active/manual mode check required",
            "gateway lockout and command rate limit remain authoritative",
            "result is not ACK until device feedback verifies it",
        ],
    }
