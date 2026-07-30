from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class TradePlan:
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_reward: float
    position_size: float
    capital_at_risk: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def build_trade_plan(
    *,
    side: str,
    entry: float,
    atr: float,
    swing: float,
    capital: float,
    risk_pct: float,
    minimum_rr: float,
    atr_multiplier: float,
) -> TradePlan | None:
    atr_distance = atr * atr_multiplier
    if side == "long":
        structural_stop = swing - atr * 0.15
        stop = min(entry - atr_distance, structural_stop)
        risk = entry - stop
        tp1, tp2 = entry + risk * minimum_rr, entry + risk * max(2.0, minimum_rr + 0.5)
    else:
        structural_stop = swing + atr * 0.15
        stop = max(entry + atr_distance, structural_stop)
        risk = stop - entry
        tp1, tp2 = entry - risk * minimum_rr, entry - risk * max(2.0, minimum_rr + 0.5)
    if risk <= 0 or entry <= 0:
        return None
    capital_at_risk = capital * risk_pct / 100
    size = capital_at_risk / risk
    actual_rr = abs(tp1 - entry) / risk
    return TradePlan(
        entry=round(entry, 8),
        stop_loss=round(stop, 8),
        take_profit_1=round(tp1, 8),
        take_profit_2=round(tp2, 8),
        risk_reward=round(actual_rr, 2),
        position_size=round(size, 8),
        capital_at_risk=round(capital_at_risk, 2),
    )

