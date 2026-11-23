"""Streamlit controls for syncing NYT Cooking recipe box to Notion."""

from __future__ import annotations

import streamlit as st

from src.grocery_hub.integrations.nyt_cooking import (
    NytAuthError,
    NYTCookingClient,
    NYTCookingError,
    NytRecipeBoxFolder,
    NytSyncProgressUpdate,
    credentials_status,
    default_orphan_target_folder,
    file_orphans_into_folder,
    format_metadata_review,
    format_notion_sync_outcome_message,
    format_orphan_file_summary,
    format_sync_summary,
    list_orphan_recipes,
    list_recipe_box_folders,
    load_sync_report,
    run_recipe_box_sync,
    verify_nyt_credentials,
)
from src.grocery_hub.ui.components.loading import loading_indicator
from src.grocery_hub.ui.db_access import get_db
from src.grocery_hub.ui.notion_cache import invalidate_recipes_after_write


def _folder_option_label(folder: NytRecipeBoxFolder) -> str:
    if folder.recipe_count is None:
        return folder.label
    return f"{folder.label} ({folder.recipe_count} recipes)"


@st.cache_data(show_spinner="Loading NYT recipe folders…", ttl=300)
def _cached_recipe_box_folders() -> list[NytRecipeBoxFolder]:
    client = NYTCookingClient()
    verify_nyt_credentials(client)
    return list_recipe_box_folders(client)


@st.cache_data(show_spinner="Checking for unfiled NYT recipes…", ttl=300)
def _cached_orphan_recipes() -> list[tuple[str, str]]:
    client = NYTCookingClient()
    verify_nyt_credentials(client)
    orphans = list_orphan_recipes(client)
    return [(recipe.id, recipe.name) for recipe in orphans]


def _clear_nyt_sync_caches() -> None:
    _cached_recipe_box_folders.clear()
    _cached_orphan_recipes.clear()


def _render_nyt_credentials_panel() -> bool:
    """Warn when NYT env vars are missing. Returns True when configured."""
    status = credentials_status()
    if status["configured"]:
        return True
    st.warning(
        "NYT credentials are not set. Add `NYT_S_COOKIE` and `NYT_REGI_ID` "
        "(or `NYT_USER_ID`) to your environment — see the package README.",
    )
    return False


def _load_nyt_recipe_box_folders() -> list[NytRecipeBoxFolder] | None:
    try:
        return _cached_recipe_box_folders()
    except NytAuthError as exc:
        st.error(str(exc))
        if st.button("Retry NYT connection", key="nyt_sync_retry_auth"):
            with loading_indicator("Reconnecting to NYT Cooking…"):
                _clear_nyt_sync_caches()
                _cached_recipe_box_folders()
            st.rerun()
        return None
    except NYTCookingError as exc:
        st.error(f"Could not load NYT recipe box: {exc}")
        return None


def _render_nyt_folder_picker(folders: list[NytRecipeBoxFolder]) -> NytRecipeBoxFolder:
    labels = [_folder_option_label(folder) for folder in folders]
    picked_label = st.selectbox(
        "Recipe-box folder",
        labels,
        key="nyt_sync_folder",
    )
    picked_index = labels.index(picked_label)
    return folders[picked_index]


def _render_nyt_sync_actions() -> tuple[bool, bool]:
    """Dry-run toggle, last-sync popover, refresh/run buttons."""
    dry_run = st.checkbox(
        "Dry run (preview only — no Notion writes)",
        value=False,
        key="nyt_sync_dry_run",
        help=(
            "Leave unchecked to write new recipes to Notion. "
            "Preview lists recipes that would be added and ingredient counts."
        ),
    )

    last_report = load_sync_report()
    if last_report is not None:
        with st.popover("Last sync metadata review"):
            st.text(format_metadata_review(last_report))

    run_col, refresh_col = st.columns(2)
    with refresh_col:
        if st.button(
            "Refresh folders",
            key="nyt_sync_refresh_folders",
            width="stretch",
        ):
            with loading_indicator("Refreshing NYT folders…"):
                _clear_nyt_sync_caches()
                _cached_recipe_box_folders()
            st.rerun()

    with run_col:
        run_clicked = st.button(
            "Preview sync" if dry_run else "Sync to Notion",
            key="nyt_sync_run",
            type="primary",
            width="stretch",
        )

    return run_clicked, dry_run


def _sync_progress_label(update: NytSyncProgressUpdate) -> str:
    if update.total and update.total > 0:
        return f"{update.processed} / {update.total} recipes"
    if update.processed:
        return f"{update.processed} recipe(s) processed"
    return "Starting sync…"


def _orphan_target_folder_options(folders: list[NytRecipeBoxFolder]) -> list[str]:
    names = [folder.label for folder in folders]
    default = default_orphan_target_folder()
    if default not in names:
        return [default, *names]
    return names


def _render_orphan_filing_panel(folders: list[NytRecipeBoxFolder]) -> None:
    """File saved recipes that are not in any NYT folder."""
    try:
        orphans = _cached_orphan_recipes()
    except (NytAuthError, NYTCookingError) as exc:
        st.caption(f"Could not check unfiled recipes: {exc}")
        return

    orphan_count = len(orphans)
    expand = orphan_count > 0
    with st.expander("Recipe box organization", expanded=expand):
        st.caption(
            "Recipes saved to your NYT recipe box but not in any folder. "
            "Filing adds them to a folder on NYT only — not Notion — and does not "
            "remove them from other folders."
        )
        if orphan_count == 0:
            st.success("All saved recipes are in at least one folder.")
            return

        st.info(
            f"**{orphan_count}** saved recipe(s) are not in any folder. "
            "File them so folder-based Notion sync can include them."
        )
        folder_options = _orphan_target_folder_options(folders)
        default_name = default_orphan_target_folder()
        default_index = folder_options.index(default_name) if default_name in folder_options else 0
        target_folder = st.selectbox(
            "Target folder",
            folder_options,
            index=default_index,
            key="nyt_orphan_target_folder",
        )
        with st.expander("Unfiled recipes", expanded=False):
            for recipe_id, recipe_name in orphans[:50]:
                st.write(f"{recipe_name} ({recipe_id})")
            if orphan_count > 50:
                st.caption(f"… and {orphan_count - 50} more")

        confirm_large_batch = True
        if orphan_count > 20:
            confirm_large_batch = st.checkbox(
                f"I want to file {orphan_count} recipes on NYT Cooking",
                value=False,
                key="nyt_orphan_confirm_large",
            )

        preview_col, file_col = st.columns(2)
        with preview_col:
            preview_clicked = st.button(
                "Preview filing",
                key="nyt_orphan_preview",
                width="stretch",
            )
        with file_col:
            file_clicked = st.button(
                "File unfiled recipes",
                key="nyt_orphan_file",
                type="primary",
                disabled=orphan_count > 20 and not confirm_large_batch,
                width="stretch",
            )

        if preview_clicked:
            _execute_orphan_filing(target_folder=target_folder, dry_run=True)
        elif file_clicked:
            _execute_orphan_filing(target_folder=target_folder, dry_run=False)


def _execute_orphan_filing(*, target_folder: str, dry_run: bool) -> None:
    client = NYTCookingClient()
    with st.status(
        "Previewing NYT filing…" if dry_run else "Filing unfiled recipes on NYT…",
        expanded=True,
    ) as status:
        progress = st.progress(0.0, text="Starting…")
        log_lines: list[str] = []

        def on_progress(update: NytSyncProgressUpdate) -> None:
            if update.message:
                log_lines.append(update.message)
            if update.total and update.total > 0:
                progress.progress(
                    min(update.processed / update.total, 1.0),
                    text=f"{update.processed} / {update.total} recipes",
                )

        try:
            summary = file_orphans_into_folder(
                client,
                folder_name=target_folder,
                dry_run=dry_run,
                on_progress=on_progress,
            )
        except (NytAuthError, NYTCookingError) as exc:
            status.update(label="Filing failed", state="error")
            st.error(str(exc))
            return

        if summary.orphans_total:
            progress.progress(1.0, text=f"{summary.orphans_total} recipe(s)")
        status.update(label=format_orphan_file_summary(summary), state="complete")

        if log_lines and not dry_run:
            with st.expander("Filing log", expanded=False):
                for line in log_lines:
                    st.write(line)

    if dry_run:
        st.info(format_orphan_file_summary(summary))
    else:
        _clear_nyt_sync_caches()
        if summary.added:
            st.success(
                f"NYT updated — filed {summary.added} recipe(s) into '{summary.target_folder}'."
            )
        elif summary.failed:
            st.warning(format_orphan_file_summary(summary))
        else:
            st.success(format_orphan_file_summary(summary))


def _execute_nyt_recipe_box_sync(
    *,
    folder: NytRecipeBoxFolder,
    dry_run: bool,
) -> None:
    progress_lines: list[str] = []

    db = get_db()
    client = NYTCookingClient()

    with st.status(
        "Previewing NYT recipes…" if dry_run else "Syncing NYT recipes to Notion…",
        expanded=True,
    ) as sync_status:
        with st.container(key="nyt_sync_progress"):
            progress_bar = st.progress(
                0.0,
                text=_sync_progress_label(
                    NytSyncProgressUpdate(message="", processed=0, total=folder.recipe_count),
                ),
            )

        def on_progress(update: NytSyncProgressUpdate) -> None:
            if update.message:
                progress_lines.append(update.message)
            if update.total and update.total > 0:
                fraction = min(update.processed / update.total, 1.0)
                progress_bar.progress(fraction, text=_sync_progress_label(update))
            elif update.processed:
                progress_bar.progress(0.0, text=_sync_progress_label(update))

        try:
            result = run_recipe_box_sync(
                db,
                client,
                collection_id=folder.collection_id,
                collection_label=folder.label,
                dry_run=dry_run,
                on_progress=on_progress,
                expected_recipe_count=folder.recipe_count,
            )
        except NytAuthError as exc:
            sync_status.update(label="NYT sync failed", state="error")
            st.error(str(exc))
            return
        except NYTCookingError as exc:
            sync_status.update(label="NYT sync failed", state="error")
            st.error(str(exc))
            return

        summary = result.summary
        if summary.total:
            if folder.recipe_count and folder.recipe_count >= summary.total:
                final_total = folder.recipe_count
            else:
                final_total = summary.total
            progress_bar.progress(
                1.0,
                text=f"{summary.total} / {final_total} recipes",
            )

        if progress_lines:
            with st.expander("Sync log", expanded=False):
                for line in progress_lines:
                    st.write(line)

        outcome_label = format_sync_summary(summary)
        if dry_run:
            outcome_label = outcome_label.replace("Sync complete:", "Preview complete:", 1)
        sync_status.update(label=outcome_label, state="complete")

    if dry_run:
        st.info(
            "Dry run finished — Notion was not updated. "
            "Uncheck dry run and choose Sync to Notion to write new recipes.",
        )
    elif summary.notion_writes:
        invalidate_recipes_after_write(schema_may_change=True)
        outcome_kind, outcome_message = format_notion_sync_outcome_message(summary)
        if outcome_kind == "success":
            st.success(outcome_message)
        elif outcome_kind == "warning":
            st.warning(outcome_message)
        else:
            st.info(outcome_message)
    else:
        _outcome_kind, outcome_message = format_notion_sync_outcome_message(summary)
        st.info(outcome_message)

    if result.review_report:
        with st.expander("Metadata review", expanded=bool(result.review_report.get("created"))):
            st.text(format_metadata_review(result.review_report))
        flagged = sum(
            1 for recipe in result.review_report.get("created", []) if recipe.get("flags")
        )
        if flagged and not dry_run:
            st.caption(
                f"{flagged} recipe(s) flagged — review metadata in Notion or expand "
                "Metadata review above.",
            )


def render_nyt_sync_controls() -> None:
    """NYT recipe-box sync on the Add Recipe tab (folder picker, dry run, sync)."""
    if not _render_nyt_credentials_panel():
        return

    folders = _load_nyt_recipe_box_folders()
    if folders is None:
        return
    if not folders:
        st.info(
            "No NYT recipe-box folders found. Create folders in NYT Cooking, "
            "then choose **Refresh folders**.",
        )
        return

    folder = _render_nyt_folder_picker(folders)
    _render_orphan_filing_panel(folders)
    run_clicked, dry_run = _render_nyt_sync_actions()
    if not run_clicked:
        return

    _execute_nyt_recipe_box_sync(folder=folder, dry_run=dry_run)
