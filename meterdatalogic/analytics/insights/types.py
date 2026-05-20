from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Mapping, Optional, Protocol, TYPE_CHECKING
import polars as pl

from ...core.types import CanonFrame
from ..types import ScenarioResult

if TYPE_CHECKING:
    from .config import InsightConfig

InsightLevel = Literal["basic", "intermediate", "advanced"]
InsightCategory = Literal["usage", "tariff", "solar", "scenario", "data_quality"]
InsightSeverity = Literal["info", "notice", "warning", "critical"]


@dataclass
class Insight:
    """A single human-readable insight with structured metadata."""

    id: str
    level: InsightLevel
    category: InsightCategory
    title: str
    message: str
    severity: InsightSeverity = "info"
    tags: List[str] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)
    extras: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PricingContext:
    """Optional pricing comparison context (polars DataFrames with a 'total' column)."""
    current_plan: str
    costs_by_plan: Mapping[str, pl.DataFrame]


@dataclass
class ScenariosContext:
    """Optional scenario results context."""
    scenarios: Mapping[str, ScenarioResult]


@dataclass
class InsightContext:
    pricing: Optional[PricingContext] = None
    scenarios: Optional[ScenariosContext] = None


class InsightEvaluator(Protocol):
    def __call__(
        self,
        df: CanonFrame,
        *,
        config: "InsightConfig",
        context: Optional[InsightContext] = None,
    ) -> Optional[Insight] | List[Insight]: ...
