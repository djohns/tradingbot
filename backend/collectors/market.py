from __future__ import annotations

import os
from typing import Any

from .binance import BinanceCollector
from .kraken import KrakenCollector


class ResilientMarketCollector:
    """Use a preferred public exchange and fail over for each data operation."""

    def __init__(self, **kwargs: Any) -> None:
        preference = os.getenv("MARKET_DATA_PROVIDER", "auto").strip().lower()
        binance = BinanceCollector(**kwargs)
        binance.name = "Binance"
        kraken = KrakenCollector(**kwargs)
        if preference not in {"auto", "binance", "kraken"}:
            raise ValueError("MARKET_DATA_PROVIDER must be auto, binance, or kraken")
        if preference == "kraken" or (
            preference == "auto" and os.getenv("GITHUB_ACTIONS") == "true"
        ):
            self.providers = [kraken, binance]
        else:
            self.providers = [binance, kraken]
        self.disabled: set[str] = set()
        self.last_provider: str | None = None

    @property
    def provider_order(self) -> list[str]:
        return [provider.name for provider in self.providers]

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        failures: list[str] = []
        for provider in self.providers:
            if provider.name in self.disabled:
                continue
            try:
                value = getattr(provider, method)(*args, **kwargs)
                self.last_provider = provider.name
                return value
            except Exception as exc:
                message = str(exc)
                failures.append(f"{provider.name}: {message}")
                # A legal restriction applies to the runner, not a single pair,
                # so avoid repeating blocked Binance calls for every asset.
                if provider.name == "Binance" and "HTTP 451" in message:
                    self.disabled.add(provider.name)
        raise RuntimeError("All market providers failed: " + " | ".join(failures))

    def klines(self, symbol: str, interval: str, limit: int = 500):
        return self._call("klines", symbol, interval, limit)

    def ticker_24h(self, symbol: str):
        return self._call("ticker_24h", symbol)

    def order_book(self, symbol: str, limit: int = 100):
        return self._call("order_book", symbol, limit)
