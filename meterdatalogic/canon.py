from __future__ import annotations
from typing import Final, Dict

INDEX_NAME: Final[str] = "t_start"
REQUIRED_COLS: Final[list[str]] = ["nmi", "channel", "flow", "kwh", "cadence_min"]
DEFAULT_TZ: Final[str] = "Australia/Brisbane"
DEFAULT_CADENCE_MIN: Final[int] = 30
COMMON_TIMESTAMP_NAMES = ("t_start", "timestamp", "time", "ts", "datetime", "date")

# Raw NEM12 suffix/channel → semantic flow
CHANNEL_MAP: Dict[str, str] = {
    "E1": "grid_import",
    "E2": "controlled_load_import",
    "B1": "grid_export_solar",
}
