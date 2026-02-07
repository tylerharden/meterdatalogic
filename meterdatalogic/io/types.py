from __future__ import annotations
from typing import List, Dict
from datetime import datetime
from pydantic import BaseModel


class LogicalDay(BaseModel):
    """A single day of meter data in logical format.
    
    Attributes:
        date: The date for this day's data (normalized to midnight in tz)
        interval_min: Number of minutes per interval (e.g., 30 for half-hourly)
        slots: Number of time slots in the day
        flows: Dictionary mapping flow names to lists of values
    """
    date: datetime
    interval_min: int
    slots: int
    flows: Dict[str, List[float]]


class LogicalSeries(BaseModel):
    """A time series of meter data for a specific NMI and channel.
    
    Attributes:
        nmi: National Metering Identifier
        channel: Channel identifier (e.g., 'E1' for export, 'B1' for import)
        tz: Timezone string (e.g., 'Australia/Brisbane')
        days: List of daily data records
    """
    nmi: str
    channel: str
    tz: str
    days: List[LogicalDay]


# Whole dataset: multiple NMI/channel series
LogicalCanon = List[LogicalSeries]
