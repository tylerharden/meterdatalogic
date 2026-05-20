"""Shared pytest fixtures for time ranges, DST edge cases, and canonical frames."""

import polars as pl
import pytest
import datetime as _dt

TZ = "Australia/Brisbane"


def _ts_range(start: str, periods: int, freq_min: int, tz: str) -> pl.Series:
    """Build a tz-aware Datetime Series at the given minute cadence.

    Non-existent times (DST spring-forward gap) are dropped, so the
    returned Series may be shorter than `periods` in DST-gap scenarios.
    """
    base = _dt.datetime.fromisoformat(start)
    times = [base + _dt.timedelta(minutes=freq_min * i) for i in range(periods)]
    s = pl.Series(times, dtype=pl.Datetime("us")).dt.replace_time_zone(
        tz, non_existent="null", ambiguous="earliest"
    )
    return s.drop_nulls()


@pytest.fixture
def tz_sydney():
    return "Australia/Sydney"


@pytest.fixture
def rng_dst_gap(tz_sydney):
    """Hourly range through the DST 'gap' day (spring forward) in Australia/Sydney."""
    return _ts_range("2024-10-06T00:00:00", 6, 60, tz_sydney)


@pytest.fixture
def rng_dst_overlap(tz_sydney):
    """30-min range through the DST 'overlap' (fall back) in Australia/Sydney."""
    return _ts_range("2024-04-07T00:00:00", 10, 30, tz_sydney)


@pytest.fixture
def halfhour_rng():
    """A stable, no-DST 7-day 30-min Datetime Series in Australia/Brisbane."""
    return _ts_range("2025-01-01T00:00:00", 48 * 7, 30, TZ)


@pytest.fixture
def canon_df_one_nmi(halfhour_rng):
    """Canonical frame for a single NMI with import-only E1 channel."""
    n = len(halfhour_rng)
    return pl.DataFrame(
        {
            "t_start": halfhour_rng,
            "nmi": pl.Series(["Q1234567890"] * n, dtype=pl.String),
            "channel": pl.Series(["E1"] * n, dtype=pl.String),
            "flow": pl.Series(["grid_import"] * n, dtype=pl.String),
            "kwh": pl.Series([0.5] * n, dtype=pl.Float64),
            "cadence_min": pl.Series([30] * n, dtype=pl.Int32),
        }
    )


@pytest.fixture
def canon_df_mixed_flows(halfhour_rng):
    """Canonical frame with interleaved import/export to test flow collapsing."""
    n = len(halfhour_rng)
    channels = ["E1" if i % 2 == 0 else "B1" for i in range(n)]
    flows = ["grid_import" if i % 2 == 0 else "grid_export_solar" for i in range(n)]
    return pl.DataFrame(
        {
            "t_start": halfhour_rng,
            "nmi": pl.Series(["Q1234567890"] * n, dtype=pl.String),
            "channel": pl.Series(channels, dtype=pl.String),
            "flow": pl.Series(flows, dtype=pl.String),
            "kwh": pl.Series([0.5] * n, dtype=pl.Float64),
            "cadence_min": pl.Series([30] * n, dtype=pl.Int32),
        }
    )


@pytest.fixture
def tou_bands_basic():
    """Three non-overlapping bands that cover the entire day."""
    return [
        {"name": "off", "start": "00:00", "end": "16:00"},
        {"name": "peak", "start": "16:00", "end": "21:00"},
        {"name": "shoulder", "start": "21:00", "end": "24:00"},
    ]
