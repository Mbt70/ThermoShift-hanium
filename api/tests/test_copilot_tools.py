import pytest
from types import SimpleNamespace

from api.routers.ai import _fallback_copilot_plan
from api.services import ai, copilot_tools


def test_도구_이름은_고정된_허용목록이다():
    names = [tool["name"] for tool in copilot_tools.TOOL_DEFINITIONS]
    assert len(names) == len(set(names))
    assert set(names) == set(copilot_tools.TOOL_NAMES)
    assert all(tool["scope"] in {"READ_ONLY", "SIMULATION_ONLY", "PROPOSAL_ONLY"}
               for tool in copilot_tools.TOOL_DEFINITIONS)


def test_제어도구는_명령을_실행하지_않고_승인카드만_만든다():
    proposal = copilot_tools.propose_control_action(
        1, {"command_type": "set_temp", "target_temp": 25, "reason": "PMV 검토"}
    )
    assert proposal["scope"] == "PROPOSAL_ONLY"
    assert proposal["executed"] is False
    assert proposal["requires_explicit_user_approval"] is True
    assert proposal["command"]["target_temp"] == 25.0
    assert proposal["approval_endpoint"] == "/rooms/1/commands"
    assert proposal["proposal_type"] == "hvac_command"
    assert proposal["command"]["payload"]["proposal_id"] == proposal["proposal_id"]


def test_제어제안도_허용범위를_벗어나면_거절한다():
    with pytest.raises(ValueError, match="target_temp"):
        copilot_tools.propose_control_action(
            1, {"command_type": "set_temp", "target_temp": 40}
        )


def test_MPC도구는_시뮬레이션만_하고_명령을_만들지_않는다():
    result = copilot_tools.simulate_mpc({
        "temperature_c": 26.0,
        "humidity_pct": 55.0,
        "p_occupied": 0.8,
    })
    assert result["scope"] == "SIMULATION_ONLY"
    assert result["device_command_created"] is False
    assert result["pareto_metrics"]["objective_has_temperature_tracking_term"] is False


def test_MPC도구는_비현실적_입력을_거절한다():
    with pytest.raises(ValueError, match="temperature_c"):
        copilot_tools.simulate_mpc({
            "temperature_c": 60,
            "humidity_pct": 55,
            "p_occupied": 0.5,
        })


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("왜 냉방을 껐어?", "get_recent_decisions"),
        ("현재 모델 학습 상태 알려줘", "get_model_status"),
        ("지금 값으로 MPC 시뮬레이션해줘", "simulate_mpc"),
        ("실험 run 상태 알려줘", "get_experiment_status"),
        ("최근 실험 데이터 품질 알려줘", "get_data_quality"),
        ("run 7 품질 확인해줘", "get_data_quality"),
        ("내일 실험 가능한지 준비 상태 알려줘", "get_experiment_readiness"),
        ("pilot 실험 시작해줘", "propose_experiment_start"),
        ("실험 중단해줘", "propose_experiment_stop"),
        ("현재 상태 어때?", "get_live_snapshot"),
    ],
)
def test_AI가_없어도_안전한_도구를_고른다(message, expected):
    tool, _arguments = _fallback_copilot_plan(message)
    assert tool == expected


def test_자연어_제어요청도_실행이_아닌_제안으로_변환한다():
    tool, arguments = _fallback_copilot_plan("25도로 설정 변경해줘")
    assert tool == "propose_control_action"
    assert arguments["command_type"] == "set_temp"
    assert arguments["target_temp"] == 25.0


def test_run_번호를_데이터_품질_도구_인자로_추출한다():
    tool, arguments = _fallback_copilot_plan("run #42 데이터 품질 확인해줘")
    assert tool == "get_data_quality"
    assert arguments == {"run_id": 42}


def test_실험_시작_제안은_run이나_MQTT를_만들지_않는다():
    readiness = {"ready": True, "checks": []}
    proposal = copilot_tools.propose_experiment_start(
        1, {"plan_key": "pilot20", "reason": "내일 파일럿"}, readiness
    )
    assert proposal["scope"] == "PROPOSAL_ONLY"
    assert proposal["proposal_type"] == "experiment_start"
    assert proposal["executed"] is False
    assert proposal["approval_supported"] is False
    assert proposal["experiment"]["duration_min"] == 20


def test_지원하지_않는_실험_계획은_거절한다():
    with pytest.raises(ValueError, match="plan_key"):
        copilot_tools.propose_experiment_start(
            1, {"plan_key": "overnight"}, {"ready": True}
        )


def test_실험_중단도_제안만_만든다():
    proposal = copilot_tools.propose_experiment_stop(
        1, {"reason": "온도 확인"}, {"run_id": 9, "plan_name": "pilot_20min"}
    )
    assert proposal["proposal_type"] == "experiment_stop"
    assert proposal["executed"] is False
    assert proposal["experiment"]["run_id"] == 9


def test_Gemini_계획_스키마는_Developer_API가_거절하는_자유_dict가_없다():
    def keys(value):
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value), set())
        return set()

    assert "additionalProperties" not in keys(
        ai._GeminiCopilotToolPlan.model_json_schema()
    )


def test_Gemini_고정_응답을_내부_도구_인자로_변환한다(monkeypatch):
    raw = ai._GeminiCopilotToolPlan(
        tool_name="get_data_quality",
        selection_reason="최근 run의 학습 적합성 확인",
        run_id=7,
    )
    monkeypatch.setattr(ai, "_call", lambda *_args, **_kwargs: raw)
    plan = ai.plan_copilot_tool("run 7 품질 확인", copilot_tools.TOOL_DEFINITIONS)
    assert plan is not None
    assert plan.tool_name == "get_data_quality"
    assert plan.arguments == {"run_id": 7}
    assert plan.attempts == 1


def test_Gemini_첫_호출이_실패하면_한번_재시도한다(monkeypatch):
    calls = []
    raw = ai._GeminiCopilotToolPlan(
        tool_name="get_live_snapshot",
        selection_reason="현재 상태 확인",
    )

    def fake_call(*args, **kwargs):
        calls.append((args, kwargs))
        return None if len(calls) == 1 else raw

    monkeypatch.setattr(ai, "_call", fake_call)
    plan = ai.plan_copilot_tool("현재 상태 알려줘", copilot_tools.TOOL_DEFINITIONS)

    assert plan is not None
    assert plan.tool_name == "get_live_snapshot"
    assert plan.attempts == 2
    assert len(calls) == 2


def test_Gemini가_허용되지_않은_도구를_고르면_재시도한다(monkeypatch):
    invalid = ai._GeminiCopilotToolPlan(
        tool_name="turn_relay_on_directly",
        selection_reason="잘못된 직접 실행",
    )
    valid = ai._GeminiCopilotToolPlan(
        tool_name="propose_control_action",
        selection_reason="승인 가능한 제어 제안",
        command_type="power_on",
    )
    responses = iter((invalid, valid))
    monkeypatch.setattr(ai, "_call", lambda *_args, **_kwargs: next(responses))

    plan = ai.plan_copilot_tool("냉각 켜줘", copilot_tools.TOOL_DEFINITIONS)

    assert plan is not None
    assert plan.tool_name == "propose_control_action"
    assert plan.arguments["command_type"] == "power_on"
    assert plan.attempts == 2


def test_Gemini_JSON은_API_스키마_기능없이_서버에서_검증한다(monkeypatch):
    captured = {}

    class Models:
        @staticmethod
        def generate_content(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                candidates=[SimpleNamespace(finish_reason="STOP")],
                prompt_feedback=None,
                text=(
                    '{"tool_name":"get_live_snapshot",'
                    '"selection_reason":"현재 상태 조회"}'
                ),
            )

    monkeypatch.setattr(ai, "is_available", lambda: True)
    monkeypatch.setattr(ai, "_get_client", lambda: SimpleNamespace(models=Models()))
    monkeypatch.setattr(ai, "MODEL", "gemini-3.5-flash-lite")

    result = ai._call("상태를 확인해줘", ai._GeminiCopilotToolPlan, effort="instant")

    assert result.tool_name == "get_live_snapshot"
    assert captured["config"].response_schema is None
    assert captured["config"].automatic_function_calling.disable is True
    assert "JSON Schema" in captured["contents"]
