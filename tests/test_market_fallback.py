from backend.collectors.market import ResilientMarketCollector


class Provider:
    def __init__(self, name, result=None, error=None):
        self.name = name
        self.result = result
        self.error = error
        self.calls = 0

    def klines(self, *args, **kwargs):
        self.calls += 1
        if self.error:
            raise RuntimeError(self.error)
        return self.result


def test_451_disables_binance_and_uses_fallback():
    binance = Provider("Binance", error="HTTP 451 unavailable")
    kraken = Provider("Kraken", result="candles")
    collector = ResilientMarketCollector.__new__(ResilientMarketCollector)
    collector.providers = [binance, kraken]
    collector.disabled = set()
    collector.last_provider = None

    assert collector.klines("BTCUSDT", "1h") == "candles"
    assert collector.last_provider == "Kraken"
    assert "Binance" in collector.disabled

    assert collector.klines("ETHUSDT", "1h") == "candles"
    assert binance.calls == 1
    assert kraken.calls == 2
