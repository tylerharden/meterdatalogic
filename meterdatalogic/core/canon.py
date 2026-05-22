"""Schema constants, CanonFrame constructors, and cadence inference."""

from __future__ import annotations
from typing import Final, Dict
import polars as pl

from ..config import DEFAULT_TZ, DEFAULT_CADENCE_MIN
from .types import CanonFrame

INDEX_NAME: Final[str] = "t_start"
REQUIRED_COLS: Final[list[str]] = ["nmi", "channel", "flow", "kwh", "cadence_min"]

# Raw NEM12 suffix/channel → semantic flow
CHANNEL_MAP: Dict[str, str] = {
    "E1": "grid_import",
    "E2": "controlled_load_import",
    "B1": "grid_export_solar",
}

# Polars schema for a canonical interval DataFrame.
# t_start is a regular column (tz-aware Datetime), not an index.
CANON_SCHEMA: Dict[str, pl.DataType] = {
    "t_start": pl.Datetime("us", DEFAULT_TZ),
    "nmi": pl.String,
    "channel": pl.String,
    "flow": pl.String,
    "kwh": pl.Float64,
    "cadence_min": pl.Int32,
}


def infer_cadence_minutes(t_start: pl.Series, default: int = DEFAULT_CADENCE_MIN) -> int:
    """Infer cadence in minutes from a Datetime Series, ignoring duplicates."""
    ts = t_start.unique().sort()
    if len(ts) < 2:
        return int(default)
    diffs = ts.diff().drop_nulls()
    diffs_min = diffs.dt.total_seconds() / 60.0
    diffs_min = diffs_min.filter(diffs_min > 0)
    if len(diffs_min) == 0:
        return int(default)
    rounded = diffs_min.round(0).cast(pl.Int32)
    return int(rounded.value_counts(sort=True).row(0)[0])


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
    kwh_series = (
        kwh.cast(pl.Float64) if isinstance(kwh, pl.Series) else pl.Series(kwh, dtype=pl.Float64)
    )
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
