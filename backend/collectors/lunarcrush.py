from __future__ import annotations

from typing import Any

from .base import HTTPCollector


class LunarCrushCollector(HTTPCollector):
    URL = "https://lunarcrush.com/api4/public/coins"

    def __init__(self, api_key: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.api_key = api_key

    def coin(self, symbol: str) -> dict[str, float]:
        payload = self.get_json(
            f"{self.URL}/{symbol.upper()}/v1",
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        data: dict[str, Any] = payload.get("data") or {}
        return {
            "galaxy_score": float(data.get("galaxy_score", 0)),
            "sentiment": float(data.get("sentiment", 0)),
            "social_dominance": float(data.get("social_dominance", 0)),
        }

