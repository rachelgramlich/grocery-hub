"""Regression: app hyperlinks open in a new browser tab."""

from __future__ import annotations

from ui_source import APP_PATH

from src.grocery_wizard.ui.external_links import external_links_iframe_html
from src.grocery_wizard.ui.theme import EXTERNAL_LINKS_JS


def _js() -> str:
    return EXTERNAL_LINKS_JS.read_text(encoding="utf-8")


def test_external_links_script_sets_blank_target() -> None:
    js = _js()
    assert "_blank" in js
    assert "noopener noreferrer" in js
    assert "__gwExternalLinksInstalled" in js
    assert 'setAttribute("target", "_blank")' in js


def test_external_links_js_file_exists() -> None:
    assert EXTERNAL_LINKS_JS.is_file()


def test_iframe_installs_script_into_parent_document() -> None:
    html = external_links_iframe_html()
    assert "window.parent.document" in html
    assert "__gwExternalLinksInstalled" in html


def test_app_installs_external_links() -> None:
    assert "install_external_links()" in APP_PATH.read_text(encoding="utf-8")
