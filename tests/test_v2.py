from copy import deepcopy

from backend.analysis.indicators import add_indicators
from backend.execution import estimate_round_trip_cost
from backend.signals.engine_v2 import evaluate
from tests.test_indicators import make_frame


RISK = {
    "capital_usd": 10_000,
    "risk_per_trade_pct": 0.5,
    "minimum_risk_per_trade_pct": 0.25,
    "volatility_target_annual_pct": 40,
    "max_notional_pct": 100,
}
EXECUTION = {
    "maker_fee_rate": 0.0002,
    "taker_fee_rate": 0.0005,
    "entry_order_type": "taker",
    "exit_order_type": "taker",
    "bnb_fee_discount_pct": 0,
    "spread_bps": 2,
    "slippage_bps": 3,
    "fallback_funding_rate": 0.0001,
    "fallback_funding_interval_hours": 8,
}
STRATEGY = {
    "mode": "shadow",
    "cost_gate_multiple": 3,
    "regime": {
        "trend_adx_min": 22,
        "trend_efficiency_min": 0.3,
        "range_adx_max": 18,
        "range_efficiency_max": 0.25,
    },
    "trend": {
        "timeframes": ["4h"],
        "breakout_period": 20,
        "relative_volume_min": 1.1,
        "initial_stop_atr": 2.5,
        "trailing_atr": 3,
        "expected_move_r": 3,
        "expected_holding_hours": 72,
        "no_followthrough_bars": 6,
        "max_holding_bars": 60,
    },
    "range": {
        "enabled": True,
        "timeframes": ["1h"],
        "zscore_entry": 2,
        "stop_atr": 1.5,
        "expected_holding_hours": 12,
        "max_holding_bars": 12,
    },
    "relative_strength": {"max_rank": 3},
}
CONTEXT = {"score": 0, "label": "neutral", "missing_sources": []}


def _range_frames():
    data = add_indicators(make_frame(300))
    index = data.index[-1]
    data.loc[index, "adx"] = 10
    data.loc[index, "efficiency_ratio"] = 0.1
    data.loc[index, "bb_zscore"] = -2.2
    data.loc[index, "bb_lower"] = data.loc[index, "close"] - 0.5
    data.loc[index, "low"] = data.loc[index, "bb_lower"] - 0.5
    data.loc[index, "open"] = data.loc[index, "bb_lower"] - 0.1
    data.loc[index, "bb_middle"] = data.loc[index, "close"] + 3
    return {"1h": data}


def _trend_frames():
    data = add_indicators(make_frame(300))
    index = data.index[-1]
    data.loc[index, "close"] = data.loc[index, "donchian_high_20"] + 2
    data.loc[index, "high"] = data.loc[index, "close"] + 1
    data.loc[index, "open"] = data.loc[index, "close"] - 1
    data.loc[index, "adx"] = 30
    data.loc[index, "efficiency_ratio"] = 0.5
    data.loc[index, "ema_200_slope_20"] = 0.02
    data.loc[index, "relative_volume"] = 1.5
    daily = add_indicators(make_frame(300))
    return {"4h": data, "1d": daily}


def test_range_model_requires_lateral_regime_and_rejection():
    frames = _range_frames()
    signal, diagnostics = evaluate(
        "BTCUSDT", "1h", frames, CONTEXT, RISK,
        strategy_config=STRATEGY, execution_config=EXECUTION,
        derivatives={"funding_rate": 0, "funding_interval_hours": 8},
    )
    assert signal is not None
    assert signal["estrategia"] == "reversion_lateral"
    assert signal["exit_model"] == "fixed_target"
    assert signal["modo"] == "shadow"
    assert diagnostics["regime"]["name"] == "lateral"


def test_transition_regime_is_a_hard_veto():
    frames = _range_frames()
    frames["1h"].loc[frames["1h"].index[-1], "adx"] = 20
    signal, diagnostics = evaluate(
        "BTCUSDT", "1h", frames, CONTEXT, RISK,
        strategy_config=STRATEGY, execution_config=EXECUTION,
    )
    assert signal is None
    assert diagnostics["status"] == "regime_blocked"


def test_cost_gate_rejects_an_economically_small_setup():
    expensive = deepcopy(EXECUTION)
    expensive.update({"taker_fee_rate": 0.01, "spread_bps": 100, "slippage_bps": 100})
    signal, diagnostics = evaluate(
        "BTCUSDT", "1h", _range_frames(), CONTEXT, RISK,
        strategy_config=STRATEGY, execution_config=expensive,
        derivatives={"funding_rate": 0.001, "funding_interval_hours": 8},
    )
    assert signal is None
    assert diagnostics["status"] == "cost_blocked"


def test_funding_credit_cannot_make_round_trip_cost_negative():
    costs = estimate_round_trip_cost(
        entry=100,
        target=110,
        side="short",
        config=EXECUTION,
        funding_rate=0.1,
        holding_hours=24,
        funding_interval_hours=8,
    )
    assert costs["total_cost_bps"] > 0


def test_falling_open_interest_vetoes_a_trend_breakout():
    signal, diagnostics = evaluate(
        "ETHUSDT", "4h", _trend_frames(), CONTEXT, RISK,
        strategy_config=STRATEGY, execution_config=EXECUTION,
        derivatives={
            "funding_rate": 0,
            "funding_interval_hours": 8,
            "open_interest_change_pct": -5,
            "source": "binance_usdm_futures",
        },
        relative_strength={"rank": 1, "universe": 4},
        btc_regime="tendencial_alcista",
    )
    assert signal is None
    assert diagnostics["status"] == "open_interest_blocked"
