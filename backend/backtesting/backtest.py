from __future__ import annotations

from typing import Any

import pandas as pd

from backend.analysis.indicators import add_indicators
from backend.backtesting.metrics import calculate_metrics


def market_regime(row: pd.Series) -> str:
    distance = abs(row["ema_50"] / row["ema_200"] - 1)
    if distance < 0.015:
        return "lateral"
    return "alcista" if row["ema_50"] > row["ema_200"] else "bajista"


def run_backtest(frame: pd.DataFrame, minimum_rr: float = 1.5) -> dict[str, Any]:
    """Conservative EMA/MACD simulator using subsequent OHLC to resolve SL/TP."""
    data = add_indicators(frame).dropna().reset_index(drop=True)
    trades: list[dict[str, Any]] = []
    index = 1
    while index < len(data) - 2:
        row, previous = data.iloc[index], data.iloc[index - 1]
        side = None
        if row["ema_20"] > row["ema_50"] > row["ema_200"] and row["macd_hist"] > 0 >= previous["macd_hist"]:
            side = "long"
        elif row["ema_20"] < row["ema_50"] < row["ema_200"] and row["macd_hist"] < 0 <= previous["macd_hist"]:
            side = "short"
        if not side:
            index += 1
            continue
        entry, atr = float(row["close"]), float(row["atr"])
        stop = entry - atr * 1.5 if side == "long" else entry + atr * 1.5
        target = entry + atr * 1.5 * minimum_rr if side == "long" else entry - atr * 1.5 * minimum_rr
        result, exit_index = None, index + 1
        for future_index in range(index + 1, min(index + 100, len(data))):
            future = data.iloc[future_index]
            # If both levels touch within a candle, use the adverse outcome.
            if side == "long":
                if future["low"] <= stop:
                    result = -1.0
                elif future["high"] >= target:
                    result = minimum_rr
            else:
                if future["high"] >= stop:
                    result = -1.0
                elif future["low"] <= target:
                    result = minimum_rr
            if result is not None:
                exit_index = future_index
                break
        if result is None:
            final = float(data.iloc[min(index + 99, len(data) - 1)]["close"])
            raw_r = (final - entry) / abs(entry - stop)
            result = raw_r if side == "long" else -raw_r
        trades.append(
            {
                "side": side,
                "entry_time": str(row["open_time"]),
                "result_r": round(float(result), 3),
                "regime": market_regime(row),
            }
        )
        index = exit_index + 1
    metrics = calculate_metrics(trades)
    metrics["by_regime"] = {
        regime: calculate_metrics([trade for trade in trades if trade["regime"] == regime])
        for regime in ("alcista", "bajista", "lateral")
    }
    metrics["trades"] = trades[-100:]
    return metrics

