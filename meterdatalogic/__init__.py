"""meterdatalogic - Meter data transformation and analytics.

Structure:
    core      - Foundation types, data operations, utilities
    io        - Data ingestion, validation, format conversion  
    analytics - Pricing, scenarios, summaries, insights

Usage:
    >>> from meterdatalogic import io, core, analytics
    >>> df = io.ingest.from_nem12("data.csv")
    >>> summary = analytics.summary.summarise(df)
"""

from .io import formats, ingest, validate
from .core import canon, transform, utils
from .analytics import pricing, scenario, summary, insights

# Expose namespaces for clean imports
from . import core, io, analytics, types

# Backwards compatibility - expose modules at top level
import sys

sys.modules['meterdatalogic.formats'] = formats
sys.modules['meterdatalogic.ingest'] = ingest
sys.modules['meterdatalogic.validate'] = validate
sys.modules['meterdatalogic.canon'] = canon
sys.modules['meterdatalogic.transform'] = transform
sys.modules['meterdatalogic.utils'] = utils
sys.modules['meterdatalogic.pricing'] = pricing
sys.modules['meterdatalogic.scenario'] = scenario
sys.modules['meterdatalogic.summary'] = summary
sys.modules['meterdatalogic.insights'] = insights

__all__ = [
    # Namespaces
    "core",
    "io",
    "analytics",
    # Backwards compatibility (flat imports)
    "canon",
    "types",
    "utils",
    "ingest",
    "formats",
    "validate",
    "transform",
    "summary",
    "pricing",
    "scenario",
    "insights",
]


