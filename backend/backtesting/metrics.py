from __future__ import annotations

from typing import Any
from math import erf, sqrt

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
            "sharpe_per_trade": 0.0,
            "sortino_per_trade": 0.0,
            "probabilistic_sharpe_pct": 0.0,
            "equity_curve": [0.0],
        }
    results = np.array([float(trade["result_r"]) for trade in trades])
    equity = np.concatenate(([0.0], np.cumsum(results)))
    running_max = np.maximum.accumulate(equity)
    drawdowns = running_max - equity
    wins = results[results > 0]
    losses = results[results < 0]
    profit_factor = wins.sum() / abs(losses.sum()) if losses.size else float("inf")
    standard_deviation = float(results.std(ddof=1)) if len(results) > 1 else 0.0
    sharpe = float(results.mean() / standard_deviation) if standard_deviation else 0.0
    downside = results[results < 0]
    downside_deviation = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    sortino = float(results.mean() / downside_deviation) if downside_deviation else 0.0
    if len(results) > 2 and standard_deviation:
        centered = (results - results.mean()) / standard_deviation
        skew = float(np.mean(centered**3))
        kurtosis = float(np.mean(centered**4))
        denominator = max(1e-12, 1 - skew * sharpe + ((kurtosis - 1) / 4) * sharpe**2)
        z_score = sharpe * sqrt(len(results) - 1) / sqrt(denominator)
        probabilistic_sharpe = 0.5 * (1 + erf(z_score / sqrt(2))) * 100
    else:
        probabilistic_sharpe = 0.0
    return {
        "total_trades": len(trades),
        "win_rate": round(float((results > 0).mean() * 100), 2),
        "average_r": round(float(results.mean()), 3),
        "expectancy": round(float(results.mean()), 3),
        "max_drawdown_r": round(float(drawdowns.max()), 3),
        "profit_factor": round(float(profit_factor), 3) if np.isfinite(profit_factor) else 999,
        "sharpe_per_trade": round(sharpe, 3),
        "sortino_per_trade": round(sortino, 3),
        "probabilistic_sharpe_pct": round(probabilistic_sharpe, 2),
        "equity_curve": [round(float(value), 3) for value in equity],
    }
