import pytest

from api.routers.ai import _fallback_copilot_plan
from api.services import copilot_tools


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
