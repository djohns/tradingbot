from __future__ import annotations

from typing import Any

import numpy as np


def _change(values: list[dict[str, object]], periods: int = 1) -> float:
    if len(values) <= periods:
        return 0.0
    old, new = float(values[-periods - 1]["value"]), float(values[-1]["value"])
    return (new / old - 1) * 100 if old else 0.0


def macro_score(fred: dict[str, list[dict[str, object]]] | None) -> tuple[float, list[str]]:
    if not fred:
        return 0.0, ["FRED no disponible; contexto macro neutral"]
    score = 0.0
    reasons: list[str] = []
    dxy = _change(fred.get("DTWEXBGS", []), min(20, max(len(fred.get("DTWEXBGS", [])) - 1, 1)))
    m2 = _change(fred.get("M2SL", []), min(3, max(len(fred.get("M2SL", [])) - 1, 1)))
    funds = _change(fred.get("FEDFUNDS", []), min(3, max(len(fred.get("FEDFUNDS", [])) - 1, 1)))
    curve_values = fred.get("T10Y2Y", [])
    curve = float(curve_values[-1]["value"]) if curve_values else 0.0
    cpi = _change(fred.get("CPIAUCSL", []), min(12, max(len(fred.get("CPIAUCSL", [])) - 1, 1)))

    score += np.clip(-dxy * 8, -25, 25)
    score += np.clip(m2 * 8, -30, 30)
    score += np.clip(-funds * 2, -20, 20)
    score += 10 if curve > 0 else -10
    score += np.clip((3 - cpi) * 4, -15, 15)
    reasons.extend(
        [
            f"Dólar 20 períodos: {dxy:+.2f}%",
            f"M2 3 períodos: {m2:+.2f}%",
            f"Curva 10Y-2Y: {curve:+.2f}",
        ]
    )
    return float(np.clip(score, -100, 100)), reasons


def compose_context(
    *,
    fear_greed: dict[str, Any] | None,
    global_market: dict[str, Any] | None,
    fred: dict[str, Any] | None,
    onchain: dict[str, Any] | None,
    weights: dict[str, float],
) -> dict[str, Any]:
    macro, macro_reasons = macro_score(fred)
    fg_value = int(fear_greed["value"]) if fear_greed else 50
    # Contrarian but capped: fear favors accumulation; greed favors distribution.
    fg_score = float(np.clip((50 - fg_value) * 1.3, -50, 50))
    dominance = float(global_market["btc_dominance"]) if global_market else 50.0
    dominance_score = float(np.clip((52 - dominance) * 3, -40, 40))
    hash_change = float(onchain["hashrate_7d_change_pct"]) if onchain else 0.0
    onchain_score = float(np.clip(hash_change * 3, -30, 30))
    score = (
        macro * weights.get("macro_weight", 0.45)
        + fg_score * weights.get("fear_greed_weight", 0.25)
        + dominance_score * weights.get("btc_dominance_weight", 0.15)
        + onchain_score * weights.get("onchain_weight", 0.15)
    )
    missing = [
        name
        for name, value in (
            ("fear_greed", fear_greed),
            ("coingecko", global_market),
            ("fred", fred),
            ("onchain", onchain),
        )
        if value is None
    ]
    label = "expansivo" if score >= 20 else "restrictivo" if score <= -20 else "neutral"
    return {
        "score": round(float(np.clip(score, -100, 100)), 1),
        "label": label,
        "macro_score": round(macro, 1),
        "fear_greed": fear_greed,
        "global_market": global_market,
        "onchain": onchain,
        "macro_reasons": macro_reasons,
        "missing_sources": missing,
    }

