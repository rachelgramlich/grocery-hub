"""Infer whether a dinner recipe is weeknight-friendly."""

from __future__ import annotations

__all__ = [
    "DEFAULT_WEEKNIGHT_COLUMN",
    "WEEKNIGHT_MAX_MINUTES",
    "is_weeknight_friendly",
    "weeknight_timing_minutes",
]

import re
from typing import Any

WEEKNIGHT_TITLE_PATTERN = re.compile(
    r"\b("
    r"weeknight|quick|easy|simple|"
    r"30[- ]?minute|45[- ]?minute|"
    r"one[- ]?pot|one[- ]?pan|sheet[- ]?pan|skillet|"
    r"stir[- ]?fry|stir fry"
    r")\b",
    re.IGNORECASE,
)

DEFAULT_WEEKNIGHT_COLUMN = "Dinner: Weeknight Friendly"
WEEKNIGHT_MAX_MINUTES = 60


def weeknight_timing_minutes(
    *,
    total_minutes: float | None = None,
    prep_minutes: float | None = None,
    cook_minutes: float | None = None,
) -> float | None:
    """Minutes used for the weeknight time threshold.

    NYT *total* often includes inactive marinating; when total is at/above the cap
    but prep plus cook are under it, use that active time instead. When prep
    includes long passive steps (e.g. bulgogi marinating) but *cook* is short,
    trust cook time under the cap.
    """
    if total_minutes is not None and total_minutes <= WEEKNIGHT_MAX_MINUTES:
        return total_minutes
    if prep_minutes is not None and cook_minutes is not None:
        active = prep_minutes + cook_minutes
        if active <= WEEKNIGHT_MAX_MINUTES:
            return active
    if cook_minutes is not None and cook_minutes <= WEEKNIGHT_MAX_MINUTES:
        return cook_minutes
    return total_minutes


def _meal_includes_dinner(meal: Any) -> bool:
    if meal is None:
        return False
    if isinstance(meal, list):
        return any(str(item).strip() == "Dinner" for item in meal if str(item).strip())
    return str(meal).strip() == "Dinner"


def is_weeknight_friendly(
    title: str,
    *,
    meal: str | list[str] | None,
    total_minutes: float | None = None,
    prep_minutes: float | None = None,
    cook_minutes: float | None = None,
) -> bool:
    """Return whether a recipe qualifies as weeknight-friendly dinner.

    Criteria (require Meal to include Dinner — string or multi-select list):
    - Active cook time under 60 minutes when available, or
    - Title heuristics: quick, easy, weeknight, one-pot, sheet pan, etc.
    """
    if not _meal_includes_dinner(meal):
        return False

    timing_minutes = weeknight_timing_minutes(
        total_minutes=total_minutes,
        prep_minutes=prep_minutes,
        cook_minutes=cook_minutes,
    )
    if timing_minutes is not None and timing_minutes <= WEEKNIGHT_MAX_MINUTES:
        return True

    return bool(WEEKNIGHT_TITLE_PATTERN.search(title))
