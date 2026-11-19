"""Tests for Notion recipe column name resolution."""

from src.grocery_wizard.integrations.notion import ColumnInfo
from src.grocery_wizard.recipes.classify import classify_column
from src.grocery_wizard.recipes.recipe_schema_columns import (
    dinner_lunch_category_column_name,
    dinner_lunch_category_na_option,
    diversity_planning_columns,
    is_dinner_lunch_category_column,
    is_dinner_lunch_category_na_only,
)


def test_is_dinner_lunch_category_column_accepts_renamed_notion_column() -> None:
    assert is_dinner_lunch_category_column("Dinner Category")
    assert is_dinner_lunch_category_column("Dinner/lunch category")
    assert is_dinner_lunch_category_column("Dinner/Lunch Category")


def test_dinner_lunch_category_na_option() -> None:
    assert dinner_lunch_category_na_option(["Pasta", "N/A"]) == "N/A"


def test_is_dinner_lunch_category_na_only() -> None:
    assert is_dinner_lunch_category_na_only(["N/A"], na_label="N/A")
    assert not is_dinner_lunch_category_na_only(["Pasta"], na_label="N/A")
    assert not is_dinner_lunch_category_na_only([], na_label="N/A")


def test_classify_column_uses_rules_for_dinner_lunch_category() -> None:
    opts = ["Pasta", "Salad"]
    assert (
        classify_column(
            "Dinner/lunch category",
            "Creamy Tomato Pasta",
            ["pasta"],
            allowed_options=opts,
        )
        == "Pasta"
    )


def test_diversity_planning_columns_uses_renamed_column() -> None:
    dinner_col = ColumnInfo(name="Dinner/lunch category", type="multi_select", options=["Pasta"])
    cols = {
        "Protein": ColumnInfo(name="Protein", type="multi_select"),
        "Dinner/lunch category": dinner_col,
        "Cuisine": ColumnInfo(name="Cuisine", type="multi_select"),
    }
    assert diversity_planning_columns(cols) == ("Protein", "Dinner/lunch category", "Cuisine")


def test_dinner_lunch_column_from_filter_columns() -> None:
    cols = [
        ColumnInfo(name="Meal", type="multi_select"),
        ColumnInfo(name="Dinner/lunch category", type="multi_select"),
    ]
    assert dinner_lunch_category_column_name(cols) == "Dinner/lunch category"
