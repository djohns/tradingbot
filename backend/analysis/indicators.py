from __future__ import annotations

import numpy as np
import pandas as pd


def add_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    """Return OHLCV data enriched with dependency-light technical indicators."""
    data = frame.copy()
    close = data["close"]
    for period in (20, 50, 200):
        data[f"ema_{period}"] = close.ewm(span=period, adjust=False).mean()

    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    data["rsi"] = (100 - 100 / (1 + rs)).fillna(50)

    ema_12 = close.ewm(span=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, adjust=False).mean()
    data["macd"] = ema_12 - ema_26
    data["macd_signal"] = data["macd"].ewm(span=9, adjust=False).mean()
    data["macd_hist"] = data["macd"] - data["macd_signal"]

    middle = close.rolling(20).mean()
    deviation = close.rolling(20).std(ddof=0)
    data["bb_middle"] = middle
    data["bb_upper"] = middle + 2 * deviation
    data["bb_lower"] = middle - 2 * deviation
    data["bb_width"] = (data["bb_upper"] - data["bb_lower"]) / middle

    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            data["high"] - data["low"],
            (data["high"] - previous_close).abs(),
            (data["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    data["atr"] = true_range.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    data["volume_sma_20"] = data["volume"].rolling(20).mean()
    data["relative_volume"] = data["volume"] / data["volume_sma_20"].replace(0, np.nan)

    # V2: every level is shifted one bar so the current candle can be tested
    # against information that was fully known before it closed.
    for period in (10, 20, 55):
        data[f"donchian_high_{period}"] = data["high"].rolling(period).max().shift(1)
        data[f"donchian_low_{period}"] = data["low"].rolling(period).min().shift(1)

    up_move = data["high"].diff()
    down_move = -data["low"].diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=data.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=data.index,
    )
    atr_wilder = true_range.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean() / atr_wilder
    minus_di = 100 * minus_dm.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean() / atr_wilder
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    data["adx"] = dx.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    data["plus_di"] = plus_di
    data["minus_di"] = minus_di

    lookback = 20
    net_change = close.diff(lookback).abs()
    travelled = close.diff().abs().rolling(lookback).sum()
    data["efficiency_ratio"] = net_change / travelled.replace(0, np.nan)
    log_returns = np.log(close / close.shift(1))
    data["realized_vol_20"] = log_returns.rolling(20).std(ddof=0)
    data["bb_zscore"] = (close - middle) / deviation.replace(0, np.nan)
    data["ema_200_slope_20"] = data["ema_200"].pct_change(20)
    data["atr_pct"] = data["atr"] / close.replace(0, np.nan)
    if "taker_buy_base" in data:
        data["taker_buy_ratio"] = data["taker_buy_base"] / data["volume"].replace(0, np.nan)
    else:
        data["taker_buy_ratio"] = np.nan
    return data


def divergence(frame: pd.DataFrame, lookback: int = 30) -> str | None:
    """Detect a conservative price/RSI divergence over two halves of a window."""
    sample = frame.tail(lookback)
    if len(sample) < lookback:
        return None
    left, right = sample.iloc[: lookback // 2], sample.iloc[lookback // 2 :]
    if right["low"].min() < left["low"].min() and right["rsi"].min() > left["rsi"].min():
        return "bullish"
    if right["high"].max() > left["high"].max() and right["rsi"].max() < left["rsi"].max():
        return "bearish"
    return None
