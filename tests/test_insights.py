"""Tests for insights evaluators (intermediate and advanced).

Covers the two evaluators refactored to use transform.aggregate:
  - peak_demand_characteristics  (evaluators_intermediate)
  - step_change_baseload         (evaluators_advanced)
"""

import numpy as np
import pandas as pd

from meterdatalogic import ingest
from meterdatalogic.analytics.insights import InsightConfig
from meterdatalogic.analytics.insights import evaluators_intermediate, evaluators_advanced

TZ = "Australia/Brisbane"


def _import_df(rng, kwh=0.5) -> pd.DataFrame:
    """Build a minimal canonical import-only DataFrame."""
    return pd.DataFrame(
        {"t_start": rng, "nmi": "Q1234567890", "channel": "E1", "kwh": kwh}
    ).set_index("t_start")


# ------------------------------------------------------------------
# peak_demand_characteristics
# ------------------------------------------------------------------


def test_peak_demand_characteristics_returns_none_on_empty():
    """Empty frame returns None immediately."""
    df = ingest.from_dataframe(
        pd.DataFrame(columns=["nmi", "channel", "kwh"]).set_index(
            pd.DatetimeIndex([], name="t_start", tz=TZ)
        )
    )
    assert evaluators_intermediate.peak_demand_characteristics(df, config=InsightConfig()) is None


def test_peak_demand_characteristics_returns_none_if_too_short():
    """Fewer than 7 days → returns None (not enough data for reliable p95)."""
    rng = pd.date_range("2025-01-01", periods=48 * 3, freq="30min", tz=TZ)
    df = ingest.from_dataframe(_import_df(rng))
    assert evaluators_intermediate.peak_demand_characteristics(df, config=InsightConfig()) is None


def test_peak_demand_characteristics_returns_insight_with_14_days():
    """14 days of uniform import produces a stable-demand insight with valid metrics."""
    rng = pd.date_range("2025-01-01", periods=48 * 14, freq="30min", tz=TZ)
    df = ingest.from_dataframe(_import_df(rng, kwh=0.5))
    result = evaluators_intermediate.peak_demand_characteristics(df, config=InsightConfig())
    assert result is not None
    assert result.id == "peak_demand_characteristics"
    assert result.metrics["mean_peak_kw"] > 0
    assert result.metrics["p95_peak_kw"] >= result.metrics["mean_peak_kw"]
    # Uniform load → p95 == mean → spiky_ratio == 1.0 → "info" severity
    assert result.severity == "info"


def test_peak_demand_characteristics_spiky_data_triggers_warning():
    """A single very-high-demand day inflates p95 well above mean → warning."""
    rng = pd.date_range("2025-01-01", periods=48 * 14, freq="30min", tz=TZ)
    kwh = np.full(len(rng), 0.2)
    # Spike one day during the demand window
    for i, ts in enumerate(rng):
        if ts.date() == pd.Timestamp("2025-01-04").date() and 16 <= ts.hour < 21:
            kwh[i] = 5.0
    df = ingest.from_dataframe(_import_df(rng, kwh=kwh))
    result = evaluators_intermediate.peak_demand_characteristics(df, config=InsightConfig())
    assert result is not None
    assert result.severity == "warning"
    assert result.metrics["spiky_ratio"] >= InsightConfig().intermediate.spiky_ratio_threshold


# ------------------------------------------------------------------
# step_change_baseload
# ------------------------------------------------------------------


def test_step_change_baseload_returns_none_on_empty():
    """Empty frame returns None immediately."""
    df = ingest.from_dataframe(
        pd.DataFrame(columns=["nmi", "channel", "kwh"]).set_index(
            pd.DatetimeIndex([], name="t_start", tz=TZ)
        )
    )
    assert evaluators_advanced.step_change_baseload(df, config=InsightConfig()) is None


def test_step_change_baseload_returns_none_if_too_short():
    """Fewer than 30 days → returns None before even aggregating."""
    rng = pd.date_range("2025-01-01", periods=48 * 20, freq="30min", tz=TZ)
    df = ingest.from_dataframe(_import_df(rng))
    assert evaluators_advanced.step_change_baseload(df, config=InsightConfig()) is None


def test_step_change_baseload_no_insight_on_uniform_data():
    """60 days of uniform overnight load → no step change detected."""
    rng = pd.date_range("2025-01-01", periods=48 * 60, freq="30min", tz=TZ)
    df = ingest.from_dataframe(_import_df(rng, kwh=0.4))
    result = evaluators_advanced.step_change_baseload(df, config=InsightConfig())
    assert result is None


def test_step_change_baseload_detects_step_up():
    """Overnight usage doubling in the second half triggers an insight."""
    # First 30 days at low usage, last 30 days at high usage.
    rng_low = pd.date_range("2025-01-01", periods=48 * 30, freq="30min", tz=TZ)
    rng_high = pd.date_range("2025-02-01", periods=48 * 30, freq="30min", tz=TZ)
    df_low = _import_df(rng_low, kwh=0.2)
    df_high = _import_df(rng_high, kwh=0.6)
    df = ingest.from_dataframe(pd.concat([df_low, df_high]))
    result = evaluators_advanced.step_change_baseload(df, config=InsightConfig())
    assert result is not None
    assert result.id == "step_change_baseload"
    # Overnight sum: before = 10 × 0.2 = 2.0, after = 10 × 0.6 = 6.0 → ~66% change
    assert result.metrics["change_pct"] >= InsightConfig().advanced.step_change_pct_threshold


def test_step_change_baseload_detects_step_down():
    """A sustained decrease also triggers the insight."""
    rng_high = pd.date_range("2025-01-01", periods=48 * 30, freq="30min", tz=TZ)
    rng_low = pd.date_range("2025-02-01", periods=48 * 30, freq="30min", tz=TZ)
    df_high = _import_df(rng_high, kwh=0.6)
    df_low = _import_df(rng_low, kwh=0.2)
    df = ingest.from_dataframe(pd.concat([df_high, df_low]))
    result = evaluators_advanced.step_change_baseload(df, config=InsightConfig())
    assert result is not None
    assert "decrease" in result.message
