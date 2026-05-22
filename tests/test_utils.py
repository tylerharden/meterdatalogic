"""Unit tests for timezone and time-of-day helpers in utils."""

import polars as pl
import datetime as _dt

from meterdatalogic import utils


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
