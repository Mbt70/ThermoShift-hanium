"""ThermoShift 운영 코파일럿이 사용할 제한된 도구 계약.

이 모듈의 도구는 조회·계산 또는 제어 *제안*만 수행한다. MQTT 발행이나
hvac_commands INSERT는 하지 않는다. 실제 실행은 기존 인증된 제어 API와
gateway 안전 정책을 반드시 거친다.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

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
        "name": "get_data_quality",
        "scope": "READ_ONLY",
        "description": "실험 run의 표본 수·간격·온도 변화·입력 검증 상태와 학습 적합성 조회",
        "arguments": {"run_id": "양의 정수, 생략하면 해당 공간의 최근 run"},
    },
    {
        "name": "get_experiment_readiness",
        "scope": "READ_ONLY",
        "description": "실험 전 센서 최신성·장치 연결·중복 run·명령 큐 점검",
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
    {
        "name": "propose_experiment_start",
        "scope": "PROPOSAL_ONLY",
        "description": "실험을 시작하지 않고 계획·수동 작업·사전점검 승인 카드 생성",
        "arguments": {"plan_key": "pilot20|calib|prbs, 기본 pilot20", "reason": "제안 근거"},
    },
    {
        "name": "propose_experiment_stop",
        "scope": "PROPOSAL_ONLY",
        "description": "진행 중인 실험을 중단하지 않고 중단 제안 카드 생성",
        "arguments": {"reason": "중단 제안 근거"},
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
    proposal_id = str(uuid4())
    return {
        "scope": "PROPOSAL_ONLY",
        "proposal_type": "hvac_command",
        "approval_supported": True,
        "requires_explicit_user_approval": True,
        "executed": False,
        "room_id": room_id,
        "command": {
            "command_type": command_type,
            "target_temp": target,
            "control_mode": "manual",
            "payload": {
                "source": "copilot_approved_proposal",
                "proposal_id": proposal_id,
                "reason": reason,
            },
        },
        "proposal_id": proposal_id,
        "approval_endpoint": f"/rooms/{room_id}/commands",
        "safety_contract": [
            "demo session cannot approve",
            "API ownership check required",
            "gateway active/manual mode check required",
            "gateway lockout and command rate limit remain authoritative",
            "result is not ACK until device feedback verifies it",
            "relay ACK verifies ON/OFF state, not target-temperature achievement",
        ],
    }


_EXPERIMENT_PLANS: dict[str, dict[str, Any]] = {
    "pilot20": {
        "plan_name": "pilot_20min",
        "duration_min": 20,
        "purpose": "센서·문·히터·냉각 이벤트의 타임스탬프와 데이터 경로 점검",
        "manual_actions": [
            "+3분 히터 ON, +8분 히터 OFF",
            "+11분 문 열기, +12분 문 닫기",
            "+15분 펠티어 ON, +18분 펠티어 OFF",
        ],
    },
    "calib": {
        "plan_name": "compact_calibration",
        "duration_min": 45,
        "purpose": "RC 모델의 히터 감도·표류·감쇠 파라미터 식별",
        "manual_actions": [
            "+10분 히터 ON, +25분 히터 OFF",
            "45분 동안 문을 닫고 다른 열 입력을 만들지 않기",
        ],
    },
    "prbs": {
        "plan_name": "prbs",
        "duration_min": 310,
        "purpose": "교정 이후 동특성 식별을 위한 장시간 다중 입력 데이터 수집",
        "manual_actions": [
            "PRBS는 단순 수동 ON/OFF 히터로 정확히 재현하기 어려우므로 자동 duty 제어 준비 필요",
        ],
    },
}


def propose_experiment_start(
    room_id: int,
    arguments: dict[str, Any],
    readiness: dict[str, Any],
) -> dict[str, Any]:
    plan_key = str(arguments.get("plan_key") or "pilot20").strip().lower()
    if plan_key not in _EXPERIMENT_PLANS:
        raise ValueError("plan_key must be one of pilot20, calib, prbs")
    plan = _EXPERIMENT_PLANS[plan_key]
    return {
        "scope": "PROPOSAL_ONLY",
        "proposal_type": "experiment_start",
        "approval_supported": False,
        "requires_explicit_user_approval": True,
        "executed": False,
        "room_id": room_id,
        "experiment": {"plan_key": plan_key, **plan},
        "readiness": readiness,
        "reason": str(arguments.get("reason") or "운영 코파일럿 실험 제안")[:300],
        "blocked_from_execution": True,
        "blocked_reason": (
            "장치 상태와 수동 히터 동작을 사람이 확인해야 하므로 코파일럿 실행은 아직 연결하지 않았습니다."
        ),
        "safety_contract": [
            "this response does not create an experiment run",
            "this response does not publish MQTT",
            "manual heater and door events require timestamped operator confirmation",
            "readiness must be rechecked immediately before a real run",
        ],
    }


def propose_experiment_stop(
    room_id: int,
    arguments: dict[str, Any],
    active_experiment: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "scope": "PROPOSAL_ONLY",
        "proposal_type": "experiment_stop",
        "approval_supported": False,
        "requires_explicit_user_approval": True,
        "executed": False,
        "room_id": room_id,
        "experiment": active_experiment,
        "reason": str(arguments.get("reason") or "운영 코파일럿 실험 중단 제안")[:300],
        "blocked_from_execution": True,
        "blocked_reason": (
            "중단 시 안전한 출력 OFF와 실제 장치 확인이 필요하므로 코파일럿 실행은 아직 연결하지 않았습니다."
        ),
        "safety_contract": [
            "this response does not update experiment_runs",
            "this response does not publish heater or cooling OFF",
            "operator must verify physical outputs after a real stop",
        ],
    }
