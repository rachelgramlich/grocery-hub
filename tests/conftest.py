"""Pytest configuration for grocery_hub tests."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from tests.notion_get_db_patch_targets import patch_ui_get_db
from tests.notion_test_env import (
    PYTEST_NOTION_API_KEY_PLACEHOLDER,
    prime_notion_env_for_pytest,
)
from tests.repo_paths import UI_TEST_HELPERS

if TYPE_CHECKING:
    from pathlib import Path

# Placeholders so CI and fresh clones run without Notion secrets.
# Shell exports and repo-root `.env` (via `prime_notion_env_for_pytest`) win over placeholders.
_PYTEST_NOTION_ENV: dict[str, str] = {
    "NOTION_API_KEY": PYTEST_NOTION_API_KEY_PLACEHOLDER,
    "NOTION_RECIPE_DATABASE_ID": "00000000-0000-4000-8000-000000000001",
    "NOTION_PANTRY_DATABASE_ID": "00000000-0000-4000-8000-000000000002",
    "NOTION_RECURRING_WEEKLY_DATABASE_ID": "00000000-0000-4000-8000-000000000003",
    "NOTION_WEEKLY_MEAL_PLANS_DATABASE_ID": "00000000-0000-4000-8000-000000000004",
    "NOTION_DEBUG_LOGS_DATABASE_ID": "00000000-0000-4000-8000-000000000005",
}


def pytest_configure(config: object) -> None:
    del config
    prime_notion_env_for_pytest()
    for key, value in _PYTEST_NOTION_ENV.items():
        os.environ.setdefault(key, value)


@pytest.fixture(autouse=True)
def _notion_test_doubles(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid live Notion API calls during tests (CI has no integration secrets)."""
    from src.grocery_hub.integrations.notion_table import clear_notion_database_metadata_cache
    from src.grocery_hub.ui.notion_cache import _recipe_store

    clear_notion_database_metadata_cache()
    _recipe_store.clear()
    import src.grocery_hub.shopping.pantry as pantry_mod
    import src.grocery_hub.shopping.recurring_weekly_items as recurring_mod
    from src.grocery_hub.integrations.notion import ColumnInfo, Recipe
    from src.grocery_hub.recipes.weeknight import DEFAULT_WEEKNIGHT_COLUMN

    def load_pantry(path: Path | None = None) -> set[str]:
        if path is not None:
            return pantry_mod._load_pantry_from_file(path)
        return set()

    monkeypatch.setattr(pantry_mod, "load_pantry", load_pantry)
    monkeypatch.setattr("src.grocery_hub.shopping.grocery_list.load_pantry", load_pantry)

    def load_recurring(path: Path | None = None) -> list[str]:
        if path is not None:
            return recurring_mod._load_recurring_from_file(path)
        return []

    monkeypatch.setattr(recurring_mod, "load_recurring_weekly_items", load_recurring)
    monkeypatch.setattr(
        "src.grocery_hub.ui.notion_cache._load_recurring_cached",
        lambda _generation: [],
    )

    fake_db = MagicMock()
    fake_db.schema.all_columns = {
        "Meal": ColumnInfo(name="Meal", type="select", options=["Dinner", "Lunch"]),
        DEFAULT_WEEKNIGHT_COLUMN: ColumnInfo(
            name=DEFAULT_WEEKNIGHT_COLUMN,
            type="checkbox",
            options=[],
        ),
    }
    fake_db.schema.filter_columns = [fake_db.schema.all_columns["Meal"]]
    fake_db.schema.checkbox_columns = [fake_db.schema.all_columns[DEFAULT_WEEKNIGHT_COLUMN]]
    fake_db.query_recipes.return_value = [
        Recipe(
            page_id="pytest-recipe-1",
            name="Test Soup",
            link=None,
            ingredients="1 cup flour",
            properties={"Meal": "Dinner", DEFAULT_WEEKNIGHT_COLUMN: True},
        ),
    ]

    def _fake_get_db() -> MagicMock:
        return fake_db

    patch_ui_get_db(monkeypatch, _fake_get_db)
    monkeypatch.setattr(
        "src.grocery_hub.ui.notion_cache._load_pantry_cached",
        lambda _generation, _household_db_id: [],
    )
    monkeypatch.setattr(
        "src.grocery_hub.ui.notion_cache._load_saved_plans_cached",
        lambda _weekly_plans_database_id, _generation, _recipes_db: [],
    )

    def _fake_persist_list_log(log, *, config=None, page_id=None):
        del log, config
        pid = page_id or "00000000-0000-4000-8000-000000000099"
        return pid, f"https://www.notion.so/{pid.replace('-', '')}"

    monkeypatch.setattr(
        "src.grocery_hub.integrations.notion_list_logs.persist_list_log_to_notion",
        _fake_persist_list_log,
    )


if str(UI_TEST_HELPERS) not in sys.path:
    sys.path.insert(0, str(UI_TEST_HELPERS))
