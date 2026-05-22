"""Conversion between CanonFrame and the compressed LogicalCanon format."""

from __future__ import annotations
import polars as pl

from ..io import validate
from ..core import canon
from ..core.types import CanonFrame
from .types import LogicalCanon, LogicalSeries, LogicalDay


def to_logical(df: CanonFrame) -> LogicalCanon:
    """
    Convert canonical interval dataframe into a compressed logical model.

    Groups by (nmi, channel). Within each series, groups by local 'date' and
    compresses flows into arrays of kWh with fixed interval length.
    """
    validate.assert_canon(df)

    if df.is_empty():
        return []

    tz = df["t_start"].dtype.time_zone
    if tz is None:
        raise ValueError("CanonFrame 't_start' must be tz-aware for logical encoding")

    out: LogicalCanon = []

    for (nmi, channel), g in df.group_by(["nmi", "channel"], maintain_order=False):
        g = g.sort("t_start")

        cadence_min = canon.infer_cadence_minutes(g["t_start"])

        # Derive local date for each interval
        g = g.with_columns(pl.col("t_start").dt.convert_time_zone(tz).dt.date().alias("_date"))

        days: list[LogicalDay] = []

        for date_val, day_df in g.group_by("_date", maintain_order=False):
            date_val = date_val if not isinstance(date_val, tuple) else date_val[0]
            day_df = day_df.sort("t_start")
            slots = int(24 * 60 / cadence_min)

            # Align to the first slot in this day's data (preserves phase)
            first_ts = day_df["t_start"][0]
            day_start_local = first_ts.replace(hour=0, minute=0, second=0, microsecond=0)
            offset_mins = int((first_ts - day_start_local).total_seconds() / 60)
            # Build a complete date-range index for this day
            full_ts = [
                day_start_local.replace(
                    hour=((offset_mins + i * cadence_min) // 60) % 24,
                    minute=(offset_mins + i * cadence_min) % 60,
                )
                for i in range(slots)
            ]
            full_index = pl.Series(full_ts, dtype=pl.Datetime("us", tz))

            flows_dict: dict[str, list[float]] = {}
            for flow_val, fdf in day_df.group_by("flow", maintain_order=False):
                flow_name = flow_val if not isinstance(flow_val, tuple) else flow_val[0]
                # Reindex to full_index: join on t_start, fill missing with 0.0
                full_frame = pl.DataFrame({"t_start": full_index})
                merged = full_frame.join(
                    fdf.select(["t_start", "kwh"]), on="t_start", how="left"
                ).with_columns(pl.col("kwh").fill_null(0.0))
                flows_dict[str(flow_name)] = merged["kwh"].to_list()

            import datetime as _dt

            date_py = _dt.date.fromisoformat(str(date_val))
            logical_day: LogicalDay = {
                "date": _dt.datetime(date_py.year, date_py.month, date_py.day),
                "interval_min": cadence_min,
                "slots": slots,
                "flows": flows_dict,
            }
            days.append(logical_day)

        series: LogicalSeries = {
            "nmi": str(nmi),
            "channel": str(channel),
            "tz": str(tz),
            "days": days,
        }
        out.append(series)

    return out


def from_logical(obj: LogicalCanon) -> CanonFrame:
    if not obj:
        return canon.empty_canon_frame()

    frames: list[pl.DataFrame] = []

    for series in obj:
        nmi = series["nmi"]
        channel = series["channel"]
        tz = series["tz"]

        for day in series["days"]:
            date_val = day["date"]
            cadence_min = int(day["interval_min"])
            slots = int(day["slots"])
            flows = day["flows"]

            # Build tz-aware start-of-day
            import datetime as _dt

            if isinstance(date_val, _dt.datetime):
                day_start = date_val.replace(tzinfo=None)
            elif isinstance(date_val, str):
                day_start = _dt.datetime.fromisoformat(date_val.strip())
            else:
                day_start = _dt.datetime(date_val.year, date_val.month, date_val.day)

            ts_list = [day_start + _dt.timedelta(minutes=cadence_min * i) for i in range(slots)]
            ts_series = pl.Series(ts_list, dtype=pl.Datetime("us")).dt.replace_time_zone(tz)

            for flow_name, values in flows.items():
                if len(values) != slots:
                    raise ValueError(
                        f"Flow {flow_name!r} for {nmi}/{channel} on {date_val} "
                        f"has {len(values)} slots, expected {slots}"
                    )
                frames.append(
                    pl.DataFrame(
                        {
                            canon.INDEX_NAME: ts_series,
                            "nmi": pl.Series([nmi] * slots, dtype=pl.String),
                            "channel": pl.Series([channel] * slots, dtype=pl.String),
                            "flow": pl.Series([flow_name] * slots, dtype=pl.String),
                            "kwh": pl.Series(values, dtype=pl.Float64),
                            "cadence_min": pl.Series([cadence_min] * slots, dtype=pl.Int32),
                        }
                    )
                )

    if not frames:
        return canon.empty_canon_frame()

    df = pl.concat(frames).sort("t_start")
    validate.assert_canon(df)
    return df
