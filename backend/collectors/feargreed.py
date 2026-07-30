from __future__ import annotations

from .base import HTTPCollector


class FearGreedCollector(HTTPCollector):
    URL = "https://api.alternative.me/fng/"

    def current(self) -> dict[str, object]:
        item = self.get_json(self.URL, params={"limit": 1, "format": "json"})["data"][0]
        return {
            "value": int(item["value"]),
            "classification": item["value_classification"],
            "timestamp": item["timestamp"],
        }

