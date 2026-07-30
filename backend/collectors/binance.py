from __future__ import annotations

from typing import Any

import pandas as pd

from .base import HTTPCollector


class BinanceCollector(HTTPCollector):
    BASE_URLS = (
        "https://api.binance.com/api/v3",
        "https://api1.binance.com/api/v3",
        "https://api2.binance.com/api/v3",
        "https://api3.binance.com/api/v3",
    )

    def _request(self, path: str, params: dict[str, Any]) -> Any:
        last_error: Exception | None = None
        for base_url in self.BASE_URLS:
            try:
                return self.get_json(f"{base_url}/{path}", params=params)
            except Exception as exc:  # geographic outages should use a mirror
                last_error = exc
        raise RuntimeError(f"All Binance endpoints failed: {last_error}") from last_error

    def klines(self, symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
        raw = self._request(
            "klines",
            {"symbol": symbol.upper(), "interval": interval, "limit": min(limit, 1000)},
        )
        columns = [
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_volume",
            "trades",
            "taker_buy_base",
            "taker_buy_quote",
            "ignore",
        ]
        frame = pd.DataFrame(raw, columns=columns)
        numeric = [
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume",
            "trades",
            "taker_buy_base",
        ]
        frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
        frame["open_time"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
        frame["close_time"] = pd.to_datetime(frame["close_time"], unit="ms", utc=True)
        return frame

    def ticker_24h(self, symbol: str) -> dict[str, Any]:
        raw = self._request("ticker/24hr", {"symbol": symbol.upper()})
        return {
            "symbol": raw["symbol"],
            "price": float(raw["lastPrice"]),
            "change_24h_pct": float(raw["priceChangePercent"]),
            "volume_24h": float(raw["volume"]),
            "quote_volume_24h": float(raw["quoteVolume"]),
            "high_24h": float(raw["highPrice"]),
            "low_24h": float(raw["lowPrice"]),
        }

    def order_book(self, symbol: str, limit: int = 100) -> dict[str, Any]:
        raw = self._request(
            "depth", {"symbol": symbol.upper(), "limit": min(limit, 1000)}
        )
        bids = [(float(price), float(size)) for price, size in raw["bids"]]
        asks = [(float(price), float(size)) for price, size in raw["asks"]]
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

