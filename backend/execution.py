from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


def as_utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def effective_fee_rate(config: dict[str, Any], order_type: str) -> float:
    rate = float(config[f"{order_type}_fee_rate"])
    discount = float(config.get("bnb_fee_discount_pct", 0.0)) / 100
    return rate * (1 - discount)


def execution_price(
    reference_price: float,
    side: str,
    action: str,
    spread_bps: float,
    slippage_bps: float,
) -> float:
    """Return an adverse fill price, including half-spread and slippage."""
    impact = (spread_bps / 2 + slippage_bps) / 10_000
    is_buy = (side == "long" and action == "entry") or (
        side == "short" and action == "exit"
    )
    return reference_price * (1 + impact if is_buy else 1 - impact)


def prepare_live_execution(
    signal: dict[str, Any],
    *,
    market_price: float,
    order_book: dict[str, Any] | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Attach an auditable market fill to a newly published signal."""
    published_at = as_utc(signal["timestamp"])
    book = order_book or {}
    bid = float(book.get("best_bid") or 0)
    ask = float(book.get("best_ask") or 0)
    observed_spread = (
        (ask - bid) / ((ask + bid) / 2) * 10_000 if ask > bid > 0 else 0.0
    )
    spread_bps = max(observed_spread, float(config["spread_bps"]))
    slippage_bps = float(config["slippage_bps"])
    entry_fill = execution_price(
        market_price, signal["tipo"], "entry", spread_bps, slippage_bps
    )
    signal.update(
        {
            "estado": "abierta",
            "publicada_en": published_at.isoformat(),
            "abierta_en": published_at.isoformat(),
            "precio_mercado_publicacion": round(market_price, 8),
            "entrada_ejecutada": round(entry_fill, 8),
            "tipo_entrada": config.get("entry_order_type", "taker"),
            "spread_bps_aplicado": round(spread_bps, 4),
            "slippage_bps_aplicado": round(slippage_bps, 4),
            "modelo_ejecucion": config.get("market", "binance_usdm_futures"),
            "comision_maker": float(config["maker_fee_rate"]),
            "comision_taker": float(config["taker_fee_rate"]),
            "descuento_bnb_pct": float(config.get("bnb_fee_discount_pct", 0.0)),
        }
    )
    return signal


def estimated_funding_events(
    opened_at: datetime,
    closed_at: datetime,
    rate: float,
    interval_hours: int,
) -> list[dict[str, Any]]:
    """Create transparent fallback funding events on UTC interval boundaries."""
    opened_at, closed_at = as_utc(opened_at), as_utc(closed_at)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    interval = timedelta(hours=interval_hours)
    elapsed = opened_at - epoch
    next_boundary = epoch + interval * (elapsed // interval + 1)
    events = []
    while next_boundary <= closed_at:
        events.append(
            {
                "time": next_boundary.isoformat(),
                "rate": float(rate),
                "source": "configured_estimate",
            }
        )
        next_boundary += interval
    return events


def calculate_trade_result(
    signal: dict[str, Any],
    exit_legs: list[dict[str, Any]],
    config: dict[str, Any],
    funding_events: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Calculate gross and net PnL in USD and R for a futures position."""
    side = signal["tipo"]
    quantity = float(signal["tamano_posicion_sugerido"])
    reference_entry = float(signal["entrada_sugerida"])
    entry_fill = float(
        signal.get("entrada_ejecutada")
        or execution_price(
            reference_entry,
            side,
            "entry",
            float(signal.get("spread_bps_aplicado", config["spread_bps"])),
            float(signal.get("slippage_bps_aplicado", config["slippage_bps"])),
        )
    )
    risk_usd = float(signal["capital_en_riesgo"])
    spread_bps = float(signal.get("spread_bps_aplicado", config["spread_bps"]))
    slippage_bps = float(signal.get("slippage_bps_aplicado", config["slippage_bps"]))
    entry_order_type = str(signal.get("tipo_entrada", config["entry_order_type"]))
    exit_order_type = str(config["exit_order_type"])

    entry_fee = quantity * entry_fill * effective_fee_rate(config, entry_order_type)
    gross_pnl = 0.0
    execution_pnl = 0.0
    exit_fees = 0.0
    exit_fills: list[dict[str, Any]] = []
    for leg in exit_legs:
        fraction = float(leg["fraction"])
        reference_exit = float(leg["price"])
        fill = execution_price(
            reference_exit, side, "exit", spread_bps, slippage_bps
        )
        leg_quantity = quantity * fraction
        direction = 1 if side == "long" else -1
        gross_pnl += direction * (reference_exit - reference_entry) * leg_quantity
        execution_pnl += direction * (fill - entry_fill) * leg_quantity
        exit_fees += leg_quantity * fill * effective_fee_rate(config, exit_order_type)
        exit_fills.append(
            {
                **leg,
                "reference_price": round(reference_exit, 8),
                "executed_price": round(fill, 8),
                "quantity": round(leg_quantity, 8),
            }
        )

    funding_usd = 0.0
    normalized_events = []
    tp1_at = as_utc(signal["tp1_alcanzado_en"]) if signal.get("tp1_alcanzado_en") else None
    tp1_fraction = float(config.get("tp1_close_fraction", 0.5))
    for event in funding_events:
        event_time = as_utc(event["time"])
        open_fraction = 1.0 - tp1_fraction if tp1_at and event_time > tp1_at else 1.0
        rate = float(event["rate"])
        funding_price = float(event.get("price") or reference_entry)
        notional = quantity * open_fraction * funding_price
        # Positive funding is paid by longs and received by shorts.
        payment = notional * rate * (1 if side == "long" else -1)
        funding_usd += payment
        normalized_events.append(
            {
                "time": event_time.isoformat(),
                "rate": rate,
                "mark_price": funding_price,
                "payment_usd": round(payment, 6),
                "source": event.get("source", "binance"),
            }
        )

    commission_usd = entry_fee + exit_fees
    execution_impact_usd = max(0.0, gross_pnl - execution_pnl)
    total_cost_usd = commission_usd + execution_impact_usd + funding_usd
    net_pnl = execution_pnl - commission_usd - funding_usd
    return {
        "entrada_ejecutada": round(entry_fill, 8),
        "salidas": exit_fills,
        "pnl_bruto_usd": round(gross_pnl, 4),
        "pnl_ejecucion_usd": round(execution_pnl, 4),
        "comisiones_usd": round(commission_usd, 4),
        "impacto_spread_slippage_usd": round(execution_impact_usd, 4),
        "funding_usd": round(funding_usd, 4),
        "costes_totales_usd": round(total_cost_usd, 4),
        "pnl_neto_usd": round(net_pnl, 4),
        "resultado_bruto_r": round(gross_pnl / risk_usd, 4) if risk_usd else 0.0,
        "resultado_r": round(net_pnl / risk_usd, 4) if risk_usd else 0.0,
        "funding_eventos": normalized_events,
        "calidad_costes": (
            "binance_funding_modelled_execution"
            if normalized_events
            and all(item["source"] == "binance_usdm_futures" for item in normalized_events)
            else "estimated_funding_modelled_execution"
        ),
    }
