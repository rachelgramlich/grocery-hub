"""Dev-only UI affordances (weekly plan jumps, dev session mode)."""

from __future__ import annotations

from src.grocery_hub.config import load_config


def dev_ui_enabled() -> bool:
    """True when ``GROCERY_DEV_UI`` is set (local UAT / agent testing)."""
    return load_config().dev_ui_enabled
