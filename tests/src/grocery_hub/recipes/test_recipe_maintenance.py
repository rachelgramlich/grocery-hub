"""Tests for recipe maintenance backfill helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.grocery_hub.integrations.notion import ColumnInfo, DatabaseSchema, Recipe
from src.grocery_hub.recipes.recipe_maintenance import (
    BackfillSummary,
    _resolve_total_minutes,
    format_backfill_failed_line,
    format_recipe_progress_line,
    infer_metadata_field_values,
    is_blank_metadata_value,
    recipe_has_cover_image,
    recipe_has_invalid_dinner_category,
    recipe_manual_ingredients_in_notion,
    recipe_missing_cover_image,
    recipe_missing_ingredients,
    recipe_missing_metadata,
    recipe_notion_markdown_link,
    recipe_possibly_missing_all_checkboxes,
    recipes_invalid_dinner_category,
    recipes_missing_ingredients,
    recipes_missing_metadata,
    run_common_metadata_repair,
    run_image_backfill,
    run_ingredients_backfill,
    run_metadata_backfill,
    run_normalize_protein_none_to_na,
    run_strip_invalid_dinner_categories,
)
from src.grocery_hub.recipes.scraper import ScrapedRecipe, ScrapeError


def _schema() -> DatabaseSchema:
    return _full_schema(filter_columns_only_meal=True)


def _full_schema(*, filter_columns_only_meal: bool = False) -> DatabaseSchema:
    meal = ColumnInfo(name="Meal", type="select", options=["Dinner", "Dessert", "Lunch"])
    weeknight = ColumnInfo(name="Dinner: Weeknight Friendly", type="checkbox", options=[])
    cuisine = ColumnInfo(name="Cuisine", type="multi_select", options=["Italian"])
    protein = ColumnInfo(
        name="Protein",
        type="multi_select",
        options=["N/A", "None", "Chicken"],
    )
    dinner_category = ColumnInfo(
        name="Dinner Category",
        type="multi_select",
        options=["Pasta", "N/A"],
    )
    filter_columns = [meal]
    if not filter_columns_only_meal:
        filter_columns = [meal, cuisine, protein, dinner_category]
    return DatabaseSchema(
        name_column="Name",
        link_column="Link",
        ingredients_column="Ingredients",
        instructions_column="Instructions",
        filter_columns=filter_columns,
        checkbox_columns=[weeknight],
        all_columns={
            "Name": ColumnInfo(name="Name", type="title"),
            "Link": ColumnInfo(name="Link", type="url"),
            "Ingredients": ColumnInfo(name="Ingredients", type="rich_text"),
            "Instructions": ColumnInfo(name="Instructions", type="rich_text"),
            "Meal": meal,
            "Cuisine": cuisine,
            "Protein": protein,
            "Dinner Category": dinner_category,
            "Dinner: Weeknight Friendly": weeknight,
        },
    )


def _recipe(
    *,
    link: str = "https://example.com/r",
    ingredients: str = "",
    meal: str | None = None,
    weeknight: bool = False,
) -> Recipe:
    props = {
        "Meal": meal,
        "Dinner: Weeknight Friendly": weeknight,
        "Instructions": "",
    }
    return Recipe(
        page_id="page-1",
        name="Chicken Pasta",
        link=link,
        ingredients=ingredients,
        properties=props,
    )


def test_recipe_manual_ingredients_requires_empty_link_and_ingredients() -> None:
    schema = _schema()
    assert recipe_manual_ingredients_in_notion(_recipe(link="", ingredients=""), schema)
    assert not recipe_manual_ingredients_in_notion(_recipe(ingredients=""), schema)
    assert not recipe_manual_ingredients_in_notion(_recipe(link="", ingredients="salt"), schema)


def test_recipe_possibly_missing_all_checkboxes() -> None:
    schema = _schema()
    assert recipe_possibly_missing_all_checkboxes(
        _recipe(ingredients="x", meal="Dinner", weeknight=False),
        schema,
    )
    assert not recipe_possibly_missing_all_checkboxes(
        _recipe(ingredients="x", meal="Dinner", weeknight=True),
        schema,
    )


def test_recipe_missing_ingredients_predicate() -> None:
    schema = _schema()
    assert recipe_missing_ingredients(_recipe(ingredients=""), schema)
    assert not recipe_missing_ingredients(_recipe(ingredients="1 cup rice"), schema)
    assert not recipe_missing_ingredients(_recipe(link="", ingredients=""), schema)


def test_recipe_missing_metadata_predicate() -> None:
    schema = _schema()
    assert recipe_missing_metadata(_recipe(ingredients="1 cup rice", meal=None), schema)
    assert not recipe_missing_metadata(
        _recipe(ingredients="1 cup rice", meal="Dinner", weeknight=True),
        schema,
    )
    assert not recipe_missing_metadata(_recipe(ingredients="", meal=None), schema)


def test_unchecked_weeknight_counts_as_gap_for_dinner() -> None:
    schema = _schema()
    assert recipe_missing_metadata(
        _recipe(ingredients="1 cup rice", meal="Dinner", weeknight=False),
        schema,
    )


def test_dessert_needs_na_dinner_category_but_not_protein() -> None:
    schema = _full_schema()
    props = {
        "Meal": "Dessert",
        "Cuisine": ["Italian"],
        "Protein": None,
        "Dinner Category": None,
        "Dinner: Weeknight Friendly": False,
    }
    recipe = Recipe(
        page_id="page-1",
        name="Brownies",
        link="https://example.com/r",
        ingredients="flour",
        properties=props,
    )
    assert recipe_missing_metadata(recipe, schema)

    props["Dinner Category"] = ["N/A"]
    recipe_ok = Recipe(
        page_id="page-1",
        name="Brownies",
        link="https://example.com/r",
        ingredients="flour",
        properties=props,
    )
    assert not recipe_missing_metadata(recipe_ok, schema)


def test_is_blank_metadata_value() -> None:
    assert is_blank_metadata_value("select", None)
    assert is_blank_metadata_value("multi_select", [])
    assert not is_blank_metadata_value("select", "Dinner")


def test_recipes_missing_lists() -> None:
    schema = _schema()
    recipes = [
        _recipe(ingredients=""),
        _recipe(ingredients="salt", meal="Dinner", weeknight=True),
        _recipe(ingredients="pepper", meal=None),
    ]
    assert len(recipes_missing_ingredients(recipes, schema)) == 1
    assert len(recipes_missing_metadata(recipes, schema)) == 1


def test_run_ingredients_backfill_updates_notion() -> None:
    schema = _schema()
    db = MagicMock()
    db.schema = schema
    candidate = _recipe(ingredients="")

    scraped = ScrapedRecipe(
        url=candidate.link or "",
        title="Chicken Pasta",
        ingredients=["1 lb chicken", "8 oz pasta"],
    )

    with (
        patch(
            "src.grocery_hub.recipes.recipe_maintenance.scrape_recipe",
            return_value=scraped,
        ),
        patch(
            "src.grocery_hub.recipes.recipe_maintenance.prepare_ingredients_for_notion",
            side_effect=lambda text, **_: text,
        ),
    ):
        summary = run_ingredients_backfill(db, [candidate])

    assert summary.succeeded == 1
    db.update_recipe.assert_called_once()
    args = db.update_recipe.call_args[0]
    assert args[0] == "page-1"
    assert "Ingredients" in args[1]


def test_run_ingredients_backfill_counts_scrape_errors() -> None:
    schema = _schema()
    db = MagicMock()
    db.schema = schema
    candidate = _recipe(ingredients="")
    lines: list[str] = []

    with patch(
        "src.grocery_hub.recipes.recipe_maintenance.scrape_recipe",
        side_effect=ScrapeError("blocked"),
    ):
        summary = run_ingredients_backfill(
            db,
            [candidate],
            on_progress=lines.append,
        )

    assert summary.failed == 1
    db.update_recipe.assert_not_called()
    assert len(lines) == 2
    assert lines[0] == format_recipe_progress_line("Scraping ingredients: ", candidate)
    assert "notion.so/page1" in lines[0]
    assert lines[1] == format_backfill_failed_line(candidate, "blocked")
    assert "notion.so/page1" in lines[1]


def test_format_recipe_progress_line_skipped_uses_notion_link() -> None:
    recipe = _recipe(ingredients="")
    line = format_recipe_progress_line("Skipped (no ingredients on page): ", recipe)
    assert line.startswith("Skipped (no ingredients on page): [Chicken Pasta]")
    assert "notion.so/page1" in line


def test_recipe_notion_markdown_link_escapes_brackets() -> None:
    recipe = Recipe(
        page_id="abc-def",
        name="Spicy [test] chicken",
        link="https://example.com",
        ingredients="",
        properties={},
    )
    linked = recipe_notion_markdown_link(recipe)
    assert linked.startswith("[Spicy \\[test\\] chicken]")
    assert linked.endswith("(https://www.notion.so/abcdef)")


def test_recipe_has_invalid_dinner_category() -> None:
    schema = _full_schema()
    dessert_wrong = _recipe(meal="Dessert")
    dessert_wrong.properties["Dinner Category"] = ["Pasta"]
    dessert_ok = _recipe(meal="Dessert")
    dessert_ok.properties["Dinner Category"] = ["N/A"]
    dinner_ok = _recipe(meal="Dinner")
    dinner_ok.properties["Dinner Category"] = ["Pasta"]
    assert recipe_has_invalid_dinner_category(dessert_wrong, schema)
    assert not recipe_has_invalid_dinner_category(dessert_ok, schema)
    assert not recipe_has_invalid_dinner_category(dinner_ok, schema)
    assert len(recipes_invalid_dinner_category([dessert_wrong, dessert_ok, dinner_ok], schema)) == 1


def test_run_common_metadata_repair_runs_strip_and_backfill() -> None:
    db = MagicMock()
    recipes = [_recipe(meal="Dessert")]

    with (
        patch(
            "src.grocery_hub.recipes.recipe_maintenance.run_strip_invalid_dinner_categories",
            return_value=BackfillSummary(succeeded=1, scanned=1),
        ) as strip_mock,
        patch(
            "src.grocery_hub.recipes.recipe_maintenance.run_normalize_protein_none_to_na",
            return_value=BackfillSummary(succeeded=0, scanned=0),
        ) as protein_mock,
        patch(
            "src.grocery_hub.recipes.recipe_maintenance.run_metadata_backfill",
            return_value=BackfillSummary(succeeded=2, scanned=3),
        ) as backfill_mock,
    ):
        summary = run_common_metadata_repair(db, recipes)

    assert summary.strip is not None
    assert summary.strip.succeeded == 1
    assert summary.protein_none_to_na is not None
    assert summary.backfill is not None
    assert summary.backfill.succeeded == 2
    strip_mock.assert_called_once()
    protein_mock.assert_called_once()
    backfill_mock.assert_called_once()


def test_run_normalize_protein_none_to_na() -> None:
    schema = _full_schema()
    db = MagicMock()
    db.schema = schema
    dessert = _recipe(meal="Dessert")
    dessert.properties["Protein"] = ["None"]
    summary = run_normalize_protein_none_to_na(db, [dessert])
    assert summary.succeeded == 1
    db.update_recipe.assert_called_once_with("page-1", {"Protein": ["N/A"]})


def test_dessert_with_na_only_dinner_category_not_invalid() -> None:
    schema = _full_schema()
    dessert_ok = _recipe(meal="Dessert")
    dessert_ok.properties["Dinner Category"] = ["N/A"]
    assert not recipe_has_invalid_dinner_category(dessert_ok, schema)


def test_run_strip_invalid_dinner_categories() -> None:
    schema = _full_schema()
    db = MagicMock()
    db.schema = schema
    dessert_wrong = _recipe(meal="Dessert")
    dessert_wrong.properties["Dinner Category"] = ["Pasta"]
    summary = run_strip_invalid_dinner_categories(db, [dessert_wrong])
    assert summary.succeeded == 1
    db.update_recipe.assert_called_once_with("page-1", {"Dinner Category": ["N/A"]})


def test_infer_metadata_does_not_overwrite_non_blank_dinner_category() -> None:
    schema = _full_schema()
    db = MagicMock()
    db.schema = schema
    candidate = _recipe(ingredients="1 lb chicken", meal="Dessert", weeknight=False)
    candidate.properties["Dinner Category"] = ["N/A"]

    updates = infer_metadata_field_values(db, candidate)

    assert "Dinner Category" not in updates
    assert "Meal" not in updates


def test_run_metadata_backfill_fills_blanks_only() -> None:
    schema = _schema()
    db = MagicMock()
    db.schema = schema
    candidate = _recipe(ingredients="1 lb chicken\n8 oz pasta", meal=None, weeknight=False)

    with patch(
        "src.grocery_hub.recipes.recipe_maintenance.infer_metadata_field_values",
        return_value={"Meal": "Dinner"},
    ):
        summary = run_metadata_backfill(db, [candidate])

    assert summary.succeeded == 1
    db.update_recipe.assert_called_once_with("page-1", {"Meal": "Dinner"})


def test_resolve_total_minutes_continues_when_scrape_blocked() -> None:
    with patch(
        "src.grocery_hub.recipes.recipe_maintenance.scrape_recipe",
        side_effect=ScrapeError("Could not fetch recipe page: 403 Client Error"),
    ):
        minutes = _resolve_total_minutes("https://example.com/r", nyt_client=None)

    assert minutes is None


def test_recipe_missing_cover_image() -> None:
    schema = _full_schema(filter_columns_only_meal=True)
    schema = DatabaseSchema(
        name_column=schema.name_column,
        link_column=schema.link_column,
        ingredients_column=schema.ingredients_column,
        image_column="Cover image",
        filter_columns=schema.filter_columns,
        checkbox_columns=schema.checkbox_columns,
        all_columns={
            **schema.all_columns,
            "Cover image": ColumnInfo(name="Cover image", type="files"),
        },
    )
    empty = _recipe(link="https://example.com")
    with_image = _recipe(link="https://example.com")
    with_image.properties["Cover image"] = ["recipe-cover.jpg"]
    assert recipe_missing_cover_image(empty, schema)
    assert not recipe_missing_cover_image(with_image, schema)
    assert not recipe_missing_cover_image(_recipe(link=""), schema)
    assert recipe_has_cover_image(with_image, schema)


def test_run_image_backfill_dry_run_counts_success() -> None:
    schema = DatabaseSchema(
        name_column="Name",
        link_column="Link",
        ingredients_column="Ingredients",
        image_column="Cover image",
        filter_columns=[],
        checkbox_columns=[],
        all_columns={
            "Name": ColumnInfo(name="Name", type="title"),
            "Link": ColumnInfo(name="Link", type="url"),
            "Ingredients": ColumnInfo(name="Ingredients", type="rich_text"),
            "Cover image": ColumnInfo(name="Cover image", type="files"),
        },
    )
    db = MagicMock()
    db.schema = schema
    candidate = _recipe(link="https://example.com/r")
    resolved = MagicMock(host="other_web", method="html_meta", image_url="https://cdn/x.jpg")
    with patch(
        "src.grocery_hub.recipes.recipe_maintenance.resolve_recipe_image_url",
        return_value=resolved,
    ):
        summary = run_image_backfill(db, [candidate], dry_run=True)
    assert summary.succeeded == 1
    db.upload_recipe_image_file.assert_not_called()


def test_run_metadata_backfill_continues_after_scrape_failure() -> None:
    schema = _schema()
    db = MagicMock()
    db.schema = schema
    candidate = _recipe(ingredients="1 lb chicken", meal=None)

    with patch(
        "src.grocery_hub.recipes.recipe_maintenance.infer_metadata_field_values",
        side_effect=ScrapeError("Could not fetch recipe page: 403 Client Error"),
    ):
        summary = run_metadata_backfill(db, [candidate])

    assert summary.failed == 1
    db.update_recipe.assert_not_called()


def test_infer_metadata_field_values_uses_classify() -> None:
    schema = _schema()
    db = MagicMock()
    db.schema = schema
    candidate = _recipe(ingredients="1 lb chicken breast", meal=None, weeknight=False)

    with patch(
        "src.grocery_hub.recipes.recipe_maintenance._resolve_total_minutes",
        return_value=45.0,
    ):
        updates = infer_metadata_field_values(db, candidate, nyt_client=None)

    assert updates.get("Meal") == "Dinner"
    assert updates.get("Dinner: Weeknight Friendly") is True
