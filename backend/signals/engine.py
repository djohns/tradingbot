from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

import numpy as np
import pandas as pd

from backend.analysis.indicators import divergence
from backend.analysis.patterns import detect_channel_or_triangle
from backend.analysis.smc import analyze_smc
from backend.signals.risk import build_trade_plan

DISCLAIMER = (
    "Señal algorítmica con fines informativos; no constituye asesoría financiera. "
    "Verifica los supuestos y gestiona tu propio riesgo antes de decidir."
)


def _higher_timeframe_bias(frames: dict[str, pd.DataFrame]) -> str:
    votes = []
    for timeframe in ("4h", "1d"):
        if timeframe not in frames or len(frames[timeframe]) < 200:
            continue
        row = frames[timeframe].iloc[-1]
        votes.append("long" if row["ema_50"] > row["ema_200"] else "short")
    if votes.count("long") == len(votes) and votes:
        return "long"
    if votes.count("short") == len(votes) and votes:
        return "short"
    return "neutral"


def evaluate(
    symbol: str,
    timeframe: str,
    frames: dict[str, pd.DataFrame],
    context: dict[str, Any],
    risk_config: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    data = frames[timeframe]
    row, previous = data.iloc[-1], data.iloc[-2]
    smc = analyze_smc(data)
    pattern = detect_channel_or_triangle(data)
    scores = {"long": 0.0, "short": 0.0}
    reasons: dict[str, list[str]] = {"long": [], "short": []}

    if row["ema_20"] > row["ema_50"] > row["ema_200"]:
        scores["long"] += 22
        reasons["long"].append("Alineación EMA 20 > 50 > 200")
    elif row["ema_20"] < row["ema_50"] < row["ema_200"]:
        scores["short"] += 22
        reasons["short"].append("Alineación EMA 20 < 50 < 200")

    if row["macd_hist"] > 0 >= previous["macd_hist"]:
        scores["long"] += 12
        reasons["long"].append("Cruce alcista del histograma MACD")
    elif row["macd_hist"] < 0 <= previous["macd_hist"]:
        scores["short"] += 12
        reasons["short"].append("Cruce bajista del histograma MACD")

    if 30 <= row["rsi"] <= 58:
        scores["long"] += 8
        reasons["long"].append(f"RSI constructivo ({row['rsi']:.1f})")
    if 42 <= row["rsi"] <= 70:
        scores["short"] += 8
        reasons["short"].append(f"RSI con margen bajista ({row['rsi']:.1f})")

    div = divergence(data)
    if div:
        side = "long" if div == "bullish" else "short"
        scores[side] += 14
        reasons[side].append(f"Divergencia RSI {div}")

    structure = smc["structure"]
    if structure["direction"] == "bullish":
        scores["long"] += 15
        reasons["long"].append("Estructura SMC alcista")
    elif structure["direction"] == "bearish":
        scores["short"] += 15
        reasons["short"].append("Estructura SMC bajista")
    if structure["event"]:
        side = "long" if str(structure["event"]).startswith("bullish") else "short"
        scores[side] += 12
        reasons[side].append(str(structure["event"]).replace("_", " ").upper())
    if smc["sweep"]:
        side = "long" if smc["sweep"] == "bullish" else "short"
        scores[side] += 12
        reasons[side].append("Barrido de liquidez con rechazo")

    active_zones = [
        zone for zone in smc["order_blocks"] + smc["fair_value_gaps"] if zone["active"]
    ]
    price, atr = float(row["close"]), float(row["atr"])
    for zone in active_zones:
        if zone["low"] - atr <= price <= zone["high"] + atr:
            side = "long" if zone["direction"] == "bullish" else "short"
            scores[side] += 10
            reasons[side].append(f"Confluencia con {zone['kind'].replace('_', ' ')}")
            break

    if row["relative_volume"] >= 1.2:
        directional = "long" if row["close"] >= row["open"] else "short"
        scores[directional] += 8
        reasons[directional].append(f"Volumen relativo {row['relative_volume']:.1f}x")

    context_score = float(context["score"])
    scores["long"] += np.clip(context_score / 5, -15, 15)
    scores["short"] += np.clip(-context_score / 5, -15, 15)
    bias = _higher_timeframe_bias(frames)
    for side in ("long", "short"):
        if bias == side:
            scores[side] += 12
            reasons[side].append(f"Tendencia superior confirma {side}")
        elif bias != "neutral":
            scores[side] -= 18
    if context["missing_sources"]:
        scores["long"] -= min(10, len(context["missing_sources"]) * 2)
        scores["short"] -= min(10, len(context["missing_sources"]) * 2)

    side = max(scores, key=scores.get)
    confidence = int(np.clip(scores[side], 0, 100))
    diagnostics = {
        "symbol": symbol,
        "timeframe": timeframe,
        "scores": {key: round(value, 1) for key, value in scores.items()},
        "smc": smc,
        "pattern": pattern,
        "higher_timeframe_bias": bias,
    }
    if confidence < int(risk_config["minimum_confidence"]):
        return None, diagnostics

    recent = data.tail(30)
    swing = float(recent["low"].min() if side == "long" else recent["high"].max())
    plan = build_trade_plan(
        side=side,
        entry=price,
        atr=atr,
        swing=swing,
        capital=float(risk_config["capital_usd"]),
        risk_pct=float(risk_config["risk_per_trade_pct"]),
        minimum_rr=float(risk_config["minimum_rr"]),
        atr_multiplier=float(risk_config["atr_stop_multiplier"]),
    )
    if plan is None or plan.risk_reward < float(risk_config["minimum_rr"]):
        return None, diagnostics

    timestamp = datetime.now(timezone.utc).isoformat()
    signal_id = sha256(f"{symbol}:{timeframe}:{side}:{data.iloc[-1]['close_time']}".encode()).hexdigest()[:16]
    signal = {
        "id": signal_id,
        "activo": symbol,
        "timeframe": timeframe,
        "tipo": side,
        "confianza": confidence,
        "razones": reasons[side] + [f"Contexto {context['label']} ({context_score:+.1f})"],
        "entrada_sugerida": plan.entry,
        "stop_loss": plan.stop_loss,
        "take_profit_1": plan.take_profit_1,
        "take_profit_2": plan.take_profit_2,
        "ratio_riesgo_beneficio": plan.risk_reward,
        "tamano_posicion_sugerido": plan.position_size,
        "capital_en_riesgo": plan.capital_at_risk,
        "contexto_macro": context["label"],
        "datos_incompletos": context["missing_sources"],
        "timestamp": timestamp,
        "estado": "abierta",
        "resultado_r": None,
        "disclaimer": DISCLAIMER,
    }
    return signal, diagnostics

