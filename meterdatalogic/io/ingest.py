from __future__ import annotations
import polars as pl
from typing import IO, Optional, TYPE_CHECKING

from ..io import validate
from ..core import utils, canon
from ..core.types import CanonFrame
from ..config import DEFAULT_TZ, INGEST_KWH_COLUMN_ALIASES, INGEST_TIMESTAMP_COLUMN_ALIASES

if TYPE_CHECKING:
    from nemreader import NEMFile
else:
    try:
        from nemreader import NEMFile
    except Exception:
        NEMFile = None  # type: ignore[assignment,misc]


def _infer_group_cadence(g: pl.DataFrame) -> pl.DataFrame:
    cadence = utils.infer_cadence_minutes(g["t_start"])
    return pl.DataFrame(
        {
            "nmi": [g["nmi"][0]],
            "channel": [g["channel"][0]],
            "cadence_min": [cadence],
        }
    )


def _attach_cadence_per_group(df: pl.DataFrame) -> pl.DataFrame:
    """Infer cadence in minutes per (nmi, channel) group and attach as a column."""
    if df.is_empty():
        return df.with_columns(pl.lit(None).cast(pl.Int32).alias("cadence_min"))

    cadence_df = df.group_by(["nmi", "channel"]).map_groups(_infer_group_cadence)

    out = df.join(cadence_df, on=["nmi", "channel"], how="left").with_columns(
        pl.col("cadence_min").cast(pl.Int32)
    )

    # Guard against mixed cadence within a single (nmi, channel)
    chk = out.group_by(["nmi", "channel"]).agg(pl.col("cadence_min").n_unique().alias("n"))
    if (chk["n"] > 1).any():
        raise ValueError(
            "Mixed cadence within a single (nmi, channel). Split or normalise before ingest."
        )

    return out


def _auto_rename(df: pl.DataFrame) -> pl.DataFrame:
    cols_lower = {c.lower(): c for c in df.columns}

    tcol = next((cols_lower[k] for k in INGEST_TIMESTAMP_COLUMN_ALIASES if k in cols_lower), None)
    if tcol is None:
        raise ValueError(
            "No timestamp column found. Expected one of: "
            + ", ".join(INGEST_TIMESTAMP_COLUMN_ALIASES)
            + "."
        )

    new = df.rename({tcol: canon.INDEX_NAME}) if tcol != canon.INDEX_NAME else df

    if "kwh" not in new.columns:
        for candidate in INGEST_KWH_COLUMN_ALIASES:
            if candidate in new.columns:
                new = new.rename({candidate: "kwh"})
                break

    return new


def from_dataframe(
    df: pl.DataFrame,
    *,
    tz: str = DEFAULT_TZ,
    channel_map: Optional[dict[str, str]] = None,
    nmi: Optional[str] = None,
) -> CanonFrame:
    """
    Parse a provided polars DataFrame with canon-like columns and normalise to canon:
      - t_start: tz-aware Datetime column
      - columns: nmi, channel, flow, kwh (positive), cadence_min
    """
    channel_map = channel_map or canon.CHANNEL_MAP
    df = _auto_rename(df)
    df = validate.validate_nmi(df, nmi)

    for col in ("nmi", "channel", "kwh"):
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")

    # Derive flow from channel map if absent
    if "flow" not in df.columns:
        df = df.with_columns(
            pl.col("channel")
            .map_elements(lambda c: channel_map.get(str(c), str(c)), return_dtype=pl.String)
            .alias("flow")
        )

    # kwh must be non-negative
    df = df.with_columns(pl.col("kwh").cast(pl.Float64).abs())

    # Attach cadence if missing
    if "cadence_min" not in df.columns or df["cadence_min"].is_null().all():
        df = _attach_cadence_per_group(df)
    else:
        df = df.with_columns(pl.col("cadence_min").cast(pl.Int32))

    # Ensure t_start is tz-aware
    df = df.with_columns(utils.ensure_tz_aware(df["t_start"], tz).alias("t_start"))

    cols = ["t_start"] + [c for c in canon.REQUIRED_COLS if c in df.columns]
    return df.select(cols).sort("t_start")


def from_nem12(
    file_like: IO[bytes] | str,
    *,
    tz: str = DEFAULT_TZ,
    channel_map: Optional[dict[str, str]] = None,
    nmi: Optional[str] = None,
) -> CanonFrame:
    """
    Parse a NEM12 file via nemreader 1.0.0 (get_data_frame_long → pl.DataFrame) and
    normalise to canon:
      - t_start: tz-aware Datetime column
      - columns: nmi, channel, flow, kwh (positive), cadence_min
    """
    if NEMFile is None:
        raise RuntimeError("nemreader is not installed. Install nemreader to use from_nem12.")

    nf = NEMFile(file_like)
    raw = nf.get_data_frame_long()
    # columns: nmi, suffix, serno, t_start, t_end, value, quality, evt_code, evt_desc

    if raw is None or raw.is_empty():
        return utils.empty_canon_frame(tz=tz)

    # Rename suffix → channel, value → kwh; drop cols we don't need
    df = raw.rename({"suffix": "channel", "value": "kwh"}).select(
        ["nmi", "channel", "t_start", "kwh"]
    )

    # t_start from NEM12 is tz-naive local time — localise to the supplied tz
    df = df.with_columns(pl.col("t_start").dt.replace_time_zone(tz))

    # Sign convention: B1 (export) may be negative in the file; make positive
    channel_map = channel_map or canon.CHANNEL_MAP
    df = df.with_columns(
        pl.col("kwh").cast(pl.Float64).abs(),
        pl.col("channel")
        .map_elements(lambda c: channel_map.get(str(c), str(c)), return_dtype=pl.String)
        .alias("flow"),
    )

    if "nmi" not in df.columns:
        raise ValueError("NEM12 frame missing 'nmi' column.")
    df = validate.validate_nmi(df, nmi)

    # Attach cadence per (nmi, channel)
    df = _attach_cadence_per_group(df)

    cols = ["t_start"] + [c for c in canon.REQUIRED_COLS if c in df.columns]
    return df.select(cols).sort("t_start")
