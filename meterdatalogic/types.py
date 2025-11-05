from __future__ import annotations
from typing import TypedDict, Literal, List, Dict, Optional
from dataclasses import dataclass

Flow = Literal["grid_import", "controlled_load_import", "grid_export_solar"]

class SummaryMeta(TypedDict):
    nmis: int
    start: str
    end: str
    cadence_min: int
    days: int

class SummaryPayload(TypedDict):
    meta: SummaryMeta
    energy: Dict[str, float]
    per_day_avg_kwh: float
    peaks: Dict[str, object]
    profile24: List[Dict[str, float]]
    months: List[Dict[str, float]]

@dataclass
class ToUBand:
    name: str
    start: str  # "HH:MM"
    end: str    # "HH:MM"
    rate_c_per_kwh: float

@dataclass
class DemandCharge:
    window_start: str   # "HH:MM"
    window_end: str     # "HH:MM"
    days: Literal["MF", "MS"]
    rate_per_kw_per_month: float

@dataclass
class Plan:
    usage_bands: list[ToUBand]
    feed_in_c_per_kwh: float = 0.0
    demand: Optional[DemandCharge] = None
    fixed_c_per_day: float = 0.0
