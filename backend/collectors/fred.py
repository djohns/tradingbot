from __future__ import annotations

from typing import Any

from .base import HTTPCollector


class FredCollector(HTTPCollector):
    URL = "https://api.stlouisfed.org/fred/series/observations"
    SERIES = ("DTWEXBGS", "FEDFUNDS", "M2SL", "T10Y2Y", "CPIAUCSL")

    def __init__(self, api_key: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.api_key = api_key

    def series(self, series_id: str, limit: int = 24) -> list[dict[str, object]]:
        payload = self.get_json(
            self.URL,
            params={
                "series_id": series_id,
                "api_key": self.api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": limit,
            },
        )
        values = []
        for row in reversed(payload["observations"]):
            if row["value"] != ".":
                values.append({"date": row["date"], "value": float(row["value"])})
        return values

    def snapshot(self) -> dict[str, list[dict[str, object]]]:
        return {series_id: self.series(series_id) for series_id in self.SERIES}

