from __future__ import annotations
from typing import TypedDict, Literal, List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
from pydantic import BaseModel

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

    @property  # either 'grid_import', 'controlled_load_import', 'grid_export_solar'
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


# Summary


# Metadata about the dataset
class SummaryMeta(TypedDict):
    nmis: int
    start: str
    end: str
    cadence_min: int
    days: int
    channels: List[str]
    flows: List[str]


class SummaryPeaks(TypedDict, total=False):
    max_interval_kwh: float
    max_interval_time: Optional[str]


class SummaryBase(TypedDict, total=False):
    base_kw: float
    base_kwh_per_day: float
    share_of_daily_pct: float


class WindowStat(TypedDict, total=False):
    avg_kw: float
    kwh_per_day: float
    share_of_daily_pct: float


class TopHours(TypedDict, total=False):
    hours: List[str]
    kwh_total: float
    share_of_daily_pct: float


class SummaryStats(TypedDict, total=False):
    total_import_kwh: float
    per_day_avg_kwh: float
    peak_consumption_kw: float
    peak_time: Optional[str]
    peaks: SummaryPeaks
    base: SummaryBase
    windows: Dict[str, WindowStat]
    top_hours: TopHours


class SeriesBreakdown(TypedDict, total=False):
    total: List[Dict[str, float | str]]
    peaks: List[Dict[str, float | str]]
    average: List[Dict[str, float | str]]


class SummaryDatasets(TypedDict, total=False):
    profile24: List[Dict[str, float | str]]
    days: SeriesBreakdown
    months: SeriesBreakdown


class InsightItem(TypedDict, total=False):
    id: str
    level: Literal["basic", "intermediate", "advanced"]
    category: Literal["usage", "tariff", "solar", "scenario", "data_quality"]
    severity: Literal["info", "notice", "warning", "critical"]
    title: str
    message: str
    tags: List[str]
    metrics: Dict[str, float]
    extras: Dict[str, float | str]


class SummaryPayload(TypedDict, total=False):
    meta: SummaryMeta
    stats: SummaryStats
    datasets: SummaryDatasets
    insights: List[InsightItem]


## TOU Pricing Models
class ToUBand(BaseModel):
    """Time-of-Use tariff band."""
    name: str
    start: str  # "HH:MM"
    end: str  # "HH:MM"
    rate_c_per_kwh: float


class DemandCharge(BaseModel):
    """Demand charge configuration."""
    window_start: str  # "HH:MM"
    window_end: str  # "HH:MM"
    days: Literal["MF", "MS"]
    rate_per_kw_per_month: float


class Plan(BaseModel):
    """Complete electricity tariff plan."""
    usage_bands: list[ToUBand]
    feed_in_c_per_kwh: float = 0.0
    demand: Optional[DemandCharge] = None
    fixed_c_per_day: float = 0.0


## Scenario Configurations
# Scenario Types
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


class EVConfig(BaseModel):
    """Electric Vehicle charging configuration."""
    daily_kwh: float = 7.0  # energy to add per day for charging
    max_kw: float = 7.0  # charger/inlet limit
    window_start: str = "18:00"
    window_end: str = "07:00"  # next-day OK
    days: Literal["ALL", "MF", "MS"] = "ALL"
    strategy: Literal["immediate", "scheduled"] = "immediate"  # solar_follow later


class PVConfig(BaseModel):
    """Solar PV system configuration."""
    system_kwp: float  # DC nameplate
    inverter_kw: float  # AC limit
    loss_fraction: float = 0.15  # wiring/soiling/etc.
    seasonal_scale: Optional[dict[str, float]] = None  # e.g. {"01":1.05,"06":0.9}


class BatteryConfig(BaseModel):
    """Battery storage system configuration."""
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
