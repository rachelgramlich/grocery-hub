"""Compatibility shim — use ``integrations.notion.views``."""

from __future__ import annotations

from src.grocery_hub.integrations import _reexport_shim
from src.grocery_hub.integrations.notion import views as _target

_reexport_shim.reexport_module(_target, globals())
