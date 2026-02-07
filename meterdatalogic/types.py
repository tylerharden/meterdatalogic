"""Unified types module for backwards compatibility.

This module aggregates types from:
- core.types: CanonFrame, Flow
- io.types: LogicalDay, LogicalSeries, LogicalCanon  
- analytics.types: Plan, EVConfig, PVConfig, BatteryConfig, etc.

For new code, prefer importing directly from the specific modules:
    from meterdatalogic.core.types import CanonFrame
    from meterdatalogic.io.types import LogicalCanon
    from meterdatalogic.analytics.types import Plan
"""

# Core types
from .core.types import (
    CanonFrame,
    Flow,
)

# IO types
from .io.types import (
    LogicalCanon,
    LogicalDay,
    LogicalSeries,
)

# Analytics types
from .analytics.types import (
    BatteryConfig,
    DemandCharge,
    EVConfig,
    InsightItem,
    Plan,
    PVConfig,
    ScenarioDelta,
    ScenarioExplain,
    ScenarioResult,
    SeriesBreakdown,
    SummaryBase,
    SummaryDatasets,
    SummaryMeta,
    SummaryPayload,
    SummaryPeaks,
    SummaryStats,
    ToUBand,
    TopHours,
    WindowStat,
)

__all__ = [
    # Core
    "CanonFrame",
    "Flow",
    # IO
    "LogicalCanon",
    "LogicalDay",
    "LogicalSeries",
    # Analytics
    "BatteryConfig",
    "DemandCharge",
    "EVConfig",
    "InsightItem",
    "Plan",
    "PVConfig",
    "ScenarioDelta",
    "ScenarioExplain",
    "ScenarioResult",
    "SeriesBreakdown",
    "SummaryBase",
    "SummaryDatasets",
    "SummaryMeta",
    "SummaryPayload",
    "SummaryPeaks",
    "SummaryStats",
    "ToUBand",
    "TopHours",
    "WindowStat",
]
