"""Compatibility shim — use ``integrations.notion.data_source``."""

from __future__ import annotations

from src.grocery_hub.integrations import _reexport_shim
from src.grocery_hub.integrations.notion import data_source as _target

_reexport_shim.reexport_module(_target, globals())
