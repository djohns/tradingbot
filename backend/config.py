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
    return config


def secret(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None

