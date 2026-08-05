from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .base import HTTPCollector


class BinanceFuturesCollector(HTTPCollector):
    """Public USDⓈ-M Futures execution and funding data."""

    name = "Binance Futures"
    BASE_URL = "https://fapi.binance.com/fapi/v1"

    def _request(self, path: str, params: dict[str, Any]) -> Any:
        return self.get_json(f"{self.BASE_URL}/{path}", params=params)

    def book_ticker(self, symbol: str) -> dict[str, float]:
        raw = self._request("ticker/bookTicker", {"symbol": symbol.upper()})
        bid, ask = float(raw["bidPrice"]), float(raw["askPrice"])
        mid = (bid + ask) / 2
        return {
            "best_bid": bid,
            "best_ask": ask,
            "mid_price": mid,
            "spread_bps": (ask - bid) / mid * 10_000 if mid else 0.0,
        }

    def derivatives_snapshot(self, symbol: str) -> dict[str, Any]:
        premium = self._request("premiumIndex", {"symbol": symbol.upper()})
        interest = self._request("openInterest", {"symbol": symbol.upper()})
        try:
            funding_info = self._request("fundingInfo", {})
        except Exception:
            funding_info = []
        adjusted = next(
            (item for item in funding_info if item.get("symbol") == symbol.upper()),
            {},
        )
        return {
            "symbol": symbol.upper(),
            "mark_price": float(premium["markPrice"]),
            "index_price": float(premium["indexPrice"]),
            "premium_bps": (
                (float(premium["markPrice"]) / float(premium["indexPrice"]) - 1) * 10_000
                if float(premium["indexPrice"]) else 0.0
            ),
            "funding_rate": float(premium.get("lastFundingRate") or 0),
            "next_funding_time": datetime.fromtimestamp(
                int(premium["nextFundingTime"]) / 1000, tz=timezone.utc
            ).isoformat(),
            "funding_interval_hours": int(adjusted.get("fundingIntervalHours", 8)),
            "open_interest": float(interest["openInterest"]),
            "source": "binance_usdm_futures",
        }

    def funding_history(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        raw = self._request(
            "fundingRate",
            {
                "symbol": symbol.upper(),
                "startTime": int(start.timestamp() * 1000),
                "endTime": int(end.timestamp() * 1000),
                "limit": min(limit, 1000),
            },
        )
        return [
            {
                "time": datetime.fromtimestamp(
                    int(item["fundingTime"]) / 1000, tz=start.tzinfo
                ).isoformat(),
                "rate": float(item["fundingRate"]),
                "price": float(item["markPrice"]) if item.get("markPrice") else None,
                "source": "binance_usdm_futures",
            }
            for item in raw
        ]
