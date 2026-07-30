from __future__ import annotations

import numpy as np
import pandas as pd


def detect_channel_or_triangle(frame: pd.DataFrame, lookback: int = 40) -> dict[str, object]:
    """Fit high/low trend lines and classify the broad consolidation geometry."""
    sample = frame.tail(lookback)
    if len(sample) < lookback:
        return {"pattern": None, "confidence": 0}
    x = np.arange(lookback)
    high_slope, high_intercept = np.polyfit(x, sample["high"], 1)
    low_slope, low_intercept = np.polyfit(x, sample["low"], 1)
    price = float(sample["close"].iloc[-1])
    normalized_high = high_slope / price
    normalized_low = low_slope / price
    epsilon = 0.0005
    pattern = None
    if normalized_high < -epsilon and normalized_low > epsilon:
        pattern = "symmetric_triangle"
    elif abs(normalized_high) <= epsilon and normalized_low > epsilon:
        pattern = "ascending_triangle"
    elif normalized_high < -epsilon and abs(normalized_low) <= epsilon:
        pattern = "descending_triangle"
    elif normalized_high > epsilon and normalized_low > epsilon:
        pattern = "ascending_channel"
    elif normalized_high < -epsilon and normalized_low < -epsilon:
        pattern = "descending_channel"
    convergence = abs((high_intercept + high_slope * (lookback - 1)) - (low_intercept + low_slope * (lookback - 1)))
    initial = abs(high_intercept - low_intercept)
    confidence = int(np.clip((1 - convergence / initial) * 100, 0, 90)) if initial else 0
    return {"pattern": pattern, "confidence": confidence}

