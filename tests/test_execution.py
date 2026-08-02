from datetime import datetime, timezone

from backend.execution import (
    calculate_trade_result,
    estimated_funding_events,
    execution_price,
)
from tests.test_settlement import EXECUTION


def signal(side="long"):
    return {
        "tipo": side,
        "entrada_sugerida": 100,
        "stop_loss": 95 if side == "long" else 105,
        "tamano_posicion_sugerido": 20,
        "capital_en_riesgo": 100,
        "abierta_en": "2026-01-01T00:00:00+00:00",
        "spread_bps_aplicado": 2,
        "slippage_bps_aplicado": 3,
        "tipo_entrada": "taker",
    }


def test_adverse_execution_prices_include_spread_and_slippage():
    assert execution_price(100, "long", "entry", 2, 3) > 100
    assert execution_price(100, "long", "exit", 2, 3) < 100
    assert execution_price(100, "short", "entry", 2, 3) < 100
    assert execution_price(100, "short", "exit", 2, 3) > 100


def test_funding_can_be_a_credit_for_short_positions():
    events = [{"time": "2026-01-01T08:00:00+00:00", "rate": 0.0001}]
    long_result = calculate_trade_result(
        signal("long"), [{"fraction": 1, "price": 105, "reason": "tp"}], EXECUTION, events
    )
    short_result = calculate_trade_result(
        signal("short"), [{"fraction": 1, "price": 95, "reason": "tp"}], EXECUTION, events
    )
    assert long_result["funding_usd"] > 0
    assert short_result["funding_usd"] < 0
    assert long_result["resultado_r"] < long_result["resultado_bruto_r"]


def test_estimated_funding_only_counts_crossed_boundaries():
    start = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, 17, tzinfo=timezone.utc)
    events = estimated_funding_events(start, end, 0.0001, 8)
    assert [item["time"][11:16] for item in events] == ["08:00", "16:00"]
