from __future__ import annotations

from typing import Any

import numpy as np


def calculate_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "average_r": 0.0,
            "expectancy": 0.0,
            "max_drawdown_r": 0.0,
            "profit_factor": 0.0,
            "equity_curve": [0.0],
        }
    results = np.array([float(trade["result_r"]) for trade in trades])
    equity = np.concatenate(([0.0], np.cumsum(results)))
    running_max = np.maximum.accumulate(equity)
    drawdowns = running_max - equity
    wins = results[results > 0]
    losses = results[results < 0]
    profit_factor = wins.sum() / abs(losses.sum()) if losses.size else float("inf")
    return {
        "total_trades": len(trades),
        "win_rate": round(float((results > 0).mean() * 100), 2),
        "average_r": round(float(results.mean()), 3),
        "expectancy": round(float(results.mean()), 3),
        "max_drawdown_r": round(float(drawdowns.max()), 3),
        "profit_factor": round(float(profit_factor), 3) if np.isfinite(profit_factor) else 999,
        "equity_curve": [round(float(value), 3) for value in equity],
    }

