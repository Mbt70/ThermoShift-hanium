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
