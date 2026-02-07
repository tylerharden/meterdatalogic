from __future__ import annotations
import pandas as pd
from typing import cast

from ..io import validate
from ..core import utils, canon
from ..core.types import CanonFrame
from .types import LogicalCanon, LogicalSeries, LogicalDay


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
    idx = pd.DatetimeIndex(df.index)
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
        cadence_min = utils.infer_cadence_minutes(
            pd.DatetimeIndex(g.index), default=canon.DEFAULT_CADENCE_MIN
        )

        # derive local date for each interval
        local_idx = pd.DatetimeIndex(g.index).tz_convert(tzname)
        dates = local_idx.normalize()  # midnight in local tz
        g = g.copy()
        g["_date"] = dates

        days: list[LogicalDay] = []

        for date_val, day_df in g.groupby("_date", sort=False):
            # Now compress flows to arrays
            # expected slots in this day
            slots = int(24 * 60 / cadence_min)

            # Build a complete date-range index for safety
            # Align start to the first local time-of-day present in this day's data to preserve phase
            day_local = pd.DatetimeIndex(day_df.index).tz_convert(tzname)
            offset = day_local[0] - day_local[0].normalize()
            date_ts = cast(pd.Timestamp, date_val)
            day_start = date_ts + offset
            full_index = pd.date_range(
                start=day_start,
                periods=slots,
                freq=f"{cadence_min}min",
                tz=tzname,
            )

            # Reindex per-flow to align to full day
            flows_dict: dict[str, list[float]] = {}

            for flow_name, fdf in day_df.groupby("flow"):
                s = fdf["kwh"].reindex(full_index, method=None).fillna(0.0).astype(float)
                flows_dict[str(flow_name)] = s.to_list()

            logical_day: LogicalDay = {
                "date": date_ts.to_pydatetime(),
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

    This reconstructs:
      - index: tz-aware DatetimeIndex 't_start'
      - columns: nmi, channel, flow, kwh, cadence_min
    """
    if not obj:
        # empty CanonFrame with the right columns/index
        return utils.empty_canon_frame()

    frames: list[pd.DataFrame] = []

    for series in obj:
        nmi = series["nmi"]
        channel = series["channel"]
        tz = series["tz"]

        for day in series["days"]:
            date_val = day["date"]
            cadence_min = int(day["interval_min"])
            slots = int(day["slots"])
            flows = day["flows"]

            # Normalise to a tz-aware start-of-day
            ts = pd.Timestamp(date_val)
            if ts.tz is None:
                day_start = ts.tz_localize(tz)
            else:
                day_start = ts.tz_convert(tz)

            idx = pd.date_range(
                start=pd.Timestamp(day_start),
                periods=slots,
                freq=f"{cadence_min}min",
            )

            for flow_name, values in flows.items():
                if len(values) != slots:
                    raise ValueError(
                        f"Flow {flow_name!r} for {nmi}/{channel} on {date_val} "
                        f"has {len(values)} slots, expected {slots}"
                    )

                df_flow = pd.DataFrame(
                    {
                        canon.INDEX_NAME: idx,
                        "nmi": nmi,
                        "channel": channel,
                        "flow": flow_name,
                        "kwh": pd.to_numeric(values, errors="coerce").astype(float),
                        "cadence_min": cadence_min,
                    }
                ).set_index(canon.INDEX_NAME)

                frames.append(df_flow)
    if not frames:
        return utils.empty_canon_frame()

    df: CanonFrame = cast(CanonFrame, pd.concat(frames, axis=0).sort_index())
    validate.assert_canon(df)
    return df
