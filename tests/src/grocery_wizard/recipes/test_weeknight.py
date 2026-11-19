"""Tests for weeknight-friendly inference."""

from src.grocery_wizard.recipes.classify import classify_recipe
from src.grocery_wizard.recipes.weeknight import (
    DEFAULT_WEEKNIGHT_COLUMN,
    is_weeknight_friendly,
    weeknight_timing_minutes,
)

MEAL_OPTIONS = ["Breakfast", "Lunch", "Dinner", "Snack", "Dessert"]


def test_weeknight_true_when_dinner_under_60_minutes() -> None:
    assert is_weeknight_friendly(
        "Roast Chicken",
        meal="Dinner",
        total_minutes=45,
    )


def test_weeknight_false_when_dinner_over_60_minutes_without_title_hint() -> None:
    assert not is_weeknight_friendly(
        "Slow Braised Short Ribs",
        meal="Dinner",
        total_minutes=180,
    )


def test_weeknight_uses_prep_plus_cook_when_total_includes_marinating() -> None:
    assert weeknight_timing_minutes(total_minutes=75, prep_minutes=20, cook_minutes=25) == 45
    assert is_weeknight_friendly(
        "Bulgogi-Style Tofu",
        meal="Dinner",
        total_minutes=75,
        prep_minutes=20,
        cook_minutes=25,
    )
    assert not is_weeknight_friendly(
        "Slow Braised Short Ribs",
        meal="Dinner",
        total_minutes=240,
        prep_minutes=30,
        cook_minutes=180,
    )


def test_weeknight_true_at_exactly_sixty_minutes() -> None:
    assert is_weeknight_friendly(
        "One-Hour Roast Chicken",
        meal="Dinner",
        total_minutes=60,
    )


def test_weeknight_uses_cook_when_prep_includes_long_passive_marinating() -> None:
    """NYT prep often counts marinating; cook alone reflects stove time."""
    assert weeknight_timing_minutes(total_minutes=90, prep_minutes=50, cook_minutes=25) == 25
    assert is_weeknight_friendly(
        "Bulgogi-Style Tofu",
        meal="Dinner",
        total_minutes=90,
        prep_minutes=50,
        cook_minutes=25,
    )


def test_weeknight_true_from_title_heuristic() -> None:
    assert is_weeknight_friendly("Sheet Pan Chicken", meal="Dinner")
    assert is_weeknight_friendly("One-Pot Pasta", meal="Dinner")
    assert is_weeknight_friendly("30-Minute Stir Fry", meal="Dinner")
    assert is_weeknight_friendly("Easy Weeknight Tacos", meal="Dinner")


def test_weeknight_false_for_non_dinner_meals() -> None:
    assert not is_weeknight_friendly("Quick Chocolate Cake", meal="Dessert", total_minutes=30)
    assert not is_weeknight_friendly("Easy Pancakes", meal="Breakfast", total_minutes=20)


def test_weeknight_false_when_meal_unset() -> None:
    assert not is_weeknight_friendly("Quick Pasta", meal=None, total_minutes=30)


def test_weeknight_true_when_dinner_in_multi_select() -> None:
    assert is_weeknight_friendly(
        "Sheet Pan Chicken",
        meal=["Dinner", "Lunch"],
        total_minutes=45,
    )
    assert is_weeknight_friendly("One-Pot Pasta", meal=["Dinner"])
    assert not is_weeknight_friendly("Quick Cake", meal=["Dessert", "Snack/Side"], total_minutes=30)


def test_classify_recipe_sets_weeknight_checkbox_for_dinner() -> None:
    result = classify_recipe(
        "Quick Sheet Pan Salmon",
        ["salmon", "lemon"],
        [("Meal", "select", MEAL_OPTIONS)],
        weeknight_column=DEFAULT_WEEKNIGHT_COLUMN,
    )
    assert result["Meal"] == "Dinner"
    assert result[DEFAULT_WEEKNIGHT_COLUMN] is True


def test_classify_recipe_clears_weeknight_for_dessert() -> None:
    result = classify_recipe(
        "Easy Chocolate Cake",
        ["flour", "sugar", "cocoa"],
        [("Meal", "select", MEAL_OPTIONS)],
        weeknight_column=DEFAULT_WEEKNIGHT_COLUMN,
    )
    assert result["Meal"] == "Dessert"
    assert result[DEFAULT_WEEKNIGHT_COLUMN] is False


def test_classify_recipe_uses_total_minutes_for_weeknight() -> None:
    result = classify_recipe(
        "Herb Roast Chicken",
        ["chicken", "herbs"],
        [("Meal", "select", MEAL_OPTIONS)],
        total_minutes=50,
        weeknight_column=DEFAULT_WEEKNIGHT_COLUMN,
    )
    assert result["Meal"] == "Dinner"
    assert result[DEFAULT_WEEKNIGHT_COLUMN] is True


def test_classify_recipe_sets_weeknight_for_multi_select_meal_column() -> None:
    result = classify_recipe(
        "Quick Sheet Pan Salmon",
        ["salmon", "lemon"],
        [("Meal", "multi_select", MEAL_OPTIONS)],
        weeknight_column=DEFAULT_WEEKNIGHT_COLUMN,
    )
    assert result["Meal"] == ["Dinner"]
    assert result[DEFAULT_WEEKNIGHT_COLUMN] is True
