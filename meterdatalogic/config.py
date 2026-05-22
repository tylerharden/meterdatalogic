"""Package-level configuration defaults.

These are the values used throughout meterdatalogic when no explicit argument is
provided. Override them programmatically before calling any library functions:

    import meterdatalogic.config as mdl_config
    mdl_config.DEFAULT_TZ = "Australia/Brisbane"
    mdl_config.DEFAULT_HEMISPHERE = "southern"
"""

from __future__ import annotations

from typing import Literal

# ---------------------------------------------------------------------------
# core  (canon, utils, transform)
# ---------------------------------------------------------------------------

DEFAULT_TZ: str = "Australia/Brisbane"
"""Timezone applied to tz-naive timestamps during ingestion and frame creation."""

DEFAULT_HEMISPHERE: Literal["northern", "southern"] = "southern"
"""Hemisphere used for season assignment when not explicitly passed."""

DEFAULT_CADENCE_MIN: int = 30
"""Fallback interval cadence in minutes (NEM12 standard is 30 min)."""

# ---------------------------------------------------------------------------
# io.ingest
# ---------------------------------------------------------------------------

INGEST_TIMESTAMP_COLUMN_ALIASES: tuple[str, ...] = (
    "t_start",
    "timestamp",
    "time",
    "ts",
    "datetime",
    "date",
)
"""Column name aliases recognised as the timestamp column during auto-rename."""

INGEST_KWH_COLUMN_ALIASES: tuple[str, ...] = ("energy", "value", "consumption")
"""Column name aliases recognised as kWh energy readings during auto-rename."""

# ---------------------------------------------------------------------------
# analytics.summary
# ---------------------------------------------------------------------------

WINDOWS: list[dict[str, str]] = [
    {"key": "overnight", "start": "00:00", "end": "05:00"},
    {"key": "morning", "start": "05:00", "end": "09:00"},
    {"key": "daytime", "start": "09:00", "end": "17:00"},
    {"key": "evening", "start": "17:00", "end": "24:00"},
]
"""Time-of-day bands used when computing summary window statistics."""

SUMMARY_TOP_N: int = 4
"""Number of peak hours included in the summary top_hours payload."""

# ---------------------------------------------------------------------------
# analytics.pricing
# ---------------------------------------------------------------------------

GST_RATE: float = 0.10
"""GST rate applied when include_gst=True (AU: 10%, NZ: 15%)."""

INCLUDE_GST: bool = False
"""Whether to include GST in cost estimates by default."""
