import json

import pytest

from backend.main import (
    MarketDataUnavailable,
    read_previous_backtests,
    read_previous_signals,
    require_market_data,
)


def test_empty_market_is_rejected_before_publication():
    with pytest.raises(MarketDataUnavailable, match="preserving"):
        require_market_data({"assets": {}})


def test_nonempty_market_can_be_published():
    require_market_data({"assets": {"BTCUSDT": {}}})


def test_previous_signal_history_is_restored(tmp_path):
    payload = {"signals": [{"id": "kept"}]}
    (tmp_path / "signals.json").write_text(json.dumps(payload), encoding="utf-8")
    assert read_previous_signals(tmp_path) == payload["signals"]


def test_previous_backtests_survive_regular_hourly_runs(tmp_path):
    payload = {"backtests": {"BTCUSDT": {"total_trades": 12}}}
    (tmp_path / "performance.json").write_text(json.dumps(payload), encoding="utf-8")
    assert read_previous_backtests(tmp_path) == payload["backtests"]
