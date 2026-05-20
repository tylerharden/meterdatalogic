"""Unit tests for timezone and time-of-day helpers in utils."""

import polars as pl
import datetime as _dt

from meterdatalogic import utils


def test_ensure_tz_aware_localises_naive(rng_dst_gap, tz_sydney):
    naive = rng_dst_gap.dt.replace_time_zone(None)
    aware = utils.ensure_tz_aware(naive, tz_sydney)
    assert aware.dtype.time_zone == tz_sydney


def test_ensure_tz_aware_converts_existing(rng_dst_gap, tz_sydney):
    aware = utils.ensure_tz_aware(rng_dst_gap, "UTC")
    assert aware.dtype.time_zone == "UTC"


def test_ensure_tz_aware_roundtrip_length(rng_dst_overlap, tz_sydney):
    result = utils.ensure_tz_aware(rng_dst_overlap, tz_sydney)
    assert len(result) == len(rng_dst_overlap)
    assert result.dtype.time_zone == tz_sydney


def test_infer_cadence_minutes_30min(halfhour_rng):
    assert utils.infer_cadence_minutes(halfhour_rng) == 30


def test_infer_cadence_minutes_default_on_single_point(halfhour_rng):
    single = halfhour_rng.head(1)
    assert utils.infer_cadence_minutes(single) == 30  # default


def test_time_in_range_normal(halfhour_rng):
    mask = utils.time_in_range(halfhour_rng, _dt.time(16, 0), _dt.time(21, 0))
    assert mask.dtype == pl.Boolean
    assert mask.sum() > 0


def test_time_in_range_wrap(halfhour_rng):
    mask = utils.time_in_range(halfhour_rng, _dt.time(22, 0), _dt.time(2, 0))
    assert mask.sum() > 0


def test_day_mask_all(halfhour_rng):
    mask = utils.day_mask(halfhour_rng, "ALL")
    assert mask.all()


def test_day_mask_mf_less_than_all(halfhour_rng):
    mask = utils.day_mask(halfhour_rng, "MF")
    assert 0 < mask.sum() < len(halfhour_rng)


def test_parse_time_str_midnight():
    assert utils.parse_time_str("24:00") == _dt.time(0, 0)


def test_parse_time_str_normal():
    assert utils.parse_time_str("16:30") == _dt.time(16, 30)
