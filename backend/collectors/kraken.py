from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd

from .base import APIError, HTTPCollector


class KrakenCollector(HTTPCollector):
    """Public Kraken spot market-data adapter with Binance-compatible output."""

    name = "Kraken"
    BASE_URL = "https://api.kraken.com/0/public"
    PAIRS = {
        "BTCUSDT": "XBTUSDT",
        "ETHUSDT": "ETHUSDT",
        "SOLUSDT": "SOLUSDT",
        "BNBUSDT": "BNBUSDT",
    }
    INTERVALS = {
        "15m": (15, timedelta(minutes=15)),
        "1h": (60, timedelta(hours=1)),
        "4h": (240, timedelta(hours=4)),
        "1d": (1440, timedelta(days=1)),
    }

    def _pair(self, symbol: str) -> str:
        normalized = symbol.upper()
        if normalized not in self.PAIRS:
            raise ValueError(f"Kraken pair mapping missing for {normalized}")
        return self.PAIRS[normalized]

    def _result(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = self.get_json(f"{self.BASE_URL}/{path}", params=params)
        errors = payload.get("error") or []
        if errors:
            raise APIError(f"Kraken {path} error: {', '.join(errors)}")
        result = payload.get("result")
        if not isinstance(result, dict) or not result:
            raise APIError(f"Kraken {path} returned no result")
        return result

    @staticmethod
    def _pair_payload(result: dict[str, Any]) -> Any:
        pair_keys = [key for key in result if key != "last"]
        if not pair_keys:
            raise APIError("Kraken response did not include a pair")
        return result[pair_keys[0]]

    def klines(self, symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
        if interval not in self.INTERVALS:
            raise ValueError(f"Kraken interval mapping missing for {interval}")
        interval_minutes, duration = self.INTERVALS[interval]
        result = self._result(
            "OHLC",
            {"pair": self._pair(symbol), "interval": interval_minutes},
        )
        rows = self._pair_payload(result)[-min(limit, 720) :]
        frame = pd.DataFrame(
            rows,
            columns=[
                "open_time",
                "open",
                "high",
                "low",
                "close",
                "vwap",
                "volume",
                "trades",
            ],
        )
        numeric = ["open", "high", "low", "close", "vwap", "volume", "trades"]
        frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
        frame["open_time"] = pd.to_datetime(frame["open_time"], unit="s", utc=True)
        frame["close_time"] = frame["open_time"] + duration
        frame["quote_volume"] = frame["vwap"] * frame["volume"]
        frame["taker_buy_base"] = 0.0
        return frame

    def ticker_24h(self, symbol: str) -> dict[str, Any]:
        result = self._result("Ticker", {"pair": self._pair(symbol)})
        raw = self._pair_payload(result)
        price = float(raw["c"][0])
        open_price = float(raw["o"])
        return {
            "symbol": symbol.upper(),
            "price": price,
            "change_24h_pct": (price / open_price - 1) * 100 if open_price else 0.0,
            "volume_24h": float(raw["v"][1]),
            "quote_volume_24h": float(raw["v"][1]) * float(raw["p"][1]),
            "high_24h": float(raw["h"][1]),
            "low_24h": float(raw["l"][1]),
        }

    def order_book(self, symbol: str, limit: int = 100) -> dict[str, Any]:
        result = self._result(
            "Depth",
            {"pair": self._pair(symbol), "count": min(limit, 500)},
        )
        raw = self._pair_payload(result)
        bids = [(float(row[0]), float(row[1])) for row in raw["bids"]]
        asks = [(float(row[0]), float(row[1])) for row in raw["asks"]]
        bid_notional = sum(price * size for price, size in bids)
        ask_notional = sum(price * size for price, size in asks)
        total = bid_notional + ask_notional
        return {
            "bid_notional": bid_notional,
            "ask_notional": ask_notional,
            "imbalance": (bid_notional - ask_notional) / total if total else 0.0,
            "largest_bid_wall": max(bids, key=lambda item: item[0] * item[1]),
            "largest_ask_wall": max(asks, key=lambda item: item[0] * item[1]),
        }
