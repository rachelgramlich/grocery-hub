#!/usr/bin/env python3
"""Repair Notion recipe metadata: strip invalid dinner/lunch categories and backfill gaps."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from src.grocery_wizard.config import load_config  # noqa: E402
from src.grocery_wizard.integrations.notion import NotionRecipesDB  # noqa: E402
from src.grocery_wizard.integrations.nyt_cooking import (  # noqa: E402
    NYTCookingClient,
    credentials_status,
    load_credentials,
)
from src.grocery_wizard.recipes.recipe_maintenance import (  # noqa: E402
    format_backfill_summary,
    format_common_metadata_repair_summary,
    recipes_invalid_dinner_category,
    recipes_missing_metadata,
    run_common_metadata_repair,
    run_metadata_backfill,
    run_strip_invalid_dinner_categories,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Strip invalid categories then backfill empty metadata (default if no flags)",
    )
    parser.add_argument(
        "--strip",
        action="store_true",
        help="Clear Dinner/Lunch Category on dessert, drink, and breakfast rows",
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Fill empty metadata (including Dinner/Lunch Category for dinner and lunch)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report counts only; no writes")
    args = parser.parse_args()

    if not args.strip and not args.backfill and not args.repair:
        args.repair = True

    config = load_config()
    db = NotionRecipesDB(config)
    recipes = db.query_recipes()

    nyt_client = None
    if args.backfill and load_credentials() is not None:
        nyt_client = NYTCookingClient()
        print(f"NYT credentials: {credentials_status()}")

    if args.repair and not args.strip and not args.backfill:
        invalid = recipes_invalid_dinner_category(recipes, db.schema)
        missing = recipes_missing_metadata(recipes, db.schema)
        print(f"Repair: {len(invalid)} strip, {len(missing)} backfill candidates")
        if args.dry_run:
            return
        summary = run_common_metadata_repair(db, recipes, nyt_client=nyt_client)
        print(format_common_metadata_repair_summary(summary))
        return

    if args.strip:
        invalid = recipes_invalid_dinner_category(recipes, db.schema)
        print(f"Invalid dinner/lunch category on dessert/drink/breakfast: {len(invalid)}")
        if args.dry_run:
            for recipe in invalid[:50]:
                print(f"  would clear: {recipe.name}")
            if len(invalid) > 50:
                print(f"  ... and {len(invalid) - 50} more")
        else:
            summary = run_strip_invalid_dinner_categories(db, invalid)
            print(format_backfill_summary("Strip invalid dinner/lunch category", summary))

    if args.backfill:
        missing = recipes_missing_metadata(recipes, db.schema)
        print(f"Recipes with empty meal-aware metadata: {len(missing)}")
        if args.dry_run:
            for recipe in missing[:50]:
                print(f"  would backfill: {recipe.name}")
            if len(missing) > 50:
                print(f"  ... and {len(missing) - 50} more")
        else:
            summary = run_metadata_backfill(db, missing, nyt_client=nyt_client)
            print(format_backfill_summary("Metadata backfill", summary))


if __name__ == "__main__":
    main()