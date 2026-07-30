from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd


@dataclass
class Zone:
    kind: str
    direction: str
    low: float
    high: float
    index: int
    active: bool = True

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def swing_points(frame: pd.DataFrame, window: int = 3) -> pd.DataFrame:
    data = frame.copy()
    rolling = window * 2 + 1
    data["swing_high"] = data["high"].eq(
        data["high"].rolling(rolling, center=True).max()
    )
    data["swing_low"] = data["low"].eq(
        data["low"].rolling(rolling, center=True).min()
    )
    return data


def market_structure(frame: pd.DataFrame) -> dict[str, object]:
    data = swing_points(frame)
    highs = data[data["swing_high"]].tail(3)
    lows = data[data["swing_low"]].tail(3)
    close = float(data["close"].iloc[-1])
    direction = "neutral"
    event = None
    if len(highs) >= 2 and len(lows) >= 2:
        higher_high = highs["high"].iloc[-1] > highs["high"].iloc[-2]
        higher_low = lows["low"].iloc[-1] > lows["low"].iloc[-2]
        lower_high = highs["high"].iloc[-1] < highs["high"].iloc[-2]
        lower_low = lows["low"].iloc[-1] < lows["low"].iloc[-2]
        if higher_high and higher_low:
            direction = "bullish"
        elif lower_high and lower_low:
            direction = "bearish"
        last_high = float(highs["high"].iloc[-1])
        last_low = float(lows["low"].iloc[-1])
        previous_close = float(data["close"].iloc[-2])
        if close > last_high >= previous_close:
            event = "bullish_bos" if direction == "bullish" else "bullish_choch"
        elif close < last_low <= previous_close:
            event = "bearish_bos" if direction == "bearish" else "bearish_choch"
    return {"direction": direction, "event": event}


def fair_value_gaps(frame: pd.DataFrame, lookback: int = 80) -> list[Zone]:
    data = frame.tail(lookback).reset_index(drop=True)
    zones: list[Zone] = []
    for index in range(2, len(data)):
        first, third = data.iloc[index - 2], data.iloc[index]
        if third["low"] > first["high"]:
            zone = Zone("fvg", "bullish", float(first["high"]), float(third["low"]), index)
            zone.active = float(data["low"].iloc[index:].min()) > zone.low
            zones.append(zone)
        elif third["high"] < first["low"]:
            zone = Zone("fvg", "bearish", float(third["high"]), float(first["low"]), index)
            zone.active = float(data["high"].iloc[index:].max()) < zone.high
            zones.append(zone)
    return zones[-10:]


def order_blocks(frame: pd.DataFrame, lookback: int = 80) -> list[Zone]:
    data = frame.tail(lookback).reset_index(drop=True)
    atr = data["atr"].replace(0, np.nan)
    impulse = (data["close"] - data["open"]).abs() > atr * 1.25
    zones: list[Zone] = []
    for index in range(1, len(data)):
        previous, current = data.iloc[index - 1], data.iloc[index]
        if not bool(impulse.iloc[index]):
            continue
        if current["close"] > current["open"] and previous["close"] < previous["open"]:
            zones.append(
                Zone(
                    "order_block",
                    "bullish",
                    float(previous["low"]),
                    float(previous["open"]),
                    index - 1,
                )
            )
        elif current["close"] < current["open"] and previous["close"] > previous["open"]:
            zones.append(
                Zone(
                    "order_block",
                    "bearish",
                    float(previous["open"]),
                    float(previous["high"]),
                    index - 1,
                )
            )
    current_price = float(data["close"].iloc[-1])
    for zone in zones:
        zone.active = (
            current_price >= zone.low if zone.direction == "bullish" else current_price <= zone.high
        )
    return zones[-10:]


def liquidity_sweep(frame: pd.DataFrame, lookback: int = 20) -> str | None:
    if len(frame) < lookback + 2:
        return None
    current = frame.iloc[-1]
    prior = frame.iloc[-lookback - 1 : -1]
    prior_high, prior_low = prior["high"].max(), prior["low"].min()
    if current["high"] > prior_high and current["close"] < prior_high:
        return "bearish"
    if current["low"] < prior_low and current["close"] > prior_low:
        return "bullish"
    return None


def liquidity_levels(frame: pd.DataFrame, tolerance_atr: float = 0.2) -> list[dict[str, object]]:
    data = swing_points(frame).tail(100)
    atr = float(data["atr"].iloc[-1])
    levels: list[dict[str, object]] = []
    for kind, column in (("equal_highs", "high"), ("equal_lows", "low")):
        mask = data["swing_high"] if kind == "equal_highs" else data["swing_low"]
        values = data.loc[mask, column].tolist()
        for first, second in zip(values, values[1:]):
            if abs(second - first) <= atr * tolerance_atr:
                levels.append({"kind": kind, "price": round((first + second) / 2, 8)})
    return levels[-6:]


def analyze_smc(frame: pd.DataFrame) -> dict[str, object]:
    return {
        "structure": market_structure(frame),
        "sweep": liquidity_sweep(frame),
        "order_blocks": [zone.as_dict() for zone in order_blocks(frame)],
        "fair_value_gaps": [zone.as_dict() for zone in fair_value_gaps(frame)],
        "liquidity_levels": liquidity_levels(frame),
    }

