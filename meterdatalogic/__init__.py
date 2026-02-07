"""meterdatalogic - Meter data transformation and analytics.

A lightweight library for meter data processing:
- Canonical data model for reliable analytics
- Composable modules: ingest, validate, transform, pricing, scenarios
- Framework-agnostic design
- Plot-ready outputs and JSON serialization

Usage:
    >>> import meterdatalogic as ml
    >>> df = ml.ingest.from_nem12("data.csv")
    >>> ml.validate.assert_canon(df)
    >>> summary = ml.summary.summarise(df)
    >>> insights = ml.insights.generate_insights(df)

Note: The library is organized internally into domain-based packages
(core/, io/, analytics/) for clean code organization, but all modules
are exposed at the top level for a simple, flat API.
"""

# Flat public API - all modules accessible at top level
from .io import formats, ingest, validate
from .core import canon, transform, utils
from .analytics import pricing, scenario, summary, insights
from . import types

__all__ = [
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


