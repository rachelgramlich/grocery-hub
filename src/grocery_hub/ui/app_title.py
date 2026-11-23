"""Decorative app title (word art) for the Streamlit shell."""

from __future__ import annotations

import streamlit as st

_APP_TITLE_HTML = """
<div class="gw-app-title-block">
  <h1 class="gw-app-title">
    <span class="gw-app-title__spark gw-app-title__spark--left" aria-hidden="true">✦</span>
    <span class="gw-app-title__grocery">Grocery</span>
    <span class="gw-app-title__hub">Hub</span>
    <span class="gw-app-title__spark gw-app-title__spark--right" aria-hidden="true">✦</span>
  </h1>
</div>
"""


def render_app_title() -> None:
    """Render the Grocery Hub word-art title instead of plain ``st.title``."""
    st.markdown(_APP_TITLE_HTML, unsafe_allow_html=True)
