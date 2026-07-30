from backend.analysis.context import compose_context


def test_context_survives_missing_optional_sources():
    context = compose_context(
        fear_greed=None,
        global_market=None,
        fred=None,
        onchain=None,
        weights={
            "macro_weight": 0.45,
            "fear_greed_weight": 0.25,
            "btc_dominance_weight": 0.15,
            "onchain_weight": 0.15,
        },
    )
    assert context["label"] == "neutral"
    assert set(context["missing_sources"]) == {"fear_greed", "coingecko", "fred", "onchain"}

