"""Time-of-day masks and flow aggregation helpers."""

from __future__ import annotations
import polars as pl
from datetime import time as _time
from typing import Literal

from .types import CanonFrame


# ---------------------------------------------------------------------------
# Time-of-day helpers
# ---------------------------------------------------------------------------


def parse_time_str(tstr: str) -> _time:
    """Parse an HH:MM time string. '24:00' is treated as midnight (00:00)."""
    s = tstr.strip()
    if s == "24:00":
        return _time(0, 0)
    h, m = s.split(":")
    return _time(int(h), int(m))


def time_in_range(t_start: pl.Series, start: _time, end: _time) -> pl.Series:
    """Boolean mask: timestamps whose local wall-clock time is in [start, end)."""
    t_s = (
        t_start.dt.hour().cast(pl.Int64) * 3600
        + t_start.dt.minute().cast(pl.Int64) * 60
        + t_start.dt.second().cast(pl.Int64)
    )
    start_s = start.hour * 3600 + start.minute * 60 + start.second
    end_s = end.hour * 3600 + end.minute * 60 + end.second
    if start_s < end_s:
        return (t_s >= start_s) & (t_s < end_s)
    # Wrap-around (e.g. 21:00 → 05:00)
    return (t_s >= start_s) | (t_s < end_s)


def day_mask(t_start: pl.Series, days: Literal["ALL", "MF", "MS"] = "ALL") -> pl.Series:
    """Boolean mask for timestamps on selected days. Polars ISO weekday: Mon=1 … Sun=7."""
    if days == "ALL":
        return pl.Series([True] * len(t_start), dtype=pl.Boolean)
    dow = t_start.dt.weekday()
    if days == "MF":
        return dow <= 5  # Mon=1 … Fri=5
    if days == "MS":
        return dow <= 6  # Mon=1 … Sat=6
    return pl.Series([True] * len(t_start), dtype=pl.Boolean)


# ---------------------------------------------------------------------------
# Flow / kWh aggregation helpers
# ---------------------------------------------------------------------------


def compute_flow_totals(df: CanonFrame) -> dict[str, float]:
    """Total kWh by flow name from a canonical DataFrame."""
    if df.is_empty() or "flow" not in df.columns or "kwh" not in df.columns:
        return {}
    result = df.group_by("flow").agg(pl.col("kwh").sum())
    return dict(zip(result["flow"].to_list(), result["kwh"].to_list()))


def daily_total_from_profile(profile: CanonFrame) -> float:
    """Sum the 'import_total' column from an average-day profile."""
    if profile.is_empty() or "import_total" not in profile.columns:
        return 0.0
    return float(profile["import_total"].sum())


def annual_total_cost(d: pl.DataFrame | None) -> float:
    """Sum a cost/billables table to a single annual total.

    Uses the 'total' column when present (cost-engine output); otherwise
    falls back to summing all numeric columns (billables-only tables that
    have no 'total' column yet).
    """
    if d is None or d.is_empty():
        return 0.0
    if "total" in d.columns:
        return float(d["total"].fill_null(0.0).sum())
    num_cols = [c for c in d.columns if d[c].dtype in (pl.Float64, pl.Float32, pl.Int64, pl.Int32)]
    return float(sum(d[c].sum() for c in num_cols))
