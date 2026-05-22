from __future__ import annotations
import polars as pl
from datetime import time as _time
from typing import Literal

from ..config import DEFAULT_TZ, DEFAULT_CADENCE_MIN
from .types import CanonFrame


# ---------------------------------------------------------------------------
# Timezone helpers
# ---------------------------------------------------------------------------

def ensure_tz_aware(t_start: pl.Series, tz: str) -> pl.Series:
    """Return a tz-aware Datetime Series, localising or converting as needed."""
    if t_start.dtype.time_zone is None:
        return t_start.dt.replace_time_zone(tz)
    return t_start.dt.convert_time_zone(tz)


# ---------------------------------------------------------------------------
# Cadence inference
# ---------------------------------------------------------------------------

def infer_cadence_minutes(t_start: pl.Series, default: int = DEFAULT_CADENCE_MIN) -> int:
    """Infer cadence in minutes from a Datetime Series, ignoring duplicates."""
    ts = t_start.unique().sort()
    if len(ts) < 2:
        return int(default)

    diffs = ts.diff().drop_nulls()  # Duration series
    diffs_min = diffs.dt.total_seconds() / 60.0
    diffs_min = diffs_min.filter(diffs_min > 0)
    if len(diffs_min) == 0:
        return int(default)

    rounded = diffs_min.round(0).cast(pl.Int32)
    return int(rounded.value_counts(sort=True).row(0)[0])


def interval_hours(df: CanonFrame) -> float:
    return infer_cadence_minutes(df["t_start"]) / 60.0


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


def _seconds_since_midnight(t_start: pl.Series) -> pl.Series:
    """Seconds since local midnight for each timestamp."""
    h = t_start.dt.hour().cast(pl.Int64)
    m = t_start.dt.minute().cast(pl.Int64)
    s = t_start.dt.second().cast(pl.Int64)
    return h * 3600 + m * 60 + s


def time_in_range(t_start: pl.Series, start: _time, end: _time) -> pl.Series:
    """Boolean mask: timestamps whose local wall-clock time is in [start, end)."""
    t_s = _seconds_since_midnight(t_start)
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
        return dow <= 5   # Mon=1 … Fri=5
    if days == "MS":
        return dow <= 6   # Mon=1 … Sat=6
    return pl.Series([True] * len(t_start), dtype=pl.Boolean)


# ---------------------------------------------------------------------------
# Label helpers
# ---------------------------------------------------------------------------

def month_label(ts: pl.Series, tz: str | None = None) -> pl.Series:
    """Return YYYY-MM month labels from a tz-aware Datetime Series."""
    s = ts
    if tz:
        if s.dtype.time_zone is not None:
            s = s.dt.convert_time_zone(tz)
        else:
            s = s.dt.replace_time_zone(tz)
    return s.dt.strftime("%Y-%m")


def format_period_label(ts: pl.Series, freq: str) -> pl.Series:
    """Format timestamps as YYYY-MM-DD (freq='1D') or YYYY-MM strings."""
    fmt = "%Y-%m-%d" if freq == "1D" else "%Y-%m"
    return ts.dt.strftime(fmt)


# ---------------------------------------------------------------------------
# Flow / kWh aggregation helpers
# ---------------------------------------------------------------------------

def compute_flow_totals(df: CanonFrame) -> dict[str, float]:
    """Total kWh by flow name from a canonical DataFrame."""
    if df.is_empty() or "flow" not in df.columns or "kwh" not in df.columns:
        return {}
    result = df.group_by("flow").agg(pl.col("kwh").sum())
    return dict(zip(result["flow"].to_list(), result["kwh"].to_list()))


def total_import_export(flow_totals: dict[str, float]) -> tuple[float, float]:
    """Sum all import flows and all export flows. Returns (total_import, total_export)."""
    import_flows = [k for k in flow_totals if "import" in k]
    export_flows = [k for k in flow_totals if "export" in k]
    return (
        float(sum(flow_totals.get(k, 0.0) for k in import_flows)),
        float(sum(flow_totals.get(k, 0.0) for k in export_flows)),
    )


def daily_total_from_profile(profile: CanonFrame) -> float:
    """Sum the 'import_total' column from an average-day profile."""
    if profile.is_empty() or "import_total" not in profile.columns:
        return 0.0
    return float(profile["import_total"].sum())


# ---------------------------------------------------------------------------
# Canon frame construction
# ---------------------------------------------------------------------------

def build_canon_frame(
    t_start: pl.Series,
    kwh: pl.Series | list[float],
    *,
    nmi: str | None,
    channel: str,
    flow: str,
    cadence_min: int | None,
) -> CanonFrame:
    n = len(t_start)
    kwh_series = kwh.cast(pl.Float64) if isinstance(kwh, pl.Series) else pl.Series(kwh, dtype=pl.Float64)
    return pl.DataFrame(
        {
            "t_start": t_start,
            "nmi": pl.Series([nmi] * n, dtype=pl.String),
            "channel": pl.Series([channel] * n, dtype=pl.String),
            "flow": pl.Series([flow] * n, dtype=pl.String),
            "kwh": kwh_series,
            "cadence_min": pl.Series([cadence_min] * n, dtype=pl.Int32),
        }
    ).sort("t_start")


def empty_canon_frame(tz: str = DEFAULT_TZ) -> CanonFrame:
    """Return an empty CanonFrame with the correct schema."""
    return pl.DataFrame(
        {
            "t_start": pl.Series([], dtype=pl.Datetime("us", tz)),
            "nmi": pl.Series([], dtype=pl.String),
            "channel": pl.Series([], dtype=pl.String),
            "flow": pl.Series([], dtype=pl.String),
            "kwh": pl.Series([], dtype=pl.Float64),
            "cadence_min": pl.Series([], dtype=pl.Int32),
        }
    )
