from __future__ import annotations
import numpy as np
import pandas as pd


def normalized_pv_shape(idx: pd.DatetimeIndex) -> np.ndarray:
    """
    Normalized PV power shape (0..1) using local wall time.
    Daylight window 06:00–18:00; peak ≈ 12:00.
    """
    if idx.tz is None:
        raise ValueError("Index must be timezone-aware for accurate PV alignment.")

    # Local wall time
    local = idx.tz_convert(idx.tz)

    # Use NumPy arrays (not pandas Index) to avoid immutability issues
    hour = local.hour.to_numpy(dtype=float)
    minute = local.minute.to_numpy(dtype=float)
    hours = hour + minute / 60.0  # float ndarray

    # Map 06:00..18:00 → 0..π
    x = (hours - 6.0) / 12.0 * np.pi
    x = np.clip(x, 0.0, np.pi)  # ndarray

    shape = np.sin(x) ** 1.2  # ndarray, 0..1..0

    # Zero outside daylight (belt & braces)
    night = (hours < 6.0) | (hours > 18.0)
    shape[night] = 0.0

    return shape
