from __future__ import annotations
from typing import Final, Dict
import polars as pl

from ..config import DEFAULT_TZ

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
