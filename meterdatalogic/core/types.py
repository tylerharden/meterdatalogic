"""Core type aliases: CanonFrame and Flow."""

from __future__ import annotations
from typing import Literal
import polars as pl

Flow = Literal["grid_import", "controlled_load_import", "grid_export_solar"]

# CanonFrame is a pl.DataFrame with the schema defined in canon.CANON_SCHEMA:
#   t_start  : Datetime (tz-aware)  — interval start, previously the index
#   nmi      : String
#   channel  : String
#   flow     : String  (one of the Flow literals)
#   kwh      : Float64 (non-negative)
#   cadence_min : Int32
CanonFrame = pl.DataFrame
