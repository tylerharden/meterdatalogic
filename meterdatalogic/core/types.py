from __future__ import annotations
from typing import Literal
import pandas as pd

Flow = Literal["grid_import", "controlled_load_import", "grid_export_solar"]

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