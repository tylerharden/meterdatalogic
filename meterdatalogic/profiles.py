from __future__ import annotations
import numpy as np
import pandas as pd


# ...existing code...
def normalized_pv_shape(idx: pd.DatetimeIndex) -> np.ndarray:
    """
    Normalized PV power shape (0..1) using local wall time.
    Daylight window 06:00–18:00; peak ≈ 12:00.
    """
    if idx.tz is None:
        raise ValueError("Index must be timezone-aware for accurate PV alignment.")

    # Local wall time (tz-aware index already local)
    local = idx

    hour = local.hour.to_numpy(dtype=float)
    minute = local.minute.to_numpy(dtype=float)
    hours = hour + minute / 60.0

    x = (hours - 6.0) / 12.0 * np.pi
    x = np.clip(x, 0.0, np.pi)
    shape = np.sin(x) ** 1.2

    night = (hours < 6.0) | (hours > 18.0)
    shape[night] = 0.0
    return shape
