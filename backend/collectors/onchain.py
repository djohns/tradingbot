from __future__ import annotations

from .base import HTTPCollector


class OnChainCollector(HTTPCollector):
    def snapshot(self) -> dict[str, float]:
        mempool = self.get_json("https://mempool.space/api/mempool")
        fees = self.get_json("https://mempool.space/api/v1/fees/recommended")
        hash_rate = self.get_json(
            "https://api.blockchain.info/charts/hash-rate",
            params={"timespan": "30days", "format": "json"},
        )
        points = [float(point["y"]) for point in hash_rate.get("values", [])]
        trend = 0.0
        if len(points) >= 14:
            previous = sum(points[-14:-7]) / 7
            current = sum(points[-7:]) / 7
            trend = (current / previous - 1) * 100 if previous else 0.0
        return {
            "mempool_transactions": float(mempool.get("count", 0)),
            "mempool_vsize": float(mempool.get("vsize", 0)),
            "fastest_fee": float(fees.get("fastestFee", 0)),
            "hashrate_7d_change_pct": trend,
        }

