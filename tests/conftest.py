"""Shared pytest fixtures for time ranges, DST edge cases, and canonical frames.

- tz_sydney/rng_dst_*: Cover DST gap (spring forward) and overlap (fall back).
- halfhour_rng: 7 days of 30‑min Brisbane data (no DST) for fast, stable tests.
- canon_df_*: Minimal canonical frames used by validate/transform/pricing tests.
- tou_bands_basic: Simple ToU band set for transform/pricing.
"""

import pandas as pd
import pytest

TZ = "Australia/Brisbane"


@pytest.fixture
def tz_sydney():
    """Return a timezone with DST to exercise gap/overlap behavior."""
    return "Australia/Sydney"


@pytest.fixture
def rng_dst_gap(tz_sydney):
    """A tz-aware hourly range through the DST 'gap' day (one hour skipped)."""
    # Spring forward: 2024-10-06 02:00 local is skipped in Australia/Sydney.
    return pd.date_range("2024-10-06 00:00", periods=6, freq="h", tz=tz_sydney)


@pytest.fixture
def rng_dst_overlap(tz_sydney):
    """A tz-aware 30‑min range through the DST 'overlap' (duplicate hour)."""
    # Fall back: 2024-04-07 02:00 repeats in Australia/Sydney.
    return pd.date_range("2024-04-07 00:00", periods=10, freq="30min", tz=tz_sydney)


@pytest.fixture
def halfhour_rng():
    """A stable, no-DST 7-day 30‑min index used across tests."""
    return pd.date_range("2025-01-01", periods=48 * 7, freq="30min", tz=TZ)


@pytest.fixture
def canon_df_one_nmi(halfhour_rng):
    """Canonical frame for a single NMI with import-only E1 channel."""
    df = pd.DataFrame(
        {"t_start": halfhour_rng, "nmi": "Q1234567890", "channel": "E1", "kwh": 0.5}
    ).set_index("t_start")
    return df


@pytest.fixture
def canon_df_mixed_flows(halfhour_rng):
    """Canonical frame with interleaved import/export to test flow collapsing."""
    df = pd.DataFrame(
        {
            "t_start": halfhour_rng,
            "nmi": "Q1234567890",
            "channel": ["E1" if i % 2 == 0 else "B1" for i in range(len(halfhour_rng))],
            "kwh": 0.5,
        }
    ).set_index("t_start")
    return df


@pytest.fixture
def tou_bands_basic():
    """Three non-overlapping bands that cover the entire day."""
    return [
        {"name": "off", "start": "00:00", "end": "16:00"},
        {"name": "peak", "start": "16:00", "end": "21:00"},
        {"name": "shoulder", "start": "21:00", "end": "24:00"},
    ]
