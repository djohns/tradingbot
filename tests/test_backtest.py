from backend.backtesting.backtest import run_backtest
from tests.test_indicators import make_frame


def test_backtest_returns_complete_metric_contract():
    metrics = run_backtest(make_frame(500))
    assert {"total_trades", "win_rate", "expectancy", "max_drawdown_r", "by_regime"} <= metrics.keys()
    assert set(metrics["by_regime"]) == {"alcista", "bajista", "lateral"}

