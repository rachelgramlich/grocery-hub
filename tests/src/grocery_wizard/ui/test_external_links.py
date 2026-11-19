"""Regression: app hyperlinks open in a new browser tab."""

from __future__ import annotations

from src.grocery_wizard.ui.theme import EXTERNAL_LINKS_JS, app_external_links_script


def test_external_links_script_sets_blank_target() -> None:
    script = app_external_links_script()
    assert "_blank" in script
    assert "noopener noreferrer" in script
    assert "__gwExternalLinksInstalled" in script


def test_external_links_js_file_exists() -> None:
    assert EXTERNAL_LINKS_JS.is_file()
    text = EXTERNAL_LINKS_JS.read_text(encoding="utf-8")
    assert 'setAttribute("target", "_blank")' in text
