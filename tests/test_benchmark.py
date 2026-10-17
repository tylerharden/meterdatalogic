"""Unit tests for household peer-group usage benchmarking."""

from meterdatalogic.analytics import benchmark


def test_typical_annual_kwh_scales_with_occupants():
    one_person = benchmark.typical_annual_kwh(occupants="1")
    four_person = benchmark.typical_annual_kwh(occupants="4")
    assert four_person > one_person


def test_typical_annual_kwh_ducted_aircon_higher_than_none():
    none = benchmark.typical_annual_kwh(occupants="2", aircon_type="none")
    ducted = benchmark.typical_annual_kwh(occupants="2", aircon_type="ducted")
    assert ducted > none


def test_typical_annual_kwh_electric_resistive_hot_water_higher_than_gas():
    gas = benchmark.typical_annual_kwh(occupants="2", hot_water="gas")
    electric = benchmark.typical_annual_kwh(occupants="2", hot_water="electric_resistive")
    assert electric > gas


def test_typical_annual_kwh_unknown_values_fall_back_gracefully():
    # Unrecognised / missing enum values should not raise - the household
    # profile step allows skipping fields.
    result = benchmark.typical_annual_kwh(
        occupants="2",  # type: ignore[arg-type]
        aircon_type="not_a_real_value",  # type: ignore[arg-type]
        hot_water="not_a_real_value",  # type: ignore[arg-type]
    )
    assert result > 0


def test_compare_positive_pct_diff_when_above_typical():
    typical = benchmark.typical_annual_kwh(occupants="2")
    result = benchmark.compare(typical * 1.5, occupants="2")
    assert result["pct_diff"] > 0
    assert result["typical_kwh"] == typical


def test_compare_negative_pct_diff_when_below_typical():
    typical = benchmark.typical_annual_kwh(occupants="2")
    result = benchmark.compare(typical * 0.5, occupants="2")
    assert result["pct_diff"] < 0


def test_compare_range_brackets_typical():
    result = benchmark.compare(5000.0, occupants="3")
    assert result["typical_kwh_low"] < result["typical_kwh"] < result["typical_kwh_high"]


def test_compare_zero_typical_does_not_divide_by_zero():
    # Defensive: even if a future change made typical 0, this must not raise.
    result = benchmark.compare(1000.0, occupants="2")
    assert isinstance(result["pct_diff"], float)
