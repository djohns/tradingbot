from __future__ import annotations

from typing import Any

from .base import HTTPCollector


class CoinGeckoCollector(HTTPCollector):
    BASE_URL = "https://api.coingecko.com/api/v3"

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.headers = {"x-cg-demo-api-key": api_key} if api_key else None

    def global_market(self) -> dict[str, float]:
        data = self.get_json(f"{self.BASE_URL}/global", headers=self.headers)["data"]
        return {
            "btc_dominance": float(data["market_cap_percentage"]["btc"]),
            "eth_dominance": float(data["market_cap_percentage"].get("eth", 0)),
            "market_cap_change_24h_pct": float(data["market_cap_change_percentage_24h_usd"]),
            "total_market_cap_usd": float(data["total_market_cap"]["usd"]),
        }

