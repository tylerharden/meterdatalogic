from __future__ import annotations
from typing import TypedDict, Literal, List, Dict, Optional
from dataclasses import dataclass
import pandas as pd
from numpy import float64
Flow = Literal["grid_import", "controlled_load_import", "grid_export_solar"]

# Metadata about the dataset
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


## TOU Pricing Models
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

## Scenario Configurations
@dataclass
class EVConfig:
    daily_kwh: float = 7.0                 # energy to add per day for charging
    max_kw: float = 7.0                    # charger/inlet limit
    window_start: str = "18:00"
    window_end: str = "07:00"              # next-day OK
    days: Literal["ALL", "MF", "MS"] = "ALL"
    strategy: Literal["immediate", "scheduled"] = "immediate"  # solar_follow later

@dataclass
class PVConfig:
    system_kwp: float                      # DC nameplate
    inverter_kw: float                     # AC limit
    loss_fraction: float = 0.15            # wiring/soiling/etc.
    seasonal_scale: Optional[dict[str, float]] = None  # e.g. {"01":1.05,"06":0.9}

@dataclass
class BatteryConfig:
    capacity_kwh: float                    # usable capacity
    max_kw: float                          # charge/discharge AC limit
    round_trip_eff: float = 0.90           # overall, applied as sqrt on charge/discharge
    soc_min: float = 0.10                  # fraction of capacity
    soc_max: float = 0.95
    strategy: Literal["self_consume"] = "self_consume"  # extendable
    allow_grid_charge: bool = False
    allow_export: bool = False             # generally False for residential

@dataclass
class ScenarioResult:
    df_before: pd.DataFrame
    df_after: pd.DataFrame
    summary_before: dict
    summary_after: dict
    cost_before: Optional[pd.DataFrame]
    cost_after: Optional[pd.DataFrame]
    delta: Dict[str]
    explain: Dict[str]


## Scenario Configurations
@dataclass
class EVConfig:
    daily_kwh: float = 7.0                 # energy to add per day for charging
    max_kw: float = 7.0                    # charger/inlet limit
    window_start: str = "18:00"
    window_end: str = "07:00"              # next-day OK
    days: Literal["ALL", "MF", "MS"] = "ALL"
    strategy: Literal["immediate", "scheduled"] = "immediate"  # solar_follow later

@dataclass
class PVConfig:
    system_kwp: float                      # DC nameplate
    inverter_kw: float                     # AC limit
    loss_fraction: float = 0.15            # wiring/soiling/etc.
    seasonal_scale: Optional[dict[str, float]] = None  # e.g. {"01":1.05,"06":0.9}

@dataclass
class BatteryConfig:
    capacity_kwh: float                    # usable capacity
    max_kw: float                          # charge/discharge AC limit
    round_trip_eff: float = 0.90           # overall, applied as sqrt on charge/discharge
    soc_min: float = 0.10                  # fraction of capacity
    soc_max: float = 0.95
    strategy: Literal["self_consume"] = "self_consume"  # extendable
    allow_grid_charge: bool = False
    allow_export: bool = False             # generally False for residential

@dataclass
class ScenarioResult:
    df_before: pd.DataFrame
    df_after: pd.DataFrame
    summary_before: dict
    summary_after: dict
    cost_before: Optional[pd.DataFrame]
    cost_after: Optional[pd.DataFrame]
    delta: Dict[str]
    explain: Dict[str]