import pytest

from backend.main import MarketDataUnavailable, require_market_data


def test_empty_market_is_rejected_before_publication():
    with pytest.raises(MarketDataUnavailable, match="preserving"):
        require_market_data({"assets": {}})


def test_nonempty_market_can_be_published():
    require_market_data({"assets": {"BTCUSDT": {}}})
