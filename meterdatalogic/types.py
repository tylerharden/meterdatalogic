from __future__ import annotations
from typing import TypedDict, Literal, List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

Flow = Literal["grid_import", "controlled_load_import", "grid_export_solar"]


# Canon DataFrame
class CanonFrame(pd.DataFrame):
    """
    Strongly-typed canonical interval dataframe.

    Expected:
      - DatetimeIndex named 't_start', tz-aware
      - Columns: ['nmi', 'channel', 'flow', 'kwh', 'cadence_min']
    """

    @property
    def _constructor(self):
        return CanonFrame

    # Convenience typed accessors (optional, but handy)
    @property
    def nmi(self) -> pd.Series:
        return self["nmi"]

    @property
    def channel(self) -> pd.Series:
        return self["channel"]

    @property
    def flow(self) -> pd.Series:
        return self["flow"]

    @property
    def kwh(self) -> pd.Series:
        return self["kwh"]

    @property
    def cadence_min(self) -> pd.Series:
        return self["cadence_min"]


# Logical
class LogicalDay(TypedDict):
    date: datetime  # normalised to midnight in tz
    interval_min: int  # e.g. 5 or 30
    slots: int  # number of intervals in the day (e.g. 288)
    flows: Dict[str, List[float]]  # flow_name -> kWh array


class LogicalSeries(TypedDict):
    nmi: str
    channel: str
    tz: str
    days: List[LogicalDay]


# Whole dataset: multiple NMI/channel series
LogicalCanon = List[LogicalSeries]


# Metadata about the dataset
class SummaryMeta(TypedDict):
    nmis: int
    start: str
    end: str
    cadence_min: int
    days: int
    channels: List[str]
    flows: List[str]


class SummaryPayload(TypedDict):
    meta: SummaryMeta
    energy: Dict[str, float]
    per_day_avg_kwh: float
    peaks: Dict[str, object]
    # DataFrames converted to records include label columns (e.g., 'slot', 'month', 'day') as str,
    # and flow columns as floats. Allow both.
    profile24: List[Dict[str, float | str]]
    months: List[Dict[str, float | str]]
    days_series: List[Dict[str, float | str]]


# Scenario deltas / explainables for stronger typing
class ScenarioDelta(TypedDict, total=False):
    import_kwh_delta: float
    export_kwh_delta: float
    total_kwh_delta: float
    cost_total_delta: Optional[float]


class ScenarioExplain(TypedDict, total=False):
    ev_kwh: float
    pv_kwh: float
    battery_discharge_kwh: float
    battery_charge_kwh: float
    battery_cycles_est: float
    pv_self_consumption_pct: Optional[float]


## TOU Pricing Models
@dataclass
class ToUBand:
    name: str
    start: str  # "HH:MM"
    end: str  # "HH:MM"
    rate_c_per_kwh: float


@dataclass
class DemandCharge:
    window_start: str  # "HH:MM"
    window_end: str  # "HH:MM"
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
    daily_kwh: float = 7.0  # energy to add per day for charging
    max_kw: float = 7.0  # charger/inlet limit
    window_start: str = "18:00"
    window_end: str = "07:00"  # next-day OK
    days: Literal["ALL", "MF", "MS"] = "ALL"
    strategy: Literal["immediate", "scheduled"] = "immediate"  # solar_follow later


@dataclass
class PVConfig:
    system_kwp: float  # DC nameplate
    inverter_kw: float  # AC limit
    loss_fraction: float = 0.15  # wiring/soiling/etc.
    seasonal_scale: Optional[dict[str, float]] = None  # e.g. {"01":1.05,"06":0.9}


@dataclass
class BatteryConfig:
    capacity_kwh: float  # usable capacity
    max_kw: float  # charge/discharge AC limit
    round_trip_eff: float = 0.90  # overall, applied as sqrt on charge/discharge
    soc_min: float = 0.10  # fraction of capacity
    soc_max: float = 0.95
    strategy: Literal["self_consume"] = "self_consume"  # extendable
    allow_grid_charge: bool = False
    allow_export: bool = False  # generally False for residential


@dataclass
class ScenarioResult:
    df_before: CanonFrame
    df_after: CanonFrame
    summary_before: SummaryPayload
    summary_after: SummaryPayload
    cost_before: Optional[pd.DataFrame]
    cost_after: Optional[pd.DataFrame]
    delta: ScenarioDelta
    explain: ScenarioExplain
