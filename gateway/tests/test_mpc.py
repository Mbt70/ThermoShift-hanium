import pytest

from ml.mpc_controller import ModelPredictiveController


def test_off_first_step_returns_power_off_not_cooling_command():
    controller = ModelPredictiveController()
    result = controller.solve(
        current_temp_c=24.5,
        humidity_pct=45.0,
        p_occupied=0.95,
        current_cooling_on=True,
    )

    if result.decision_type == "setback":
        assert result.optimal_action == "POWER_OFF"


def test_reported_improvements_are_labeled_as_simulation():
    result = ModelPredictiveController().solve(
        current_temp_c=28.0,
        humidity_pct=60.0,
        p_occupied=0.9,
    )

    assert result.pareto_metrics["scope"] == "SIMULATION_ESTIMATE"
    assert "compressor_switch_reduction_pct" not in result.pareto_metrics
    assert result.pareto_metrics["heat_feedforward_status"] == "CALIBRATED_INPUT_REQUIRED"
    assert result.pareto_metrics["energy_basis"] == "RUNTIME_PROXY_POWER_CALIBRATION_REQUIRED"
    assert result.pareto_metrics["optimized_energy_wh"] is None
    assert result.pareto_metrics["objective_has_temperature_tracking_term"] is False
    assert result.pareto_metrics["pmv_comfort_limit"] == 0.5
    assert sum(result.pareto_metrics["objective_terms"].values()) == pytest.approx(
        result.objective_cost, abs=0.02
    )


def test_configured_actuator_power_reports_energy_in_wh():
    result = ModelPredictiveController(actuator_power_w=42.0).solve(
        current_temp_c=28.0,
        humidity_pct=60.0,
        p_occupied=0.9,
    )

    expected_wh = 42.0 * result.pareto_metrics["optimized_runtime_min"] / 60.0
    assert result.pareto_metrics["energy_basis"] == "CONFIGURED_ACTUATOR_POWER"
    assert result.pareto_metrics["optimized_energy_wh"] == pytest.approx(expected_wh)


def test_weights_expose_the_comfort_energy_tradeoff():
    energy_first = ModelPredictiveController(
        w_energy=10.0, w_comfort=0.1, w_switch=0.0
    ).solve(28.0, 50.0, 0.9)
    comfort_first = ModelPredictiveController(
        w_energy=0.1, w_comfort=20.0, w_switch=0.0
    ).solve(28.0, 50.0, 0.9)

    assert energy_first.pareto_metrics["optimized_runtime_min"] < (
        comfort_first.pareto_metrics["optimized_runtime_min"]
    )
    assert abs(energy_first.predicted_pmv_60min) > abs(
        comfort_first.predicted_pmv_60min
    )
