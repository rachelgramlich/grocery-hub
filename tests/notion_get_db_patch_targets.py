"""UI modules whose namespace binds ``get_db`` — patch all of them in mocked Notion tests.

Pytest collection imports test modules before the autouse ``_notion_test_doubles`` fixture
runs. Any test that imports a UI view at module level therefore freezes the real ``get_db``
in that view's namespace until monkeypatch replaces ``<module>.get_db`` for every binding
module listed here.

When adding ``from src.grocery_wizard.ui.db_access import get_db`` to a UI module, append
its dotted path to ``UI_GET_DB_PATCH_TARGETS``. ``test_get_db_patch_targets.py`` enforces that.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from tests.repo_paths import REPO_ROOT

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

# ``notion_cache`` imports ``get_db`` only for ``get_db.clear()``; keep the real ``@st.cache_resource``.
GET_DB_PATCH_EXEMPT: frozenset[str] = frozenset({"src.grocery_wizard.ui.notion_cache"})

UI_GET_DB_PATCH_TARGETS: tuple[str, ...] = (
    "src.grocery_wizard.ui.db_access",
    "src.grocery_wizard.ui.app",
    "src.grocery_wizard.ui.nyt_sync",
    "src.grocery_wizard.ui.views.add_recipe",
    "src.grocery_wizard.ui.views.browse_recipes",
    "src.grocery_wizard.ui.views.recipe_maintenance",
    "src.grocery_wizard.ui.views.weekly_plan.flow",
    "src.grocery_wizard.ui.views.weekly_plan.plan_entry",
    "src.grocery_wizard.ui.views.weekly_plan.grocery_list_ui",
    "src.grocery_wizard.ui.views.weekly_plan.state",
)

_GET_DB_IMPORT_RE = re.compile(
    r"^from src\.grocery_wizard\.ui\.db_access import get_db\s*$",
    re.MULTILINE,
)


def patch_ui_get_db(
    monkeypatch: pytest.MonkeyPatch,
    replacement: Callable[..., Any],
    *,
    raising: bool = False,
) -> None:
    for module_path in UI_GET_DB_PATCH_TARGETS:
        monkeypatch.setattr(f"{module_path}.get_db", replacement, raising=raising)


def ui_modules_binding_get_db_at_import() -> frozenset[str]:
    """Dotted module paths under ``src.grocery_wizard.ui`` that import ``get_db`` at top level."""
    ui_root = REPO_ROOT / "src" / "grocery_wizard" / "ui"
    found: set[str] = set()
    for path in ui_root.rglob("*.py"):
        if _GET_DB_IMPORT_RE.search(path.read_text(encoding="utf-8")):
            rel = path.relative_to(REPO_ROOT / "src")
            found.add("src." + ".".join(rel.with_suffix("").parts))
    return frozenset(found)


def ui_modules_requiring_get_db_patch() -> frozenset[str]:
    return ui_modules_binding_get_db_at_import() - GET_DB_PATCH_EXEMPT
