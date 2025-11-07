"""Unit tests for timezone localization and time parsing helpers in utils."""

import pandas as pd

from meterdatalogic import utils


def test_safe_localize_series_naive_and_aware(rng_dst_gap):
    """Localize naive timestamps across a DST 'gap' into a tz-aware Series.

    Input: naive Series constructed from a tz-aware index (gap day).
    Expect: tz is applied without error; result remains convertible to UTC.
    """
    naive = pd.to_datetime(rng_dst_gap.tz_convert(None)).to_series(index=None)
    out = utils.safe_localize_series(naive, str(rng_dst_gap.tz))
    assert str(out.dt.tz) == str(rng_dst_gap.tz)
    # Round-trip back to UTC should not raise.
    out.dt.tz_convert("UTC")


def test_safe_localize_handles_dst_overlap(rng_dst_overlap):
    """Localize naive timestamps over a DST 'overlap' day (duplicate hour).

    Input: naive Series from an overlap range at 30‑min cadence.
    Expect: same length, correct tz set, no ambiguity errors in helper.
    """
    naive = pd.to_datetime(rng_dst_overlap.tz_convert(None)).to_series(index=None)
    out = utils.safe_localize_series(naive, str(rng_dst_overlap.tz))
    assert len(out) == len(naive)
    assert str(out.dt.tz) == str(rng_dst_overlap.tz)
