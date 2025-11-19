from __future__ import annotations

from typing import Iterable
from datetime import datetime

import pandas as pd

from . import canon, validate
from .types import CanonFrame, LogicalCanon, LogicalSeries, LogicalDay


def to_logical(df: CanonFrame) -> LogicalCanon:
    """
    Convert canonical interval dataframe into a compressed logical model.

    - Groups by (nmi, channel).
    - Within each series, groups by local 'date' and compresses flows
      into arrays of kWh with fixed interval length.
    """
    validate.assert_canon(df)

    if df.empty:
        return []

    # Ensure tz-aware DatetimeIndex (should already be true)
    idx = df.index
    if idx.tz is None:
        raise ValueError("CanonFrame index must be tz-aware for logical encoding")

    tz = idx.tz
    tzname = getattr(tz, "key", str(tz))

    # We'll normalise to one cadence per (nmi, channel) group
    out: LogicalCanon = []

    # Group by NMI + channel
    by_series = df.groupby(["nmi", "channel"], sort=False)

    for (nmi, channel), g in by_series:
        g = g.sort_index()

        # infer cadence in minutes for this series
        cadence_min = int(
            canon.infer_minutes_from_index(g.index)
            if hasattr(canon, "infer_minutes_from_index")
            else (g.index[1] - g.index[0]).total_seconds() / 60.0
        )

        # derive local date for each interval
        local_idx = g.index.tz_convert(tzname)
        dates = local_idx.normalize()  # midnight in local tz
        g = g.copy()
        g["_date"] = dates

        days: list[LogicalDay] = []

        for date_val, day_df in g.groupby("_date", sort=False):
            # Now compress flows to arrays
            # expected slots in this day
            slots = int(24 * 60 / cadence_min)

            # Build a complete date-range index for safety
            day_start = date_val
            full_index = pd.date_range(
                start=day_start,
                periods=slots,
                freq=f"{cadence_min}min",
                tz=tzname,
            )

            # Reindex per-flow to align to full day
            flows_dict: dict[str, list[float]] = {}

            for flow_name, fdf in day_df.groupby("flow"):
                s = (
                    fdf["kwh"]
                    .reindex(full_index, method=None)
                    .fillna(0.0)
                    .astype(float)
                )
                flows_dict[str(flow_name)] = s.to_list()

            logical_day: LogicalDay = {
                "date": date_val.to_pydatetime(),
                "interval_min": cadence_min,
                "slots": slots,
                "flows": flows_dict,
            }
            days.append(logical_day)

        series: LogicalSeries = {
            "nmi": str(nmi),
            "channel": str(channel),
            "tz": tzname,
            "days": days,
        }
        out.append(series)

    return out


def from_logical(obj: LogicalCanon) -> CanonFrame:
    """
    Convert compressed logical model back into canonical DataFrame.
    """
    if not obj:
        # empty CanonFrame with the right columns/index
        return pd.DataFrame(
            columns=["nmi", "channel", "flow", "kwh", "cadence_min"]
        ).set_index(pd.DatetimeIndex([], name=canon.INDEX_NAME))

    records = []

    for series in obj:
        nmi = series["nmi"]
        channel = series["channel"]
        tz = series["tz"]

        for day in series["days"]:
            date_val = day["date"]
            cadence_min = int(day["interval_min"])
            slots = int(day["slots"])
            flows = day["flows"]

            # start-of-day in tz
            ts = pd.Timestamp(date_val)

            if ts.tz is None:
                # naive -> localise directly
                day_start = ts.tz_localize(tz)
            else:
                # already tz-aware -> convert to desired tz
                day_start = ts.tz_convert(tz)

            idx = pd.date_range(
                start=day_start,
                periods=slots,
                freq=f"{cadence_min}min",
            )

            for flow_name, values in flows.items():
                if len(values) != slots:
                    raise ValueError(
                        f"Flow {flow_name!r} for {nmi}/{channel} on {date_val} "
                        f"has {len(values)} slots, expected {slots}"
                    )
                for ts, kwh in zip(idx, values):
                    records.append(
                        {
                            canon.INDEX_NAME: ts,
                            "nmi": nmi,
                            "channel": channel,
                            "flow": flow_name,
                            "kwh": float(kwh),
                            "cadence_min": cadence_min,
                        }
                    )

    df = pd.DataFrame.from_records(records)
    df.set_index(canon.INDEX_NAME, inplace=True)
    df.sort_index(inplace=True)
    validate.assert_canon(df)
    return df
