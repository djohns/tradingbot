from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]


def load_config(path: str | None = None) -> dict[str, Any]:
    """Load YAML configuration and normalize paths relative to the repository."""
    load_dotenv(ROOT / ".env")
    config_path = Path(path or os.getenv("BOT_CONFIG", ROOT / "backend/config.yaml"))
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    for section, key in (
        ("storage", "sqlite_path"),
        ("storage", "output_dir"),
        ("dashboard", "public_data_dir"),
    ):
        raw = Path(config[section][key])
        config[section][key] = str(raw if raw.is_absolute() else ROOT / raw)

    numeric_overrides = {
        "BINANCE_MAKER_FEE_RATE": ("execution", "maker_fee_rate"),
        "BINANCE_TAKER_FEE_RATE": ("execution", "taker_fee_rate"),
        "BINANCE_BNB_FEE_DISCOUNT_PCT": ("execution", "bnb_fee_discount_pct"),
    }
    for environment, (section, key) in numeric_overrides.items():
        value = os.getenv(environment, "").strip()
        if value:
            config[section][key] = float(value)
    mode = os.getenv("BOT_STRATEGY_MODE", "").strip().lower()
    if mode:
        if mode not in {"shadow", "live"}:
            raise ValueError("BOT_STRATEGY_MODE must be shadow or live")
        config["strategy_v2"]["mode"] = mode
    return config


def secret(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None
