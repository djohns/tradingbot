import pandas as pd
import pytest

from backend.collectors.kraken import KrakenCollector


class FakeKraken(KrakenCollector):
    def get_json(self, url, *, params=None, headers=None):
        if url.endswith("/OHLC"):
            rows = [
                [1_700_000_000 + index * 3600, "100", "103", "99", "102", "101", "2.5", 30]
                for index in range(220)
            ]
            return {"error": [], "result": {"XBTUSDT": rows, "last": 1_700_800_000}}
        if url.endswith("/Ticker"):
            return {
                "error": [],
                "result": {
                    "XBTUSDT": {
                        "c": ["105", "0.1"],
                        "o": "100",
                        "v": ["10", "20"],
                        "p": ["102", "103"],
                        "h": ["106", "108"],
                        "l": ["98", "97"],
                    }
                },
            }
        return {
            "error": [],
            "result": {
                "XBTUSDT": {
                    "bids": [["104", "2", 1], ["103", "1", 1]],
                    "asks": [["106", "1", 1], ["107", "3", 1]],
                }
            },
        }


def test_kraken_adapter_matches_market_contract():
    collector = FakeKraken(max_retries=1)
    frame = collector.klines("BTCUSDT", "1h", 210)
    assert len(frame) == 210
    assert pd.api.types.is_datetime64_any_dtype(frame["open_time"])
    assert {"open", "high", "low", "close", "volume", "close_time"} <= set(frame.columns)

    ticker = collector.ticker_24h("BTCUSDT")
    assert ticker["price"] == 105
    assert ticker["change_24h_pct"] == pytest.approx(5)

    book = collector.order_book("BTCUSDT")
    assert book["largest_bid_wall"] == (104.0, 2.0)
    assert book["largest_ask_wall"] == (107.0, 3.0)
