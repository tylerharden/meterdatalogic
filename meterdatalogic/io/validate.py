from __future__ import annotations
import polars as pl
from typing import Optional

from ..core import exceptions, canon


def assert_canon(df: pl.DataFrame) -> None:
    if "t_start" not in df.columns:
        raise exceptions.CanonError("Missing 't_start' column.")
    t = df["t_start"]
    if not isinstance(t.dtype, pl.Datetime):
        raise exceptions.CanonError("'t_start' must be a Datetime column.")
    if t.dtype.time_zone is None:
        raise exceptions.CanonError("'t_start' must be tz-aware.")
    for col in canon.REQUIRED_COLS:
        if col not in df.columns:
            raise exceptions.CanonError(f"Missing required column '{col}'.")
    if not t.equals(t.sort()):
        raise exceptions.CanonError("'t_start' must be sorted ascending.")
    if (df["kwh"] < 0).any():
        raise exceptions.CanonError("Negative kWh values detected; energy should be non-negative.")


def validate_nmi(df: pl.DataFrame, nmi: Optional[str] = None) -> pl.DataFrame:
    """
    Validate that DataFrame contains a single NMI, or filter to the specified NMI.

    Returns:
        DataFrame filtered to a single NMI.

    Raises:
        ValueError: If multiple NMIs found without specifying which one, or NMI not found.
    """
    if "nmi" not in df.columns:
        raise ValueError("DataFrame does not have 'nmi' column")

    nmi_strs = [str(n) for n in df["nmi"].unique().to_list()]

    if nmi is not None:
        nmi_str = str(nmi)
        if nmi_str not in nmi_strs:
            raise ValueError(
                f"Specified NMI {nmi} is not in the dataset. Available NMIs: {', '.join(nmi_strs)}"
            )
        filtered = df.filter(pl.col("nmi").cast(pl.String) == nmi_str)
        if filtered.is_empty():
            raise ValueError(f"No data found for NMI {nmi} after filtering")
        return filtered

    if len(nmi_strs) > 1:
        raise ValueError(f"Multiple NMIs detected: {', '.join(nmi_strs)}. Please specify an NMI.")
    return df
