from __future__ import annotations
import pandas as pd
from typing import IO, Optional
from zoneinfo import ZoneInfo

from . import canon, utils, validate

try:
    from nemreader import NEMFile
except Exception:
    NEMFile = None


def _attach_cadence_per_group(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("Index must be a DatetimeIndex.")

    gcols = ["nmi", "channel"]

    cad_per_group = (
        df.sort_index()
        .groupby(gcols, observed=True)
        .apply(lambda g: utils.infer_minutes_from_index(g.index), include_groups=False)
        .rename("cadence_min")
        .reset_index()
    )

    out = (
        df.reset_index()
        .merge(cad_per_group, on=gcols, how="left", validate="many_to_one")
        .set_index("t_start")
        .sort_index()
    )
    out["cadence_min"] = out["cadence_min"].astype(int)
    return out


def _auto_rename(df: pd.DataFrame) -> pd.DataFrame:
    new = df.copy()

    # 1) If index is already datetime-like, just name it t_start
    if isinstance(new.index, pd.DatetimeIndex):
        new.index.name = canon.INDEX_NAME
    else:
        # 2) Otherwise try to find a timestamp column and set as index
        cols = {c.lower(): c for c in new.columns}
        tcol = next((cols[k] for k in canon.COMMON_TIMESTAMP_NAMES if k in cols), None)
        if tcol is None:
            raise ValueError(
                "No timestamp column found and index is not datetime. "
                "Expected one of: t_start, timestamp, time, ts, datetime, date."
            )
        new = new.rename(columns={tcol: canon.INDEX_NAME}).set_index(canon.INDEX_NAME)

    # 3) Standardize energy column name if needed
    # (only rename if a candidate exists and 'kwh' isn't already present)
    if "kwh" not in new.columns:
        for candidate in ("kwh", "energy", "value", "consumption"):
            if candidate in df.columns:
                new = new.rename(columns={candidate: "kwh"})
                break

    return new


def from_dataframe(
    df: pd.DataFrame,
    *,
    tz: str = canon.DEFAULT_TZ,
    channel_map: Optional[dict[str, str]] = None,
    nmi: Optional[int] = None,
) -> pd.DataFrame:
    """
    Parse a provided DataFrame with canon-like columns
    and normalise to canon:
      - index: tz-aware 't_start'
      - columns: nmi, channel, flow, kwh (positive), cadence_min
    """
    channel_map = channel_map or canon.CHANNEL_MAP
    df = _auto_rename(df)
    df = validate.validate_nmi(df, nmi)

    for col in ("nmi", "channel", "kwh"):
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")

    # derive flow from channel map if absent
    if "flow" not in df.columns:
        df = df.assign(flow=df["channel"].map(channel_map).fillna(df["channel"]))

    # kwh must be non-negative in canon
    df = df.assign(kwh=df["kwh"].astype(float).abs())

    # cadence_min
    cadence = df.get("cadence_min")
    if cadence is None or (isinstance(cadence, pd.Series) and cadence.isna().all()):
        df = _attach_cadence_per_group(df)
    elif not isinstance(cadence, pd.Series):
        df = df.assign(cadence_min=int(cadence))

    # in ingest.from_dataframe(), after utils.attach_cadence_per_group(...)
    chk = df.groupby(["nmi", "channel"])["cadence_min"].nunique()
    if (chk > 1).any():
        raise ValueError(
            "Mixed cadence within a single (nmi, channel). Split or normalise before ingest."
        )

    # enforce index + tz
    df.index.name = canon.INDEX_NAME
    df = utils.ensure_tz_aware_index(df.sort_index(), tz)

    cols = [c for c in canon.REQUIRED_COLS if c in df.columns]
    return df[cols].copy()


def from_nem12(
    file_like: IO[bytes] | str,
    *,
    tz: str = canon.DEFAULT_TZ,
    channel_map: Optional[dict[str, str]] = None,
    nmi: Optional[int] = None,
) -> pd.DataFrame:
    """
    Parse a NEM12 file via nemreader.NEMFile.get_data_frame()
    and normalise to canon:
      - index: tz-aware 't_start'
      - columns: nmi, channel, flow, kwh (positive), cadence_min
    """
    if NEMFile is None:
        raise RuntimeError(
            "nemreader is not installed. Install nemreader to use from_nem12."
        )

    nf = NEMFile(file_like)
    raw = (
        nf.get_data_frame()
    )  # columns: nmi, suffix, serno, t_start, t_end, value, quality, evt_code, evt_desc
    if raw is None or raw.empty:
        # return an empty canon-shaped frame
        idx = pd.DatetimeIndex([], tz=ZoneInfo(tz), name=canon.INDEX_NAME)
        return pd.DataFrame(columns=canon.REQUIRED_COLS, index=idx)

    # Rename to our expected names
    df = raw.rename(columns={"suffix": "channel", "value": "kwh"})
    # Localize/convert t_start then set as index
    df["t_start"] = utils.safe_localize_series(df["t_start"], tz)
    df = df.set_index("t_start").sort_index()

    # Sign convention in file: B1 often negative (export). In canon, kwh is positive and flow tells direction.
    # So: make kwh positive; flow from suffix; export is represented by flow name.
    channel_map = channel_map or canon.CHANNEL_MAP
    df["kwh"] = df["kwh"].astype(float).abs()
    df["flow"] = (
        df["channel"].astype(str).map(channel_map).fillna(df["channel"].astype(str))
    )

    # Minimum required columns
    if "nmi" not in df.columns:
        raise ValueError("NEM12 frame missing 'nmi' column.")
    df = validate.validate_nmi(df, nmi)  # validate NMI

    # cadence_min (infer from index)
    df = _attach_cadence_per_group(df)

    # Keep canon columns
    out = df[["nmi", "channel", "flow", "kwh", "cadence_min"]].copy()
    out.index.name = canon.INDEX_NAME
    return out
