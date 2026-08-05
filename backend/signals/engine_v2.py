from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

import numpy as np
import pandas as pd

from backend.analysis.regime import Regime, classify_regime
from backend.execution import estimate_round_trip_cost

DISCLAIMER = (
    "Señal V2 en validación con fines informativos; no constituye asesoría financiera. "
    "Permanece en modo sombra hasta superar los criterios fuera de muestra."
)


def _timeframe_periods_per_year(timeframe: str) -> float:
    unit, value = timeframe[-1], float(timeframe[:-1])
    hours = value / 60 if unit == "m" else value if unit == "h" else value * 24
    return 365.25 * 24 / hours


def _risk_pct(row: pd.Series, timeframe: str, risk: dict[str, Any]) -> float:
    base = float(risk.get("risk_per_trade_pct", 0.5))
    floor = float(risk.get("minimum_risk_per_trade_pct", 0.25))
    period_vol = float(row.get("realized_vol_20", 0) or 0)
    annual_vol = period_vol * np.sqrt(_timeframe_periods_per_year(timeframe)) * 100
    target = float(risk.get("volatility_target_annual_pct", 40))
    scale = np.clip(target / annual_vol, floor / base, 1.0) if annual_vol > 0 else 1.0
    return round(base * float(scale), 4)


def _position_plan(
    *,
    side: str,
    entry: float,
    stop: float,
    target: float,
    row: pd.Series,
    timeframe: str,
    risk: dict[str, Any],
) -> dict[str, float] | None:
    distance = entry - stop if side == "long" else stop - entry
    reward = target - entry if side == "long" else entry - target
    if entry <= 0 or distance <= 0 or reward <= 0:
        return None
    risk_pct = _risk_pct(row, timeframe, risk)
    capital_risk = float(risk["capital_usd"]) * risk_pct / 100
    size = capital_risk / distance
    max_notional = float(risk["capital_usd"]) * float(risk.get("max_notional_pct", 100)) / 100
    size = min(size, max_notional / entry)
    actual_risk = size * distance
    return {
        "entry": round(entry, 8),
        "stop": round(stop, 8),
        "target": round(target, 8),
        "size": round(size, 8),
        "risk_usd": round(actual_risk, 2),
        "risk_pct": round(actual_risk / float(risk["capital_usd"]) * 100, 4),
        "rr": round(reward / distance, 2),
    }


def _trend_setup(
    data: pd.DataFrame,
    regime: Regime,
    config: dict[str, Any],
    *,
    btc_regime: str | None,
) -> tuple[str | None, list[str], dict[str, Any]]:
    row, previous = data.iloc[-1], data.iloc[-2]
    period = int(config.get("breakout_period", 20))
    upper, lower = row[f"donchian_high_{period}"], row[f"donchian_low_{period}"]
    previous_upper = previous[f"donchian_high_{period}"]
    previous_lower = previous[f"donchian_low_{period}"]
    volume_ok = float(row["relative_volume"]) >= float(config.get("relative_volume_min", 1.1))
    long_break = row["close"] > upper and previous["close"] <= previous_upper
    short_break = row["close"] < lower and previous["close"] >= previous_lower
    side = regime.direction if regime.trending else None
    if side == "long" and not long_break:
        side = None
    if side == "short" and not short_break:
        side = None
    if side == "short" and btc_regime not in {None, "tendencial_bajista"}:
        side = None
    if regime.daily_alignment not in {side, "unknown"}:
        side = None
    if not volume_ok:
        side = None
    reasons = []
    if side:
        reasons = [
            f"Ruptura confirmada del canal Donchian de {period} velas",
            regime.reason,
            f"Volumen relativo {float(row['relative_volume']):.2f}x",
            f"Tendencia diaria alineada: {regime.daily_alignment}",
        ]
    return side, reasons, {
        "channel_period": period,
        "upper": float(upper),
        "lower": float(lower),
        "volume_ok": bool(volume_ok),
        "long_break": bool(long_break),
        "short_break": bool(short_break),
    }


def _range_setup(
    data: pd.DataFrame,
    regime: Regime,
    config: dict[str, Any],
) -> tuple[str | None, list[str], dict[str, Any]]:
    row = data.iloc[-1]
    threshold = float(config.get("zscore_entry", 2.0))
    bullish_rejection = row["low"] <= row["bb_lower"] and row["close"] > row["bb_lower"] and row["close"] > row["open"]
    bearish_rejection = row["high"] >= row["bb_upper"] and row["close"] < row["bb_upper"] and row["close"] < row["open"]
    side = None
    if regime.name == "lateral" and float(row["bb_zscore"]) <= -threshold and bullish_rejection:
        side = "long"
    elif regime.name == "lateral" and float(row["bb_zscore"]) >= threshold and bearish_rejection:
        side = "short"
    reasons = []
    if side:
        reasons = [
            "Rechazo confirmado en el extremo del rango",
            f"Z-score de precio {float(row['bb_zscore']):+.2f}",
            regime.reason,
        ]
    return side, reasons, {
        "zscore": round(float(row.get("bb_zscore", 0)), 3),
        "bullish_rejection": bool(bullish_rejection),
        "bearish_rejection": bool(bearish_rejection),
    }


def evaluate(
    symbol: str,
    timeframe: str,
    frames: dict[str, pd.DataFrame],
    context: dict[str, Any],
    risk_config: dict[str, Any],
    market_price: float | None = None,
    *,
    strategy_config: dict[str, Any] | None = None,
    execution_config: dict[str, Any] | None = None,
    derivatives: dict[str, Any] | None = None,
    relative_strength: dict[str, Any] | None = None,
    btc_regime: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    strategy = strategy_config or {}
    execution = execution_config or {}
    data = frames[timeframe]
    row = data.iloc[-1]
    regime = classify_regime(frames, timeframe, strategy.get("regime", {}))
    diagnostics: dict[str, Any] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "version": "v2",
        "regime": regime.as_dict(),
        "status": "no_setup",
    }

    trend_timeframes = strategy.get("trend", {}).get("timeframes", ["4h"])
    range_timeframes = strategy.get("range", {}).get("timeframes", ["1h"])
    if regime.trending and timeframe in trend_timeframes:
        model = "ruptura_tendencial"
        side, reasons, setup = _trend_setup(
            data, regime, strategy.get("trend", {}), btc_regime=btc_regime
        )
    elif regime.name == "lateral" and timeframe in range_timeframes and strategy.get("range", {}).get("enabled", True):
        model = "reversion_lateral"
        side, reasons, setup = _range_setup(data, regime, strategy.get("range", {}))
    else:
        diagnostics["status"] = "regime_blocked"
        return None, diagnostics
    diagnostics["setup"] = setup
    if side is None:
        return None, diagnostics

    oi_change = (derivatives or {}).get("open_interest_change_pct")
    minimum_oi_change = float(strategy.get("derivatives", {}).get("minimum_open_interest_change_pct", -3.0))
    diagnostics["derivatives"] = {
        "funding_rate": (derivatives or {}).get("funding_rate"),
        "open_interest_change_pct": oi_change,
        "source": (derivatives or {}).get("source", "configured_estimate"),
    }
    if model == "ruptura_tendencial" and oi_change is not None and float(oi_change) < minimum_oi_change:
        diagnostics["status"] = "open_interest_blocked"
        return None, diagnostics

    rank = (relative_strength or {}).get("rank")
    universe = int((relative_strength or {}).get("universe", 0))
    max_rank = int(strategy.get("relative_strength", {}).get("max_rank", 3))
    if model == "ruptura_tendencial" and side == "long" and rank and rank > min(max_rank, universe):
        diagnostics["status"] = "relative_strength_blocked"
        return None, diagnostics

    entry = float(market_price) if market_price and market_price > 0 else float(row["close"])
    atr = float(row["atr"])
    if model == "ruptura_tendencial":
        stop_multiplier = float(strategy.get("trend", {}).get("initial_stop_atr", 2.5))
        stop = entry - atr * stop_multiplier if side == "long" else entry + atr * stop_multiplier
        expected_r = float(strategy.get("trend", {}).get("expected_move_r", 3.0))
        target = entry + atr * stop_multiplier * expected_r if side == "long" else entry - atr * stop_multiplier * expected_r
        exit_model = "chandelier"
    else:
        stop_multiplier = float(strategy.get("range", {}).get("stop_atr", 1.5))
        stop = min(float(row["low"]) - atr * 0.25, entry - atr * stop_multiplier) if side == "long" else max(float(row["high"]) + atr * 0.25, entry + atr * stop_multiplier)
        target = float(row["bb_middle"])
        exit_model = "fixed_target"
    plan = _position_plan(
        side=side, entry=entry, stop=stop, target=target, row=row,
        timeframe=timeframe, risk=risk_config,
    )
    if plan is None:
        diagnostics["status"] = "invalid_trade_plan"
        return None, diagnostics

    funding_rate = float((derivatives or {}).get("funding_rate", execution.get("fallback_funding_rate", 0)))
    hold_hours = float(strategy.get("trend" if model == "ruptura_tendencial" else "range", {}).get("expected_holding_hours", 48 if model == "ruptura_tendencial" else 12))
    cost = estimate_round_trip_cost(
        entry=entry,
        target=target,
        side=side,
        config=execution,
        funding_rate=funding_rate,
        holding_hours=hold_hours,
        funding_interval_hours=int((derivatives or {}).get("funding_interval_hours", execution.get("fallback_funding_interval_hours", 8))),
    )
    cost_multiple = float(strategy.get("cost_gate_multiple", 3.0))
    diagnostics["cost_gate"] = {**cost, "required_multiple": cost_multiple}
    if cost["expected_move_bps"] < cost["total_cost_bps"] * cost_multiple:
        diagnostics["status"] = "cost_blocked"
        return None, diagnostics

    confidence = 70
    confidence += min(10, int(max(0, regime.adx - 20) / 2)) if model == "ruptura_tendencial" else 5
    confidence += 5 if float(row["relative_volume"]) >= 1.25 else 0
    confidence += 5 if rank and rank <= max_rank else 0
    confidence = min(confidence, 90)
    now = datetime.now(timezone.utc).isoformat()
    signal_id = sha256(
        f"v2:{symbol}:{timeframe}:{model}:{side}:{row['close_time']}".encode()
    ).hexdigest()[:16]
    signal = {
        "id": signal_id,
        "version_estrategia": "v2",
        "estrategia": model,
        "modo": strategy.get("mode", "shadow"),
        "activo": symbol,
        "timeframe": timeframe,
        "tipo": side,
        "confianza": confidence,
        "puntuacion_confluencia": None,
        "razones": reasons,
        "regimen": regime.as_dict(),
        "entrada_sugerida": plan["entry"],
        "stop_loss": plan["stop"],
        "take_profit_1": plan["target"],
        "take_profit_2": plan["target"],
        "ratio_riesgo_beneficio": plan["rr"],
        "tamano_posicion_sugerido": plan["size"],
        "capital_en_riesgo": plan["risk_usd"],
        "riesgo_pct_efectivo": plan["risk_pct"],
        "exit_model": exit_model,
        "trailing_atr_multiplier": float(strategy.get("trend", {}).get("trailing_atr", 3.0)),
        "initial_atr": round(atr, 8),
        "no_followthrough_bars": int(strategy.get("trend", {}).get("no_followthrough_bars", 6)),
        "max_holding_bars": int(strategy.get("trend" if model == "ruptura_tendencial" else "range", {}).get("max_holding_bars", 60 if model == "ruptura_tendencial" else 12)),
        "coste_estimado_bps": cost["total_cost_bps"],
        "movimiento_esperado_bps": cost["expected_move_bps"],
        "funding_estimado": funding_rate,
        "open_interest_change_pct": oi_change,
        "calidad_derivados": (derivatives or {}).get("source", "configured_estimate"),
        "fuerza_relativa": relative_strength,
        "contexto_macro": context.get("label", "neutral"),
        "datos_incompletos": context.get("missing_sources", []),
        "timestamp": now,
        "publicada_en": now,
        "vela_analizada_cierre": row["close_time"].isoformat(),
        "precio_cierre_analizado": round(float(row["close"]), 8),
        "estado": "pendiente",
        "resultado_r": None,
        "disclaimer": DISCLAIMER,
    }
    diagnostics["status"] = "shadow_candidate" if signal["modo"] == "shadow" else "candidate"
    return signal, diagnostics


def relative_strength_ranks(
    frames_by_symbol: dict[str, dict[str, pd.DataFrame]],
    timeframe: str = "1d",
    lookback: int = 14,
) -> dict[str, dict[str, Any]]:
    values: list[tuple[str, float]] = []
    for symbol, frames in frames_by_symbol.items():
        frame = frames.get(timeframe)
        if frame is None or len(frame) <= lookback:
            continue
        momentum = float(frame.iloc[-1]["close"] / frame.iloc[-lookback - 1]["close"] - 1)
        values.append((symbol, momentum))
    values.sort(key=lambda item: item[1], reverse=True)
    return {
        symbol: {
            "rank": index + 1,
            "universe": len(values),
            "lookback_bars": lookback,
            "return_pct": round(momentum * 100, 2),
        }
        for index, (symbol, momentum) in enumerate(values)
    }
