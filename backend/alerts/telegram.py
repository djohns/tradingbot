from __future__ import annotations

from typing import Any

import requests


def format_signal(signal: dict[str, Any]) -> str:
    icon = "🟢" if signal["tipo"] == "long" else "🔴"
    reasons = "\n".join(f"• {reason}" for reason in signal["razones"])
    return (
        f"{icon} Señal {signal['tipo'].upper()} — {signal['activo']} {signal['timeframe']}\n"
        f"Confianza: {signal['confianza']}/100\n"
        f"Entrada: {signal['entrada_sugerida']:,.4f}\n"
        f"SL: {signal['stop_loss']:,.4f} | TP1: {signal['take_profit_1']:,.4f} | "
        f"TP2: {signal['take_profit_2']:,.4f}\n"
        f"R:R mínimo: {signal['ratio_riesgo_beneficio']:.2f}\n\n"
        f"{reasons}\n\n⚠️ {signal['disclaimer']}"
    )


def send_signal(token: str, chat_id: str, signal: dict[str, Any], timeout: float = 15) -> None:
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": format_signal(signal), "disable_web_page_preview": True},
        timeout=timeout,
    )
    response.raise_for_status()

