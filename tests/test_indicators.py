import numpy as np
import pandas as pd

from backend.analysis.indicators import add_indicators


def make_frame(rows: int = 260) -> pd.DataFrame:
    close = np.linspace(100, 160, rows) + np.sin(np.arange(rows) / 5)
    return pd.DataFrame(
        {
            "open_time": pd.date_range("2025-01-01", periods=rows, freq="h", tz="UTC"),
            "close_time": pd.date_range("2025-01-01 00:59", periods=rows, freq="h", tz="UTC"),
            "open": close - 0.3,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": np.linspace(1000, 1400, rows),
        }
    )


def test_indicators_are_populated():
    result = add_indicators(make_frame())
    for column in ("ema_20", "ema_50", "ema_200", "rsi", "macd_hist", "atr", "relative_volume"):
        assert column in result
        assert np.isfinite(result[column].iloc[-1])
    assert 0 <= result["rsi"].iloc[-1] <= 100

