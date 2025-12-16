from __future__ import annotations

from typing import Iterable, List, Optional

from .types import Insight, InsightContext, InsightEvaluator
from .config import InsightConfig, default_config
from ..types import CanonFrame

# Import evaluator groups
from .evaluators_basic import (
    usage_vs_benchmark,
    peak_time_bias,
    data_completeness,
)
from .evaluators_intermediate import (
    seasonal_variation,
    tariff_suitability,
    peak_demand_characteristics,
)
from .evaluators_advanced import (
    ev_impact,
    battery_impact,
    load_shifting_opportunities,
    step_change_baseload,
)


def _flatten(results: Iterable[Optional[Insight] | List[Insight]]) -> List[Insight]:
    out: List[Insight] = []
    for r in results:
        if r is None:
            continue
        if isinstance(r, list):
            out.extend([x for x in r if x is not None])
        else:
            out.append(r)
    return out


def generate_insights(
    df: CanonFrame,
    *,
    config: Optional[InsightConfig] = None,
    context: Optional[InsightContext] = None,
) -> List[Insight]:
    """Evaluate all configured insights against a canonical dataset.

    This orchestration keeps the engine simple: each evaluator returns an
    Insight or None when not applicable. Adding new insights is as easy as
    adding another evaluator here.
    """
    cfg = config or default_config()

    evaluators: list[InsightEvaluator] = [
        # BASIC
        usage_vs_benchmark,
        peak_time_bias,
        data_completeness,
        # INTERMEDIATE
        seasonal_variation,
        tariff_suitability,
        peak_demand_characteristics,
        # ADVANCED
        ev_impact,
        battery_impact,
        load_shifting_opportunities,
        step_change_baseload,
    ]

    results: list[Optional[Insight] | list[Insight]] = []
    for ev in evaluators:
        try:
            results.append(ev(df, config=cfg, context=context))
        except Exception:
            # Be defensive: one failing evaluator shouldn't block others.
            continue
    return _flatten(results)
