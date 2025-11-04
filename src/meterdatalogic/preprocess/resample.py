import pandas as pd

def resample_to(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """
    Resample energy to target cadence by summing within bins.
    Expects df['kwh'] and tz-aware DatetimeIndex.
    """
    if "kwh" not in df.columns:
        raise ValueError("DataFrame must contain 'kwh'")
    return df.resample(freq).sum()
