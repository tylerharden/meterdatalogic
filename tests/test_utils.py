"""Unit tests for timezone localization and time parsing helpers in utils."""

import pandas as pd
from datetime import time as _time

from meterdatalogic import utils, ingest


def test_safe_localize_series_naive_and_aware(rng_dst_gap):
    """Localize naive timestamps across a DST 'gap' into a tz-aware Series.

    Input: naive Series constructed from a tz-aware index (gap day).
    Expect: tz is applied without error; result remains convertible to UTC.
    """
    naive = pd.to_datetime(rng_dst_gap.tz_convert(None)).to_series(index=None)
    out = utils._safe_localize_series(naive, str(rng_dst_gap.tz))
    assert str(out.dt.tz) == str(rng_dst_gap.tz)
    # Round-trip back to UTC should not raise.
    out.dt.tz_convert("UTC")


def test_safe_localize_handles_dst_overlap(rng_dst_overlap):
    """Localize naive timestamps over a DST 'overlap' day (duplicate hour).

    Input: naive Series from an overlap range at 30‑min cadence.
    Expect: same length, correct tz set, no ambiguity errors in helper.
    """
    naive = pd.to_datetime(rng_dst_overlap.tz_convert(None)).to_series(index=None)
    out = utils._safe_localize_series(naive, str(rng_dst_overlap.tz))
    assert len(out) == len(naive)
    assert str(out.dt.tz) == str(rng_dst_overlap.tz)


def test_time_parsing_24_00_boundary():
    """Interpret '24:00' as midnight of the next day.

    Input: strings "24:00" to _parse_time_str and _parse_hhmm.
    Expect: both map to 00:00 (hour=0, minute=0).
    """
    assert utils._parse_time_str("24:00") == _time(0, 0)
    hhmm = utils._parse_hhmm("24:00")
    assert hhmm.hour == 0 and hhmm.minute == 0


def test_collapse_flows_handles_filtered_frames(canon_df_mixed_flows):
    df = ingest.from_dataframe(canon_df_mixed_flows)
    imp, exp = utils._collapse_flows(df)
    assert len(imp) == len(df.index)
    assert len(exp) == len(df.index)
    # export should be >= 0 and present when flows include 'grid_export_solar'
    assert (exp >= 0).all()
