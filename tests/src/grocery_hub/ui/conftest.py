"""Shared fixtures for Streamlit AppTest modules."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _auth_gate_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """AppTests must not inherit ``REQUIRE_AUTH`` from config tests."""
    monkeypatch.setenv("REQUIRE_AUTH", "false")
    monkeypatch.delenv("AUTH_EMAIL_ALLOWLIST", raising=False)
