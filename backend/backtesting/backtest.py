from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

import pandas as pd

from backend.analysis.indicators import add_indicators
from backend.backtesting.metrics import calculate_metrics
from backend.execution import calculate_trade_result, estimated_funding_events, prepare_live_execution
from backend.signals.engine_v2 import evaluate


DEFAULT_RISK = {
    "capital_usd": 10_000,
    "risk_per_trade_pct": 0.5,
    "minimum_risk_per_trade_pct": 0.25,
    "volatility_target_annual_pct": 40,
    "max_notional_pct": 100,
    "minimum_rr": 1.5,
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
    "tp1_close_fraction": 0.0,
}
DEFAULT_STRATEGY = {
    "mode": "shadow",
    "cost_gate_multiple": 3.0,
    "regime": {
        "trend_adx_min": 22,
        "trend_efficiency_min": 0.30,
        "range_adx_max": 18,
        "range_efficiency_max": 0.25,
    },
    "trend": {
        "enabled": True,
        "timeframes": ["4h"],
        "breakout_period": 20,
        "relative_volume_min": 1.1,
        "initial_stop_atr": 2.5,
        "trailing_atr": 3.0,
        "expected_move_r": 3.0,
        "expected_holding_hours": 72,
        "no_followthrough_bars": 6,
        "max_holding_bars": 60,
    },
    "range": {
        "enabled": True,
        "timeframes": ["1h"],
        "zscore_entry": 2.0,
        "stop_atr": 1.5,
        "expected_holding_hours": 12,
        "max_holding_bars": 12,
    },
}
DEFAULT_VALIDATION = {
    "minimum_oos_trades": 150,
    "minimum_profit_factor": 1.2,
    "minimum_expectancy_r": 0.0,
    "maximum_drawdown_r": 12.0,
    "cost_stress_multiples": [1.0, 2.0, 3.0],
    "walk_forward_folds": 4,
}
NEUTRAL_CONTEXT = {"score": 0.0, "label": "neutral", "missing_sources": []}


def market_regime(row: pd.Series) -> str:
    adx = float(row.get("adx", 0) or 0)
    efficiency = float(row.get("efficiency_ratio", 0) or 0)
    if adx < 20 or efficiency < 0.28:
        return "lateral"
    return "alcista" if row["ema_50"] > row["ema_200"] else "bajista"


def _prepared_frames(frame_or_frames: pd.DataFrame | dict[str, pd.DataFrame]):
    raw = frame_or_frames if isinstance(frame_or_frames, dict) else {"1h": frame_or_frames}
    prepared = {}
    for timeframe, frame in raw.items():
        data = frame.copy()
        if "adx" not in data.columns:
            data = add_indicators(data)
        prepared[timeframe] = data.dropna(subset=["atr", "adx", "efficiency_ratio"]).reset_index(drop=True)
    return prepared


def _close_trade(
    signal: dict[str, Any],
    data: pd.DataFrame,
    start_index: int,
    execution: dict[str, Any],
) -> tuple[int, str, list[dict[str, Any]]]:
    side = signal["tipo"]
    entry = float(signal["entrada_sugerida"])
    stop = float(signal["stop_loss"])
    target = float(signal["take_profit_1"])
    initial_atr = float(signal["initial_atr"])
    risk_distance = abs(entry - stop)
    max_bars = int(signal.get("max_holding_bars", 60))
    no_followthrough = int(signal.get("no_followthrough_bars", 6))
    trailing_multiple = float(signal.get("trailing_atr_multiplier", 3.0))
    end_index = min(start_index + max_bars - 1, len(data) - 1)
    running_high, running_low, trailing_stop = entry, entry, stop

    for future_index in range(start_index, end_index + 1):
        candle = data.iloc[future_index]
        stop_hit = candle["low"] <= trailing_stop if side == "long" else candle["high"] >= trailing_stop
        target_hit = candle["high"] >= target if side == "long" else candle["low"] <= target
        if stop_hit:
            reason = "trailing_stop" if trailing_stop != stop else "stop_loss"
            return future_index, reason, [{"fraction": 1.0, "price": trailing_stop, "reason": reason}]
        if signal["exit_model"] == "fixed_target" and target_hit:
            return future_index, "mean_target", [{"fraction": 1.0, "price": target, "reason": "mean_target"}]

        running_high = max(running_high, float(candle["high"]))
        running_low = min(running_low, float(candle["low"]))
        if signal["exit_model"] == "chandelier":
            candidate = running_high - initial_atr * trailing_multiple if side == "long" else running_low + initial_atr * trailing_multiple
            trailing_stop = max(trailing_stop, candidate) if side == "long" else min(trailing_stop, candidate)
        mfe = max(0.0, running_high - entry) if side == "long" else max(0.0, entry - running_low)
        bars_open = future_index - start_index + 1
        if bars_open >= no_followthrough and mfe < risk_distance * 0.5:
            return future_index, "no_followthrough", [{"fraction": 1.0, "price": float(candle["close"]), "reason": "no_followthrough"}]

    final = data.iloc[end_index]
    return end_index, "max_holding", [{"fraction": 1.0, "price": float(final["close"]), "reason": "max_holding"}]


def _simulate(
    frames: dict[str, pd.DataFrame],
    *,
    symbol: str,
    risk: dict[str, Any],
    execution: dict[str, Any],
    strategy: dict[str, Any],
    relative_strength: dict[str, Any] | None,
    btc_regime: str | None,
) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    timeframes = list(dict.fromkeys(
        list(strategy.get("range", {}).get("timeframes", []))
        + list(strategy.get("trend", {}).get("timeframes", []))
    ))
    for timeframe in timeframes:
        if timeframe not in frames:
            continue
        data = frames[timeframe]
        index = 210
        while index < len(data) - 2:
            analysis_time = data.iloc[index]["close_time"]
            historical = {
                tf: values[values["close_time"] <= analysis_time]
                for tf, values in frames.items()
                if not values[values["close_time"] <= analysis_time].empty
            }
            next_row = data.iloc[index + 1]
            signal, _ = evaluate(
                symbol,
                timeframe,
                historical,
                NEUTRAL_CONTEXT,
                risk,
                market_price=float(next_row["open"]),
                strategy_config=strategy,
                execution_config=execution,
                derivatives={
                    "funding_rate": execution["fallback_funding_rate"],
                    "funding_interval_hours": execution["fallback_funding_interval_hours"],
                    "source": "configured_estimate",
                },
                # A live-universe rank cannot be replayed from a single-symbol
                # backtest, so it is reported but deliberately not used here.
                relative_strength=None,
                btc_regime=btc_regime if symbol != "BTCUSDT" else None,
            )
            if signal is None:
                index += 1
                continue
            opened_at = next_row["open_time"].to_pydatetime()
            signal["timestamp"] = opened_at.isoformat()
            signal["abierta_en"] = opened_at.isoformat()
            signal = prepare_live_execution(
                signal, market_price=float(next_row["open"]), order_book=None, config=execution
            )
            exit_index, reason, legs = _close_trade(signal, data, index + 1, execution)
            closed_at = data.iloc[exit_index]["close_time"].to_pydatetime()
            funding = estimated_funding_events(
                opened_at,
                closed_at,
                float(execution["fallback_funding_rate"]),
                int(execution["fallback_funding_interval_hours"]),
            )
            result = calculate_trade_result(signal, legs, execution, funding)
            trades.append({
                "side": signal["tipo"],
                "strategy": signal["estrategia"],
                "timeframe": timeframe,
                "entry_time": opened_at.isoformat(),
                "exit_time": closed_at.isoformat(),
                "exit_reason": reason,
                "result_r": result["resultado_r"],
                "gross_result_r": result["resultado_bruto_r"],
                "net_pnl_usd": result["pnl_neto_usd"],
                "costs_usd": result["costes_totales_usd"],
                "regime": signal["regimen"]["name"],
            })
            index = exit_index + 1
    return sorted(trades, key=lambda trade: trade["entry_time"])


def _walk_forward(trades: list[dict[str, Any]], folds: int) -> dict[str, Any]:
    if not trades:
        return {"method": "fixed_parameters_expanding_window", "folds": []}
    timestamps = pd.to_datetime([trade["entry_time"] for trade in trades], utc=True)
    boundaries = pd.date_range(timestamps.min(), timestamps.max(), periods=max(2, folds + 1))
    output = []
    for index in range(len(boundaries) - 1):
        start, end = boundaries[index], boundaries[index + 1]
        selected = [
            trade for trade in trades
            if pd.Timestamp(trade["entry_time"]) >= start
            and (pd.Timestamp(trade["entry_time"]) < end or index == len(boundaries) - 2)
        ]
        output.append({
            "fold": index + 1,
            "start": start.isoformat(),
            "end": end.isoformat(),
            **calculate_metrics(selected),
        })
    return {"method": "fixed_parameters_expanding_window", "folds": output}


def _stressed_execution(execution: dict[str, Any], multiple: float) -> dict[str, Any]:
    stressed = deepcopy(execution)
    for field in ("maker_fee_rate", "taker_fee_rate", "spread_bps", "slippage_bps", "fallback_funding_rate"):
        stressed[field] = float(stressed[field]) * multiple
    return stressed


def run_backtest(
    frame: pd.DataFrame | dict[str, pd.DataFrame],
    minimum_rr: float = 1.5,
    *,
    symbol: str = "BTCUSDT",
    risk_config: dict[str, Any] | None = None,
    execution_config: dict[str, Any] | None = None,
    strategy_config: dict[str, Any] | None = None,
    validation_config: dict[str, Any] | None = None,
    relative_strength: dict[str, Any] | None = None,
    btc_regime: str | None = None,
) -> dict[str, Any]:
    """Replay V2 chronologically and report walk-forward/stressed OOS evidence."""
    risk = {**DEFAULT_RISK, **(risk_config or {}), "minimum_rr": minimum_rr}
    execution = {**DEFAULT_EXECUTION, **(execution_config or {})}
    strategy = {**DEFAULT_STRATEGY, **(strategy_config or {})}
    validation = {**DEFAULT_VALIDATION, **(validation_config or {})}
    frames = _prepared_frames(frame)
    trades = _simulate(
        frames, symbol=symbol, risk=risk, execution=execution, strategy=strategy,
        relative_strength=relative_strength, btc_regime=btc_regime,
    )
    metrics = calculate_metrics(trades)
    regime_names = {
        "alcista": "tendencial_alcista",
        "bajista": "tendencial_bajista",
        "lateral": "lateral",
    }
    metrics["by_regime"] = {
        label: calculate_metrics([trade for trade in trades if trade["regime"] == internal])
        for label, internal in regime_names.items()
    }
    metrics["by_strategy"] = {
        model: calculate_metrics([trade for trade in trades if trade["strategy"] == model])
        for model in ("ruptura_tendencial", "reversion_lateral")
    }
    metrics["total_costs_usd"] = round(sum(float(t["costs_usd"]) for t in trades), 2)
    metrics["net_pnl_usd"] = round(sum(float(t["net_pnl_usd"]) for t in trades), 2)
    metrics["walk_forward"] = _walk_forward(trades, int(validation["walk_forward_folds"]))
    stress = {}
    for multiple in validation["cost_stress_multiples"]:
        stressed = _simulate(
            frames, symbol=symbol, risk=risk,
            execution=_stressed_execution(execution, float(multiple)),
            strategy=strategy, relative_strength=relative_strength, btc_regime=btc_regime,
        )
        stress[f"{float(multiple):g}x"] = calculate_metrics(stressed)
    metrics["cost_stress"] = stress
    gates = {
        "minimum_trades": metrics["total_trades"] >= int(validation["minimum_oos_trades"]),
        "positive_expectancy": metrics["expectancy"] > float(validation["minimum_expectancy_r"]),
        "profit_factor": metrics["profit_factor"] >= float(validation["minimum_profit_factor"]),
        "drawdown": metrics["max_drawdown_r"] <= float(validation["maximum_drawdown_r"]),
        "survives_2x_costs": stress.get("2x", {}).get("expectancy", -1) > 0,
    }
    metrics["validation"] = {
        "status": "validated" if all(gates.values()) else "shadow_required",
        "gates": gates,
        "criteria": validation,
    }
    metrics["context_assumption"] = "neutral_no_historical_context"
    metrics["relative_strength_assumption"] = "disabled_without_historical_universe"
    metrics["trades"] = trades[-200:]
    return metrics
