from __future__ import annotations
import pandas as pd
from typing import Optional, cast

from ..core import exceptions, canon


def assert_canon(df: pd.DataFrame) -> None:
    if df.index.name != canon.INDEX_NAME:
        raise exceptions.CanonError(f"Index must be '{canon.INDEX_NAME}'.")
    tz_index = cast(pd.DatetimeIndex, df.index)
    if tz_index.tz is None:
        raise exceptions.CanonError("Index must be tz-aware.")
    for col in canon.REQUIRED_COLS:
        if col not in df.columns:
            raise exceptions.CanonError(f"Missing required column '{col}'.")
    if not df.index.is_monotonic_increasing:
        raise exceptions.CanonError("Index must be sorted ascending.")
    if (df["kwh"] < 0).any():
        raise exceptions.CanonError("Negative kWh values detected; energy should be non-negative.")


def validate_nmi(df: pd.DataFrame, nmi: Optional[str] = None) -> pd.DataFrame:
    """
    Validate that DataFrame contains a single NMI, or filter to specified NMI.

    Args:
        df: DataFrame with 'nmi' column
        nmi: Optional NMI to filter to (string, e.g. "Q1234567890"). If None and
             multiple NMIs exist, raises error.

    Returns:
        DataFrame filtered to single NMI

    Raises:
        ValueError: If multiple NMIs found without specifying which one to use,
                   or if specified NMI not found in data

    Example:
        >>> df = validate_nmi(multi_site_df, nmi="Q1234567890")
    """
    if "nmi" not in df.columns:
        raise ValueError("DataFrame does not have 'nmi' column")

    nmis = df["nmi"].unique()
    nmi_strs = [str(n) for n in nmis]

    if nmi is not None:
        nmi_str = str(nmi)
        if nmi_str not in nmi_strs:
            raise ValueError(
                f"Specified NMI {nmi} is not in the dataset. Available NMIs: {', '.join(nmi_strs)}"
            )
        filtered = df[df["nmi"].astype(str) == nmi_str].copy()
        if filtered.empty:
            raise ValueError(f"No data found for NMI {nmi} after filtering")
        return filtered

    if len(nmis) > 1:
        raise ValueError(f"Multiple NMIs detected: {', '.join(nmi_strs)}. Please specify an NMI.")
    return df
