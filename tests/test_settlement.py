import pandas as pd

from backend.main import settle_open_signals
from backend.storage import Storage


def test_ambiguous_candle_settles_conservatively_as_loss(tmp_path):
    storage = Storage(str(tmp_path / "test.db"))
    signal = {
        "id": "signal-1",
        "activo": "BTCUSDT",
        "timeframe": "1h",
        "tipo": "long",
        "confianza": 80,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "estado": "abierta",
        "resultado_r": None,
        "stop_loss": 95,
        "take_profit_1": 105,
        "ratio_riesgo_beneficio": 1.5,
    }
    assert storage.save_signal(signal)
    frame = pd.DataFrame(
        [
            {
                "close_time": pd.Timestamp("2026-01-01T01:00:00Z"),
                "low": 94,
                "high": 106,
            }
        ]
    )
    settle_open_signals(storage, "BTCUSDT", frame)
    settled = storage.list_signals()[0]
    assert settled["estado"] == "perdedora"
    assert settled["resultado_r"] == -1.0

