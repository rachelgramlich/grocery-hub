"""Recipe maintenance page — batch backfill for Notion recipe rows."""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from src.grocery_wizard.integrations.notion import NotionRecipesDB, Recipe, recipe_lookup_key
from src.grocery_wizard.integrations.notion_views import (
    ensure_manual_ingredients_notion_view_url,
    ensure_possibly_missing_checkboxes_notion_view_url,
)
from src.grocery_wizard.integrations.nyt_cooking import (
    NYTCookingClient,
    NytReclassifyChange,
    NytSyncProgressUpdate,
    credentials_status,
    format_reclassify_summary,
    reclassify_nyt_synced_recipes,
)
from src.grocery_wizard.recipes.recipe_maintenance import (
    BackfillSummary,
    FractionCallback,
    ProgressCallback,
    format_backfill_summary,
    format_recipe_progress_line,
    recipes_invalid_dinner_category,
    recipes_legacy_protein_none,
    recipes_manual_ingredients_in_notion,
    recipes_missing_cover_images,
    recipes_missing_ingredients,
    recipes_missing_metadata,
    recipes_possibly_missing_all_checkboxes,
    run_common_metadata_repair,
    run_image_backfill,
    run_ingredients_backfill,
    run_metadata_backfill,
    run_strip_invalid_dinner_categories,
)
from src.grocery_wizard.ui.db_access import get_db
from src.grocery_wizard.ui.meal_plan_status_ui import (
    meal_plan_status_editor_context,
    render_meal_plan_status_for_recipe,
    render_meal_plan_status_unavailable,
)
from src.grocery_wizard.ui.notion_cache import cached_query_recipes, invalidate_recipes_after_write


def _nyt_client_if_configured() -> NYTCookingClient | None:
    if not credentials_status()["configured"]:
        return None
    return NYTCookingClient()


def _write_backfill_progress_line(line: str) -> None:
    """Render a backfill log line; recipe rows use Markdown links into Notion."""
    if "](https://" in line:
        st.markdown(line)
    else:
        st.write(line)


def _nyt_sync_progress_log_line(update: NytSyncProgressUpdate) -> str | None:
    """Map NYT sync-style progress events to maintenance log lines."""
    message = update.message.strip()
    return message or None


def _format_reclassify_change_line(change: NytReclassifyChange) -> str:
    recipe = Recipe(
        page_id=change.page_id,
        name=change.name,
        link=None,
        ingredients=None,
        properties={},
    )
    return (
        f"{format_recipe_progress_line('', recipe)}: {change.field} "
        f"{change.old_value} → {change.new_value}"
    )


def _run_backfill_with_progress(
    *,
    label: str,
    runner: Callable[..., BackfillSummary],
) -> None:
    progress_lines: list[str] = []
    progress_bar = st.progress(0.0, text=f"{label}…")

    def on_progress(message: str) -> None:
        progress_lines.append(message)

    def on_fraction(fraction: float) -> None:
        progress_bar.progress(min(max(fraction, 0.0), 1.0), text=f"{label}…")

    with st.status(label, expanded=True) as status:
        summary = runner(on_progress=on_progress, on_fraction=on_fraction)
        for line in progress_lines[-40:]:
            _write_backfill_progress_line(line)
        outcome = format_backfill_summary(label, summary)
        status.update(label=outcome, state="complete")

    progress_bar.progress(1.0, text=outcome)
    st.success(outcome)
    if summary.succeeded:
        invalidate_recipes_after_write(schema_may_change=True)


def _preview_count_line(count: int) -> None:
    st.write(f"**{count}** recipe(s) will appear in Notion with this filter.")


def _render_meal_plan_status_section(db: NotionRecipesDB, recipes: list[Recipe]) -> None:
    """Standalone flow: pick a recipe and update Notion meal-plan rotation status."""
    st.markdown("### Meal plan status")
    st.caption(
        "Set **Active**, **Favorite**, **Paused**, or **Deprecated** for any recipe in Notion. "
        "This does not change your weekly meal list — only how recipes appear in future planning."
    )
    with st.container(border=True):
        render_meal_plan_status_unavailable(db)
        status_context = meal_plan_status_editor_context(db)
        if status_context is not None and recipes:
            recipe_names = sorted({recipe.name for recipe in recipes}, key=str.casefold)
            selected_name = st.selectbox(
                "Recipe",
                options=recipe_names,
                key="recipe_maint_meal_plan_status_recipe",
            )
            by_name = {recipe_lookup_key(recipe.name): recipe for recipe in recipes}
            selected_recipe = by_name.get(recipe_lookup_key(selected_name))
            if selected_recipe is not None:
                render_meal_plan_status_for_recipe(
                    db,
                    selected_recipe,
                    scope="maintenance",
                )
        elif status_context is not None:
            st.info("No recipes in Notion yet.")


def _render_open_notion_button(*, label: str, url: str, key: str, disabled: bool) -> None:
    st.link_button(
        label,
        url,
        type="primary",
        use_container_width=True,
        key=key,
        disabled=disabled,
    )


def render_recipe_maintenance() -> None:
    st.caption(
        "Housekeeping for recipes already in Notion — fill missing ingredients or metadata "
        "from recipe links without using **Add Recipe**."
    )

    db = get_db()
    schema = db.schema
    recipes = cached_query_recipes(db)

    missing_ingredients = recipes_missing_ingredients(recipes, schema)
    missing_metadata = recipes_missing_metadata(recipes, schema)
    invalid_dinner_category = recipes_invalid_dinner_category(recipes, schema)
    legacy_protein_none = recipes_legacy_protein_none(recipes, schema)
    missing_images = recipes_missing_cover_images(recipes, schema)
    manual_ingredients = recipes_manual_ingredients_in_notion(recipes, schema)
    possibly_missing_checkboxes = recipes_possibly_missing_all_checkboxes(recipes, schema)
    checkbox_names = [col.name for col in schema.checkbox_columns]

    _render_meal_plan_status_section(db, recipes)

    st.markdown("### Fix mistaken metadata")
    st.caption(
        "These actions **overwrite** specific bad values (unlike metadata backfill, which only "
        "fills empty cells). Run after classifier improvements or bulk NYT imports."
    )

    nyt_client = _nyt_client_if_configured()
    nyt_synced_count = 0
    nyt_col = db.nyt_synced_column_name()
    if nyt_col:
        nyt_synced_count = sum(1 for r in recipes if r.properties.get(nyt_col))

    repair_disabled = (
        not invalid_dinner_category and not legacy_protein_none and not missing_metadata
    )

    with st.container(border=True):
        st.markdown("**Standard metadata repair**")
        st.caption(
            "1) Set **N/A** on Dinner/Lunch Category for non-main meals, 2) rewrite Protein "
            "**None** → **N/A**, then 3) backfill any other empty metadata."
        )
        st.write(
            f"**{len(invalid_dinner_category)}** bad dinner/lunch category · "
            f"**{len(legacy_protein_none)}** Protein None · "
            f"**{len(missing_metadata)}** empty metadata"
        )
        if st.button(
            "Run standard repair",
            type="primary",
            key="recipe_maint_standard_repair",
            disabled=repair_disabled,
        ):

            def _repair_runner(
                *,
                on_progress: ProgressCallback | None = None,
                on_fraction: FractionCallback | None = None,
            ) -> BackfillSummary:
                combined = run_common_metadata_repair(
                    db,
                    recipes,
                    nyt_client=nyt_client,
                    on_progress=on_progress,
                    on_fraction=on_fraction,
                )
                parts = [
                    combined.strip,
                    combined.protein_none_to_na,
                    combined.backfill,
                ]
                return BackfillSummary(
                    scanned=sum(p.scanned for p in parts if p),
                    succeeded=sum(p.succeeded for p in parts if p),
                    failed=sum(p.failed for p in parts if p),
                    skipped=sum(p.skipped for p in parts if p),
                )

            _run_backfill_with_progress(
                label="Standard metadata repair",
                runner=_repair_runner,
            )

    with st.container(border=True):
        st.markdown("**Set Dinner/Lunch Category to N/A (desserts / drinks / breakfast)**")
        st.caption(
            "Keeps **N/A** as the meaningful value for non-main meals; replaces wrong tags "
            "(One-Pot / One-Pan on brownies) or empty cells. Rows already **N/A** are left alone."
        )
        st.write(
            f"**{len(invalid_dinner_category)}** recipe(s) missing N/A or with a wrong category."
        )
        if st.button(
            "Set dinner/lunch category to N/A",
            type="secondary",
            key="recipe_maint_strip_dinner_category",
            disabled=not invalid_dinner_category,
        ):

            def _strip_runner(
                *,
                on_progress: ProgressCallback | None = None,
                on_fraction: FractionCallback | None = None,
            ) -> BackfillSummary:
                return run_strip_invalid_dinner_categories(
                    db,
                    invalid_dinner_category,
                    on_progress=on_progress,
                    on_fraction=on_fraction,
                )

            _run_backfill_with_progress(
                label="Set dinner/lunch category to N/A",
                runner=_strip_runner,
            )

    with st.container(border=True):
        st.markdown("**Reclassify NYT-synced recipes**")
        st.caption(
            "For rows with **Synced from NYT recipe box** checked: re-infers **Meal** from title "
            "and ingredients, **Weeknight Friendly** from NYT cook time, and sets "
            "**Dinner/Lunch Category** to **N/A** on desserts/drinks/breakfast. "
            "**Overwrites** existing values when the classifier disagrees (unlike standard repair, "
            "which only fixes rule-invalid dinner/lunch tags and empty cells)."
        )
        if not nyt_col:
            st.info("Add a **Synced from NYT recipe box** checkbox in Notion to use this step.")
        elif nyt_client is None:
            st.info("Set NYT credentials in `.env` to fetch cook times and run reclassify.")
        else:
            st.write(f"**{nyt_synced_count}** NYT-synced recipe(s) in Notion.")
            reclassify_dry = st.checkbox(
                "Dry run (log changes only)",
                key="recipe_maint_nyt_reclassify_dry",
            )
            if st.button(
                "Reclassify NYT-synced metadata",
                type="secondary",
                key="recipe_maint_nyt_reclassify",
                disabled=nyt_synced_count == 0,
            ):
                progress_lines: list[str] = []
                progress_bar = st.progress(0.0, text="NYT reclassify…")

                def on_progress(update: NytSyncProgressUpdate) -> None:
                    line = _nyt_sync_progress_log_line(update)
                    if line is not None:
                        progress_lines.append(line)

                with st.status("NYT reclassify", expanded=True) as status:
                    summary = reclassify_nyt_synced_recipes(
                        db,
                        nyt_client,
                        dry_run=reclassify_dry,
                        on_progress=on_progress,
                    )
                    for line in progress_lines[-40:]:
                        _write_backfill_progress_line(line)
                    if summary.changes:
                        for change in summary.changes[:30]:
                            _write_backfill_progress_line(_format_reclassify_change_line(change))
                    outcome = format_reclassify_summary(summary)
                    status.update(label=outcome, state="complete")
                progress_bar.progress(1.0, text=outcome)
                st.success(outcome)
                if not reclassify_dry and (
                    summary.meal_changes
                    or summary.dinner_category_cleared
                    or summary.weeknight_set
                    or summary.weeknight_cleared
                ):
                    invalidate_recipes_after_write(schema_may_change=True)

    st.markdown("### Automatic backfill")

    with st.container(border=True):
        st.markdown("**Backfill missing ingredients**")
        st.caption("Recipes with a link but empty Ingredients column.")
        if not schema.ingredients_column:
            st.info("This Notion database has no Ingredients column configured.")
        else:
            st.write(f"**{len(missing_ingredients)}** recipe(s) missing ingredients.")
            if st.button(
                "Start ingredients backfill",
                type="primary",
                key="recipe_maint_ingredients",
                disabled=not missing_ingredients,
            ):

                def _ingredients_runner(
                    *,
                    on_progress: ProgressCallback | None = None,
                    on_fraction: FractionCallback | None = None,
                ) -> BackfillSummary:
                    return run_ingredients_backfill(
                        db,
                        missing_ingredients,
                        on_progress=on_progress,
                        on_fraction=on_fraction,
                    )

                _run_backfill_with_progress(
                    label="Ingredients backfill",
                    runner=_ingredients_runner,
                )

    with st.container(border=True):
        st.markdown("**Backfill missing metadata**")
        st.caption(
            "Fills **empty** Meal, Cuisine, Protein, and **Dinner/Lunch Category** for **Dinner** "
            "and **Lunch** (one column). It does **not** overwrite values "
            "already set — use **Fix mistaken metadata** above for rule-based overwrites. "
            "**Weeknight Friendly** applies only when Meal includes Dinner. "
            "Instructions, NYT sync, and Showstopper are not auto-filled."
        )
        st.write(f"**{len(missing_metadata)}** recipe(s) with gaps in metadata columns.")
        if st.button(
            "Start metadata backfill",
            type="primary",
            key="recipe_maint_metadata",
            disabled=not missing_metadata,
        ):
            nyt_client = _nyt_client_if_configured()

            def _metadata_runner(
                *,
                on_progress: ProgressCallback | None = None,
                on_fraction: FractionCallback | None = None,
            ) -> BackfillSummary:
                return run_metadata_backfill(
                    db,
                    missing_metadata,
                    nyt_client=nyt_client,
                    on_progress=on_progress,
                    on_fraction=on_fraction,
                )

            _run_backfill_with_progress(label="Metadata backfill", runner=_metadata_runner)

    with st.container(border=True):
        st.markdown("**Backfill missing cover images**")
        image_column = schema.image_column
        if not image_column:
            st.info(
                "Add a Notion **Files** column (for example **Cover image**) and optionally set "
                "**GROCERY_WIZARD_RECIPE_IMAGE_COLUMN** in `.env`."
            )
        else:
            st.caption(
                f"Recipes with a **Link** but nothing in **{image_column}**. "
                "Images are downloaded once and stored in Notion (not hotlinked)."
            )
            st.write(f"**{len(missing_images)}** recipe(s) missing cover images.")
            dry_run = st.checkbox(
                "Dry run (resolve URLs only — no Notion upload)",
                key="recipe_maint_image_dry_run",
            )
            if st.button(
                "Start cover image backfill",
                type="primary",
                key="recipe_maint_images",
                disabled=not missing_images,
            ):

                def _image_runner(
                    *,
                    on_progress: ProgressCallback | None = None,
                    on_fraction: FractionCallback | None = None,
                ) -> BackfillSummary:
                    return run_image_backfill(
                        db,
                        missing_images,
                        dry_run=dry_run,
                        on_progress=on_progress,
                        on_fraction=on_fraction,
                    )

                _run_backfill_with_progress(
                    label="Cover image backfill (dry run)" if dry_run else "Cover image backfill",
                    runner=_image_runner,
                )

    st.markdown("### Manual backfill in Notion")
    st.caption("Open a filtered database view to edit rows yourself.")

    with st.container(border=True):
        st.markdown("**Write ingredients in Notion**")
        st.caption(
            "Filter: **Link** is empty and **Ingredients** is empty — rows we cannot "
            "auto-backfill; add URLs and ingredient lists by hand in Notion."
        )
        if not schema.ingredients_column:
            st.info("This Notion database has no Ingredients column configured.")
        else:
            _preview_count_line(len(manual_ingredients))
            try:
                ingredients_view_url = ensure_manual_ingredients_notion_view_url(db)
            except Exception as exc:
                st.error(f"Could not prepare Notion view: {exc}")
            else:
                _render_open_notion_button(
                    label="Open in Notion",
                    url=ingredients_view_url,
                    key="recipe_maint_notion_manual_ingredients",
                    disabled=not manual_ingredients,
                )

    with st.container(border=True):
        st.markdown("**Review checkbox columns in Notion**")
        if not checkbox_names:
            st.info("This Notion database has no checkbox review columns.")
        else:
            joined = ", ".join(f"**{name}**" for name in checkbox_names)
            st.caption(
                f"Filter: all of {joined} are unchecked. These may be missing metadata "
                "or intentionally left off — review and check boxes only where appropriate."
            )
            _preview_count_line(len(possibly_missing_checkboxes))
            try:
                checkboxes_view_url = ensure_possibly_missing_checkboxes_notion_view_url(db)
            except Exception as exc:
                st.error(f"Could not prepare Notion view: {exc}")
            else:
                _render_open_notion_button(
                    label="Open in Notion",
                    url=checkboxes_view_url,
                    key="recipe_maint_notion_manual_checkboxes",
                    disabled=not possibly_missing_checkboxes,
                )
