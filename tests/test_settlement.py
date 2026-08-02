import pandas as pd

from backend.main import settle_open_signals
from backend.storage import Storage


EXECUTION = {
    "market": "binance_usdm_futures",
    "maker_fee_rate": 0.0002,
    "taker_fee_rate": 0.0005,
    "entry_order_type": "taker",
    "exit_order_type": "taker",
    "bnb_fee_discount_pct": 0,
    "spread_bps": 2,
    "slippage_bps": 3,
    "fallback_funding_rate": 0.0001,
    "fallback_funding_interval_hours": 8,
    "max_bars_open": 24,
    "tp1_close_fraction": 0.5,
    "move_stop_to_break_even": True,
}
RISK = {"capital_usd": 10_000, "risk_per_trade_pct": 1}


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
            "entrada_sugerida": 100,
            "tamano_posicion_sugerido": 20,
            "capital_en_riesgo": 100,
            "stop_loss": 95,
            "take_profit_1": 105,
            "take_profit_2": 110,
        "ratio_riesgo_beneficio": 1.5,
    }
    assert storage.save_signal(signal)
    frame = pd.DataFrame(
        [
            {
                "open_time": pd.Timestamp("2026-01-01T00:00:00Z"),
                "close_time": pd.Timestamp("2026-01-01T01:00:00Z"),
                "low": 94,
                "high": 106,
            }
        ]
    )
    settle_open_signals(storage, "BTCUSDT", frame, EXECUTION, RISK)
    settled = storage.list_signals()[0]
    assert settled["estado"] == "perdedora"
    assert settled["resultado_r"] < -1.0
    assert settled["comisiones_usd"] > 0
    assert settled["motivo_salida"] == "stop_loss"


def test_candle_started_before_publication_is_ignored(tmp_path):
    storage = Storage(str(tmp_path / "test.db"))
    item = {
        "id": "signal-pre-publication",
        "activo": "BTCUSDT",
        "timeframe": "1h",
        "tipo": "long",
        "confianza": 70,
        "timestamp": "2026-01-01T00:17:00+00:00",
        "estado": "abierta",
        "resultado_r": None,
        "entrada_sugerida": 100,
        "tamano_posicion_sugerido": 20,
        "capital_en_riesgo": 100,
        "stop_loss": 95,
        "take_profit_1": 107.5,
        "take_profit_2": 110,
        "ratio_riesgo_beneficio": 1.5,
    }
    storage.save_signal(item)
    frame = pd.DataFrame([{
        "open_time": pd.Timestamp("2026-01-01T00:00:00Z"),
        "close_time": pd.Timestamp("2026-01-01T01:00:00Z"),
        "low": 94,
        "high": 101,
        "close": 100,
    }])
    settle_open_signals(storage, "BTCUSDT", frame, EXECUTION, RISK)
    assert storage.list_signals()[0]["estado"] == "abierta"


def test_tp1_then_break_even_uses_two_real_exit_legs(tmp_path):
    storage = Storage(str(tmp_path / "test.db"))
    item = {
        "id": "signal-partial",
        "activo": "BTCUSDT",
        "timeframe": "1h",
        "tipo": "long",
        "confianza": 70,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "estado": "abierta",
        "resultado_r": None,
        "entrada_sugerida": 100,
        "tamano_posicion_sugerido": 20,
        "capital_en_riesgo": 100,
        "stop_loss": 95,
        "take_profit_1": 107.5,
        "take_profit_2": 110,
        "ratio_riesgo_beneficio": 1.5,
    }
    storage.save_signal(item)
    frame = pd.DataFrame([
        {
            "open_time": pd.Timestamp("2026-01-01T00:00:00Z"),
            "close_time": pd.Timestamp("2026-01-01T01:00:00Z"),
            "low": 99,
            "high": 108,
            "close": 107,
        },
        {
            "open_time": pd.Timestamp("2026-01-01T01:00:00Z"),
            "close_time": pd.Timestamp("2026-01-01T02:00:00Z"),
            "low": 99,
            "high": 108,
            "close": 100,
        },
    ])
    settle_open_signals(storage, "BTCUSDT", frame, EXECUTION, RISK)
    settled = storage.list_signals()[0]
    assert settled["estado"] == "ganadora"
    assert settled["motivo_salida"] == "break_even"
    assert len(settled["salidas"]) == 2
    assert 0 < settled["resultado_r"] < 0.75
