"""Resolve Notion recipe column names that vary by database schema."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from src.grocery_hub.integrations.notion import ColumnInfo, DatabaseSchema

__all__ = [
    "classification_rules_key",
    "dinner_lunch_category_column_name",
    "dinner_lunch_category_na_option",
    "diversity_planning_columns",
    "is_dinner_lunch_category_column",
    "is_dinner_lunch_category_na_only",
]

_DINNER_LUNCH_CATEGORY_KEYS = frozenset({"dinnercategory", "dinnerlunchcategory"})


def column_name_key(name: str) -> str:
    return re.sub(r"[\s_/]+", "", name.lower())


def is_dinner_lunch_category_column(name: str) -> bool:
    """True for **Dinner Category**, **Dinner/Lunch Category**, and close variants."""
    return column_name_key(name) in _DINNER_LUNCH_CATEGORY_KEYS


def classification_rules_key(column_name: str) -> str:
    if is_dinner_lunch_category_column(column_name):
        return "dinner category"
    return column_name.lower()


def dinner_lunch_category_column_name(
    columns: Iterable[ColumnInfo],
) -> str | None:
    for col in columns:
        if is_dinner_lunch_category_column(col.name):
            return col.name
    return None


def dinner_lunch_category_column_from_schema(schema: DatabaseSchema) -> str | None:
    return dinner_lunch_category_column_name(schema.filter_columns)


def dinner_lunch_category_na_option(options: Iterable[str]) -> str | None:
    """Notion option for not applicable (exact label from schema, usually ``N/A``)."""
    for opt in options:
        stripped = opt.strip()
        if stripped.upper() in {"N/A", "NA"}:
            return opt
    return None


def is_dinner_lunch_category_na_only(value: object, *, na_label: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, list):
        text = str(value).strip()
        return text.upper() in {"N/A", "NA"} or text == na_label
    items = {str(item).strip() for item in value if str(item).strip()}
    if len(items) != 1:
        return False
    only = next(iter(items))
    return only == na_label or only.upper() in {"N/A", "NA"}


def diversity_planning_columns(schema_columns: dict[str, ColumnInfo]) -> tuple[str, ...]:
    """Protein, dinner/lunch category (if present), and Cuisine — dinner and lunch variety."""
    names: list[str] = []
    if "Protein" in schema_columns:
        names.append("Protein")
    dinner_col = dinner_lunch_category_column_name(schema_columns.values())
    if dinner_col:
        names.append(dinner_col)
    if "Cuisine" in schema_columns:
        names.append("Cuisine")
    return tuple(names)
