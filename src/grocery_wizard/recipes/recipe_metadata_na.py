"""Not-applicable (N/A) option expectations for recipe metadata multi_selects."""

from __future__ import annotations

from src.grocery_wizard.integrations.notion import ColumnInfo, DatabaseSchema
from src.grocery_wizard.recipes.recipe_schema_columns import (
    dinner_lunch_category_na_option,
    is_dinner_lunch_category_column,
)

METADATA_NA_LABELS = frozenset({"N/A", "NA"})

# **N/A** is preferred; **None** is a legacy not-applicable label (still recognized).
PROTEIN_NOT_APPLICABLE_LABELS = frozenset({"N/A", "NA", "None"})
PROTEIN_LEGACY_NONE_LABEL = "None"


def protein_column_name(schema: DatabaseSchema) -> str | None:
    for col in schema.filter_columns:
        if col.name.lower() == "protein":
            return col.name
    return None


def protein_na_option(options: list[str]) -> str | None:
    """Preferred not-applicable protein tag (**N/A** when present)."""
    return dinner_lunch_category_na_option(options)


def protein_is_not_applicable_value(value: object, *, na_label: str) -> bool:
    if value is None:
        return False
    if isinstance(value, list):
        items = {str(item).strip() for item in value if str(item).strip()}
        if not items:
            return False
        return items <= PROTEIN_NOT_APPLICABLE_LABELS and (
            na_label in items or PROTEIN_LEGACY_NONE_LABEL in items
        )
    text = str(value).strip()
    return text in PROTEIN_NOT_APPLICABLE_LABELS


def column_expects_na_option(column: ColumnInfo) -> bool:
    """Multi_select columns where N/A is a meaningful explicit value (not blank)."""
    if is_dinner_lunch_category_column(column.name):
        return True
    return column.name in ("Cuisine", "Tags")


def column_has_na_option(column: ColumnInfo) -> bool:
    if column.name == "Protein":
        return any(opt.strip() in PROTEIN_NOT_APPLICABLE_LABELS for opt in column.options)
    if not column_expects_na_option(column):
        return True
    return dinner_lunch_category_na_option(column.options) is not None


def collect_recipes_na_option_errors(
    schema: DatabaseSchema,
    *,
    database_label: str = "[GW CI] Recipes",
) -> list[str]:
    """Schema errors when a metadata column is missing N/A (or Protein missing None/N/A)."""
    errors: list[str] = []
    for col in schema.filter_columns:
        if col.type != "multi_select":
            continue
        if col.name == "Protein":
            if protein_na_option(col.options) is None:
                errors.append(
                    f"{database_label}: Protein multi_select should include an N/A option "
                    f"({PROTEIN_LEGACY_NONE_LABEL!r} is legacy)."
                )
            continue
        if column_expects_na_option(col) and not column_has_na_option(col):
            errors.append(
                f"{database_label}: {col.name!r} multi_select must include an "
                f"N/A option for dessert, drink, and breakfast rows."
            )
    dinner_col_name = next(
        (c.name for c in schema.filter_columns if is_dinner_lunch_category_column(c.name)),
        None,
    )
    if dinner_col_name is None:
        errors.append(
            f"{database_label}: missing Dinner/Lunch Category (or legacy Dinner Category) "
            "multi_select column."
        )
    return errors
