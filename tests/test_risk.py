from backend.signals.risk import build_trade_plan


def test_long_plan_respects_risk_budget_and_rr():
    plan = build_trade_plan(
        side="long",
        entry=100,
        atr=2,
        swing=96,
        capital=10_000,
        risk_pct=1,
        minimum_rr=1.5,
        atr_multiplier=1.5,
    )
    assert plan is not None
    assert plan.stop_loss < plan.entry < plan.take_profit_1
    assert plan.capital_at_risk == 100
    assert plan.risk_reward >= 1.5


def test_short_plan_levels_are_ordered():
    plan = build_trade_plan(
        side="short",
        entry=100,
        atr=2,
        swing=104,
        capital=10_000,
        risk_pct=1,
        minimum_rr=2,
        atr_multiplier=1.5,
    )
    assert plan is not None
    assert plan.take_profit_1 < plan.entry < plan.stop_loss

