from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class Regime:
    name: str
    direction: str
    trending: bool
    adx: float
    efficiency_ratio: float
    daily_alignment: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _daily_alignment(frames: dict[str, pd.DataFrame]) -> str:
    daily = frames.get("1d")
    if daily is None or daily.empty:
        return "unknown"
    row = daily.iloc[-1]
    close = float(row["close"])
    ema = float(row["ema_200"])
    slope = float(row.get("ema_200_slope_20", 0) or 0)
    if close > ema and slope > 0:
        return "long"
    if close < ema and slope < 0:
        return "short"
    return "neutral"


def classify_regime(
    frames: dict[str, pd.DataFrame],
    timeframe: str,
    config: dict[str, Any],
) -> Regime:
    row = frames[timeframe].iloc[-1]
    adx = float(row.get("adx", 0) or 0)
    efficiency = float(row.get("efficiency_ratio", 0) or 0)
    trend_adx = float(config.get("trend_adx_min", 22))
    trend_efficiency = float(config.get("trend_efficiency_min", 0.30))
    range_adx = float(config.get("range_adx_max", 18))
    range_efficiency = float(config.get("range_efficiency_max", 0.25))
    alignment = _daily_alignment(frames)

    local_direction = "long" if row["ema_50"] > row["ema_200"] else "short"
    slope = float(row.get("ema_200_slope_20", 0) or 0)
    slope_aligned = (local_direction == "long" and slope > 0) or (
        local_direction == "short" and slope < 0
    )
    trending = adx >= trend_adx and efficiency >= trend_efficiency and slope_aligned
    if trending:
        return Regime(
            name=f"tendencial_{'alcista' if local_direction == 'long' else 'bajista'}",
            direction=local_direction,
            trending=True,
            adx=round(adx, 2),
            efficiency_ratio=round(efficiency, 3),
            daily_alignment=alignment,
            reason="ADX, eficiencia y pendiente confirman tendencia",
        )
    if adx <= range_adx and efficiency <= range_efficiency:
        return Regime(
            name="lateral",
            direction="neutral",
            trending=False,
            adx=round(adx, 2),
            efficiency_ratio=round(efficiency, 3),
            daily_alignment=alignment,
            reason="ADX y eficiencia confirman ausencia de tendencia",
        )
    return Regime(
        name="transicion",
        direction="neutral",
        trending=False,
        adx=round(adx, 2),
        efficiency_ratio=round(efficiency, 3),
        daily_alignment=alignment,
        reason="Régimen ambiguo; no se permite ninguna estrategia",
    )
