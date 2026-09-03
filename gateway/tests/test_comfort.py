import pytest

from ml.comfort_model import PMV_COMFORT_LIMIT, calculate_pmv, calculate_pmv_value


def test_reference_office_condition_is_near_neutral():
    # Fanger PMV reference-style condition: ta=tr=25C, RH=50%, v=0.1,
    # met=1.1, clo=0.5. A broad tolerance protects against rounding details.
    result = calculate_pmv(25.0, 50.0)
    assert result.pmv == pytest.approx(-0.13, abs=0.05)
    assert result.ppd == pytest.approx(5.4, abs=0.5)


def test_setback_is_derived_from_pmv_band_not_fixed_delta():
    result = calculate_pmv(25.0, 50.0)
    assert calculate_pmv_value(result.optimal_temp_c, 50.0) == pytest.approx(0.0, abs=0.05)
    assert abs(calculate_pmv_value(result.setback_temp_c, 50.0)) <= PMV_COMFORT_LIMIT
    assert result.setback_temp_c > result.optimal_temp_c


def test_invalid_humidity_is_rejected():
    with pytest.raises(ValueError):
        calculate_pmv(25.0, 101.0)
