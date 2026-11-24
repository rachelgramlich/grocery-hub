"""Config loading from repo-root ``secrets.toml``."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from src.grocery_hub.config import load_auth_gate_settings, load_config

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_load_config_reads_flat_secrets_toml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text(
        """\
NOTION_API_KEY = "from-secrets"
NOTION_RECIPE_DATABASE_ID = "00000000-0000-4000-8000-000000000001"
NOTION_PANTRY_DATABASE_ID = "00000000-0000-4000-8000-000000000002"
NOTION_RECURRING_WEEKLY_DATABASE_ID = "00000000-0000-4000-8000-000000000003"
NOTION_WEEKLY_MEAL_PLANS_DATABASE_ID = "00000000-0000-4000-8000-000000000004"
NOTION_DEBUG_LOGS_DATABASE_ID = "00000000-0000-4000-8000-000000000005"
GITHUB_FEEDBACK_TOKEN = "gh-test"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("NOTION_API_KEY", "from-env")
    for key in list(os.environ):
        if key.startswith("GITHUB_FEEDBACK_") or key in {
            "REQUIRE_AUTH",
            "AUTH_EMAIL_ALLOWLIST",
            "DEFAULT_MEALS",
            "DEV_UI",
        }:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        "src.grocery_hub.config._apply_streamlit_runtime_secrets_to_environ",
        lambda: None,
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.grocery_hub.config._secrets_toml_path",
        lambda: secrets_path,
    )
    for key in list(os.environ):
        if key.startswith("NOTION_") and key != "NOTION_API_KEY":
            monkeypatch.delenv(key, raising=False)

    cfg = load_config()
    assert cfg.notion_api_key == "from-env"
    assert cfg.github_feedback_token == "gh-test"


def test_load_auth_gate_settings_without_notion_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text(
        """\
REQUIRE_AUTH = true
AUTH_EMAIL_ALLOWLIST = "a@example.com"
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.grocery_hub.config._secrets_toml_path",
        lambda: secrets_path,
    )
    for key in list(os.environ):
        if key.startswith(("NOTION_", "GITHUB_FEEDBACK_")):
            monkeypatch.delenv(key, raising=False)
    for key in ("REQUIRE_AUTH", "AUTH_EMAIL_ALLOWLIST"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        "src.grocery_hub.config._apply_streamlit_runtime_secrets_to_environ",
        lambda: None,
    )

    gate = load_auth_gate_settings()
    assert gate.require_auth is True
    assert gate.auth_email_allowlist == "a@example.com"

    for key in ("REQUIRE_AUTH", "AUTH_EMAIL_ALLOWLIST"):
        monkeypatch.delenv(key, raising=False)


def test_normalize_notion_database_id_repairs_wrong_dash_grouping() -> None:
    from src.grocery_hub.config import normalize_notion_database_id

    # Common copy-paste mistake (16-char last segment) → standard UUID
    assert (
        normalize_notion_database_id("a061062d-64d6-4f42-a3b48bbb9cdc64ea")
        == "a061062d-64d6-4f42-a3b4-8bbb9cdc64ea"
    )
