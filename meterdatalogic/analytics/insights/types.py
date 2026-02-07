from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Mapping, Optional, Protocol, TYPE_CHECKING
import pandas as pd

from ...core.types import CanonFrame
from ..types import ScenarioResult

if TYPE_CHECKING:
    from .config import InsightConfig

# Enums (as Literals for lightweight typing)
InsightLevel = Literal["basic", "intermediate", "advanced"]
InsightCategory = Literal["usage", "tariff", "solar", "scenario", "data_quality"]
InsightSeverity = Literal["info", "notice", "warning", "critical"]


@dataclass
class Insight:
    """A single human-readable insight with structured metadata.

    - id: stable identifier (snake_case) for programmatic handling
    - level/category: for grouping and filtering
    - title/message: UI-ready human text (short title + one-paragraph message)
    - severity: lightweight importance indicator for UI styling
    - metrics: small numeric bundle (percentages, kWh, $)
    - extras: optional structured details for deeper UI drill-down
    """

    id: str
    level: InsightLevel
    category: InsightCategory
    title: str
    message: str
    severity: InsightSeverity = "info"
    tags: List[str] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)
    extras: Dict[str, Any] = field(default_factory=dict)


# Optional external context available to the insights engine
@dataclass
class PricingContext:
    """Optional pricing comparison context.

    Provide monthly (or cycle) cost DataFrames for the current plan and
    alternatives. DataFrames should contain a numeric 'total' column that
    sums to an annual cost when summed over rows.
    """

    current_plan: str
    costs_by_plan: Mapping[str, pd.DataFrame]


@dataclass
class ScenariosContext:
    """Optional scenario results context.

    Provide named ScenarioResult objects, e.g., {"ev": ..., "battery": ...}.
    """

    scenarios: Mapping[str, ScenarioResult]


@dataclass
class InsightContext:
    pricing: Optional[PricingContext] = None
    scenarios: Optional[ScenariosContext] = None


# Evaluator protocol for pluggable insight checks
class InsightEvaluator(Protocol):
    def __call__(
        self,
        df: CanonFrame,
        *,
        config: "InsightConfig",
        context: Optional[InsightContext] = None,
    ) -> Optional[Insight] | List[Insight]: ...
