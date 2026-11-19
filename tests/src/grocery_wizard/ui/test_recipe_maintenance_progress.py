"""Unit tests for Recipe maintenance NYT progress helpers."""

from __future__ import annotations

from src.grocery_wizard.integrations.nyt_cooking import NytSyncProgressUpdate
from src.grocery_wizard.ui.views.recipe_maintenance import _nyt_sync_progress_log_line


def test_nyt_sync_progress_log_line_returns_message() -> None:
    update = NytSyncProgressUpdate(message="Update: Pasta", processed=3, total=10)
    assert _nyt_sync_progress_log_line(update) == "Update: Pasta"


def test_nyt_sync_progress_log_line_omits_blank_message() -> None:
    assert _nyt_sync_progress_log_line(NytSyncProgressUpdate(message="", processed=1)) is None
    assert _nyt_sync_progress_log_line(NytSyncProgressUpdate(message="   ", processed=1)) is None
