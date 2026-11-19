"""Open app hyperlinks in a new browser tab (idempotent in the parent document)."""

from __future__ import annotations

import json

import streamlit as st

from src.grocery_wizard.ui.theme import EXTERNAL_LINKS_JS


def external_links_iframe_html() -> str:
    """HTML for a 1px iframe that installs the link patcher in the parent document.

    Streamlit does not execute ``<script>`` inside ``st.markdown``; the script is copied
    into a tag on ``window.parent.document`` so it runs in the app frame (same pattern
    as dropdown dismiss).
    """
    code = json.dumps(EXTERNAL_LINKS_JS.read_text(encoding="utf-8"))
    return f"""
    <script>
    (function () {{
      var parentDoc = window.parent.document;
      var script = parentDoc.createElement("script");
      script.textContent = {code};
      parentDoc.head.appendChild(script);
      script.remove();
    }})();
    </script>
    """


def install_external_links() -> None:
    """Install parent-document hyperlink handlers (idempotent in the browser)."""
    st.iframe(external_links_iframe_html(), height=1)
