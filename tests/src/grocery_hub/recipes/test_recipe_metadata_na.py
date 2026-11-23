"""Tests for N/A option expectations on recipe metadata columns."""

from src.grocery_hub.integrations.notion import ColumnInfo, DatabaseSchema
from src.grocery_hub.recipes.recipe_metadata_na import collect_recipes_na_option_errors


def _schema_with_dinner_lunch(*, dinner_options: list[str]) -> DatabaseSchema:
    dinner = ColumnInfo(
        name="Dinner/Lunch Category",
        type="multi_select",
        options=dinner_options,
    )
    cuisine = ColumnInfo(name="Cuisine", type="multi_select", options=["American", "N/A"])
    tags = ColumnInfo(name="Tags", type="multi_select", options=["Weeknight", "N/A"])
    protein = ColumnInfo(name="Protein", type="multi_select", options=["N/A", "None", "Chicken"])
    cols = {
        "Name": ColumnInfo(name="Name", type="title"),
        "Link": ColumnInfo(name="Link", type="url"),
        "Ingredients": ColumnInfo(name="Ingredients", type="rich_text"),
        "Dinner/Lunch Category": dinner,
        "Cuisine": cuisine,
        "Tags": tags,
        "Protein": protein,
    }
    return DatabaseSchema(
        name_column="Name",
        link_column="Link",
        ingredients_column="Ingredients",
        filter_columns=[dinner, cuisine, tags, protein],
        checkbox_columns=[],
        all_columns=cols,
    )


def test_collect_recipes_na_option_errors_ok() -> None:
    assert (
        collect_recipes_na_option_errors(_schema_with_dinner_lunch(dinner_options=["N/A", "Pasta"]))
        == []
    )


def test_collect_recipes_na_option_errors_missing_na_on_dinner_lunch() -> None:
    errors = collect_recipes_na_option_errors(_schema_with_dinner_lunch(dinner_options=["Pasta"]))
    assert any("Dinner/Lunch Category" in err and "N/A" in err for err in errors)


def test_collect_recipes_na_option_errors_missing_dinner_lunch_column() -> None:
    schema = DatabaseSchema(
        name_column="Name",
        link_column="Link",
        ingredients_column="Ingredients",
        filter_columns=[],
        checkbox_columns=[],
        all_columns={
            "Name": ColumnInfo(name="Name", type="title"),
            "Link": ColumnInfo(name="Link", type="url"),
        },
    )
    errors = collect_recipes_na_option_errors(schema)
    assert any("Dinner/Lunch Category" in err for err in errors)
