"""Guard: every UI module that binds ``get_db`` at import is in ``UI_GET_DB_PATCH_TARGETS``."""

from __future__ import annotations

from tests.notion_get_db_patch_targets import (
    UI_GET_DB_PATCH_TARGETS,
    ui_modules_requiring_get_db_patch,
)


def test_ui_get_db_patch_targets_cover_import_bindings() -> None:
    bound = ui_modules_requiring_get_db_patch()
    patched = set(UI_GET_DB_PATCH_TARGETS)
    missing = sorted(bound - patched)
    assert not missing, (
        "Add these modules to UI_GET_DB_PATCH_TARGETS in tests/notion_get_db_patch_targets.py: "
        + ", ".join(missing)
    )
