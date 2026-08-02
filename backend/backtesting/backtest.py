from __future__ import annotations

from typing import Any

import pandas as pd

from backend.analysis.indicators import add_indicators
from backend.backtesting.metrics import calculate_metrics
from backend.execution import (
    calculate_trade_result,
    estimated_funding_events,
    prepare_live_execution,
)
from backend.signals.engine import evaluate


DEFAULT_RISK = {
    "capital_usd": 10_000,
    "risk_per_trade_pct": 1.0,
    "minimum_rr": 1.5,
    "minimum_confidence": 62,
    "atr_stop_multiplier": 1.5,
}
DEFAULT_EXECUTION = {
    "market": "binance_usdm_futures",
    "maker_fee_rate": 0.0002,
    "taker_fee_rate": 0.0005,
    "entry_order_type": "taker",
    "exit_order_type": "taker",
    "bnb_fee_discount_pct": 0.0,
    "spread_bps": 2.0,
    "slippage_bps": 3.0,
    "fallback_funding_rate": 0.0001,
    "fallback_funding_interval_hours": 8,
    "max_bars_open": 24,
    "tp1_close_fraction": 0.5,
    "move_stop_to_break_even": True,
}
NEUTRAL_CONTEXT = {"score": 0.0, "label": "neutral", "missing_sources": []}


def market_regime(row: pd.Series) -> str:
    distance = abs(row["ema_50"] / row["ema_200"] - 1)
    if distance < 0.015:
        return "lateral"
    return "alcista" if row["ema_50"] > row["ema_200"] else "bajista"


def _prepared_frames(frame_or_frames: pd.DataFrame | dict[str, pd.DataFrame]):
    raw_frames = frame_or_frames if isinstance(frame_or_frames, dict) else {"1h": frame_or_frames}
    prepared = {}
    for timeframe, frame in raw_frames.items():
        data = frame.copy()
        if "ema_200" not in data.columns:
            data = add_indicators(data)
        prepared[timeframe] = data.dropna().reset_index(drop=True)
    return prepared


def run_backtest(
    frame: pd.DataFrame | dict[str, pd.DataFrame],
    minimum_rr: float = 1.5,
    *,
    symbol: str = "BTCUSDT",
    risk_config: dict[str, Any] | None = None,
    execution_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Walk-forward the live scoring logic with next-bar, net execution PnL.

    Historical macro/on-chain snapshots are not available, so the context
    component is held neutral rather than leaking today's context into history.
    """
    risk = {**DEFAULT_RISK, **(risk_config or {}), "minimum_rr": minimum_rr}
    execution = {**DEFAULT_EXECUTION, **(execution_config or {})}
    frames = _prepared_frames(frame)
    timeframe = "1h" if "1h" in frames else next(iter(frames))
    data = frames[timeframe]
    trades: list[dict[str, Any]] = []
    index = 200
    while index < len(data) - 2:
        analysis_row = data.iloc[index]
        next_row = data.iloc[index + 1]
        analysis_time = analysis_row["close_time"]
        historical_frames = {
            tf: values[values["close_time"] <= analysis_time]
            for tf, values in frames.items()
            if not values[values["close_time"] <= analysis_time].empty
        }
        signal, _ = evaluate(
            symbol,
            timeframe,
            historical_frames,
            NEUTRAL_CONTEXT,
            risk,
            market_price=float(next_row["open"]),
        )
        if signal is None:
            index += 1
            continue

        opened_at = next_row["open_time"].to_pydatetime()
        signal["timestamp"] = opened_at.isoformat()
        signal["abierta_en"] = opened_at.isoformat()
        signal = prepare_live_execution(
            signal,
            market_price=float(next_row["open"]),
            order_book=None,
            config=execution,
        )
        side = signal["tipo"]
        close_fraction = float(execution["tp1_close_fraction"])
        tp1_reached = False
        tp1_time = None
        exit_index = min(index + int(execution["max_bars_open"]), len(data) - 1)
        exit_reason = "time_stop"
        exit_legs: list[dict[str, Any]] = []
        for future_index in range(index + 1, exit_index + 1):
            future = data.iloc[future_index]
            active_stop = (
                float(signal["entrada_sugerida"])
                if tp1_reached and execution["move_stop_to_break_even"]
                else float(signal["stop_loss"])
            )
            stop_hit = (
                future["low"] <= active_stop
                if side == "long"
                else future["high"] >= active_stop
            )
            tp1_hit = (
                future["high"] >= signal["take_profit_1"]
                if side == "long"
                else future["low"] <= signal["take_profit_1"]
            )
            tp2_hit = (
                future["high"] >= signal["take_profit_2"]
                if side == "long"
                else future["low"] <= signal["take_profit_2"]
            )
            if stop_hit:
                if tp1_reached:
                    exit_legs.append(
                        {"fraction": close_fraction, "price": signal["take_profit_1"], "reason": "tp1"}
                    )
                exit_legs.append(
                    {
                        "fraction": 1 - close_fraction if tp1_reached else 1.0,
                        "price": active_stop,
                        "reason": "break_even" if tp1_reached else "stop_loss",
                    }
                )
                exit_reason, exit_index = exit_legs[-1]["reason"], future_index
                break
            if tp2_hit:
                tp1_reached = True
                tp1_time = future["close_time"].to_pydatetime()
                exit_legs = [
                    {"fraction": close_fraction, "price": signal["take_profit_1"], "reason": "tp1"},
                    {"fraction": 1 - close_fraction, "price": signal["take_profit_2"], "reason": "tp2"},
                ]
                exit_reason, exit_index = "tp2", future_index
                break
            if tp1_hit and not tp1_reached:
                tp1_reached = True
                tp1_time = future["close_time"].to_pydatetime()
        if not exit_legs:
            final = data.iloc[exit_index]
            if tp1_reached:
                exit_legs.append(
                    {"fraction": close_fraction, "price": signal["take_profit_1"], "reason": "tp1"}
                )
            exit_legs.append(
                {
                    "fraction": 1 - close_fraction if tp1_reached else 1.0,
                    "price": float(final["close"]),
                    "reason": "time_stop",
                }
            )
        if tp1_time:
            signal["tp1_alcanzado_en"] = tp1_time.isoformat()
        closed_at = data.iloc[exit_index]["close_time"].to_pydatetime()
        funding = estimated_funding_events(
            opened_at,
            closed_at,
            float(execution["fallback_funding_rate"]),
            int(execution["fallback_funding_interval_hours"]),
        )
        result = calculate_trade_result(signal, exit_legs, execution, funding)
        trades.append(
            {
                "side": side,
                "entry_time": opened_at.isoformat(),
                "exit_time": closed_at.isoformat(),
                "exit_reason": exit_reason,
                "result_r": result["resultado_r"],
                "gross_result_r": result["resultado_bruto_r"],
                "net_pnl_usd": result["pnl_neto_usd"],
                "costs_usd": result["costes_totales_usd"],
                "regime": market_regime(analysis_row),
            }
        )
        index = exit_index + 1

    metrics = calculate_metrics(trades)
    metrics["by_regime"] = {
        regime: calculate_metrics([trade for trade in trades if trade["regime"] == regime])
        for regime in ("alcista", "bajista", "lateral")
    }
    metrics["total_costs_usd"] = round(sum(float(t["costs_usd"]) for t in trades), 2)
    metrics["net_pnl_usd"] = round(sum(float(t["net_pnl_usd"]) for t in trades), 2)
    metrics["context_assumption"] = "neutral_no_historical_context"
    metrics["trades"] = trades[-100:]
    return metrics
