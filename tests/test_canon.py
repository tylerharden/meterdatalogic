"""Unit tests for canon module (schema constants and constructors)."""

from meterdatalogic import canon


def test_infer_cadence_minutes_30min(halfhour_rng):
    assert canon.infer_cadence_minutes(halfhour_rng) == 30


def test_infer_cadence_minutes_default_on_single_point(halfhour_rng):
    single = halfhour_rng.head(1)
    assert canon.infer_cadence_minutes(single) == 30  # default
