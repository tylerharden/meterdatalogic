from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field
from datetime import datetime

Cadence = Literal["5min", "15min", "30min", "60min"]

class IntervalSeries(BaseModel):
    index: list[datetime]            # tz-aware, uniform cadence
    values_kwh: list[float]          # import positive, export negative
    cadence: Cadence = "30min"
    nmi: str
    meter_number: str
    channel: str = "E1"
    model_config = {"frozen": True}
