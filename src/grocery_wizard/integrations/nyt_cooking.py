"""NYT Cooking integration — credentials, recipe box, and recipe JSON API."""

from __future__ import annotations

__all__ = [
    "NYTCookingClient",
    "NYTCookingError",
    "NytAuthError",
    "NytCollection",
    "NytCreatedRecipe",
    "NytCredentials",
    "NytNetworkError",
    "NytNotFoundError",
    "NytOrphanFileSummary",
    "NytRecipe",
    "NytRecipeBoxFolder",
    "NytSavedRecipe",
    "NytSyncCancelledError",
    "NytSyncProgressUpdate",
    "NytSyncRunResult",
    "NytSyncSummary",
    "credentials_status",
    "default_orphan_target_folder",
    "file_orphans_into_folder",
    "format_metadata_review",
    "format_orphan_file_summary",
    "format_sync_summary",
    "list_orphan_recipes",
    "list_recipe_box_folders",
    "list_recipe_ids_in_any_folder",
    "load_credentials",
    "load_sync_report",
    "prompt_collection_choice",
    "run_recipe_box_sync",
    "sync_saved_recipes_to_notion",
    "verify_nyt_credentials",
]

import json
import os
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Any

import requests

from src.grocery_wizard.config import NYT_LAST_SYNC_PATH
from src.grocery_wizard.integrations.notion import DEFAULT_NYT_SYNCED_COLUMN

SITE = "https://cooking.nytimes.com"
API_HEADERS = {"x-cooking-api": "cooking-frontend", "accept": "*/*"}
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 30
DEFAULT_PER_PAGE = 48
DEFAULT_NYT_ORPHAN_FOLDER = "1 to make"
NYT_ORPHAN_FOLDER_ENV = "GROCERY_WIZARD_NYT_ORPHAN_FOLDER"
DEFAULT_ORPHAN_FILE_DELAY_SECONDS = 0.25

_REGI_ID_PATTERN = re.compile(r"regi_id=(\d+)", re.IGNORECASE)
_HTML_TAGS = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


class NYTCookingError(Exception):
    """Base error for NYT Cooking access."""


class NytAuthError(NYTCookingError):
    """Credentials are missing or were rejected."""


class NytNotFoundError(NYTCookingError):
    """The requested resource does not exist."""


class NytNetworkError(NYTCookingError):
    """The request could not be completed."""


class NytSyncCancelledError(NYTCookingError):
    """User cancelled an interactive NYT sync step."""


@dataclass(frozen=True, slots=True)
class NytCredentials:
    nyt_s_cookie: str
    regi_id: str


@dataclass(frozen=True, slots=True)
class NytSavedRecipe:
    id: str
    name: str
    url: str
    author: str | None = None


@dataclass(frozen=True, slots=True)
class NytCollection:
    id: str
    name: str
    recipe_count: int = 0


@dataclass(frozen=True, slots=True)
class NytRecipe:
    id: str
    name: str
    url: str
    ingredients: list[str]
    author: str | None = None
    total_time_minutes: float | None = None
    prep_time_minutes: float | None = None
    cook_time_minutes: float | None = None


def parse_regi_id(value: str) -> str:
    """Extract regi_id from a raw id or full regi_cookie string."""
    stripped = value.strip()
    match = _REGI_ID_PATTERN.search(stripped)
    if match:
        return match.group(1)
    return stripped


def load_credentials() -> NytCredentials | None:
    """Load credentials from environment variables."""
    cookie = os.getenv("NYT_S_COOKIE", "").strip()
    regi_id = os.getenv("NYT_REGI_ID", "").strip() or os.getenv("NYT_USER_ID", "").strip()

    if cookie and regi_id:
        return NytCredentials(nyt_s_cookie=cookie, regi_id=regi_id)
    return None


def credentials_status() -> dict[str, Any]:
    """Return whether credentials are configured via environment variables."""
    creds = load_credentials()
    return {
        "configured": creds is not None,
        "regi_id": creds.regi_id if creds else None,
    }


def verify_nyt_credentials(client: NYTCookingClient | None = None) -> None:
    """Raise ``NytAuthError`` when credentials are missing or invalid."""
    if load_credentials() is None:
        raise NytAuthError(
            "NYT Cooking credentials are not configured. Set NYT_S_COOKIE and "
            "NYT_REGI_ID (or NYT_USER_ID) in your environment."
        )
    (client or NYTCookingClient()).verify_auth()


@dataclass(frozen=True, slots=True)
class NytRecipeBoxFolder:
    """One selectable NYT recipe-box folder (or the full box)."""

    collection_id: str | None
    label: str
    recipe_count: int | None = None


_PREFERRED_NYT_FOLDER_LABELS = ("To make", "Favorites")


def _recipe_box_folders_from_collections(
    collections: list[NytCollection],
) -> list[NytRecipeBoxFolder]:
    """Build folder choices with preferred labels first; no full-recipe-box option."""
    preferred_lower = {label.casefold() for label in _PREFERRED_NYT_FOLDER_LABELS}
    picked: list[NytRecipeBoxFolder] = []
    remaining: list[NytRecipeBoxFolder] = []

    for collection in collections:
        folder = NytRecipeBoxFolder(
            collection_id=collection.id,
            label=collection.name,
            recipe_count=collection.recipe_count,
        )
        if collection.name.casefold() in preferred_lower:
            picked.append(folder)
        else:
            remaining.append(folder)

    def _preferred_sort_key(folder: NytRecipeBoxFolder) -> tuple[int, str]:
        try:
            order = next(
                index
                for index, label in enumerate(_PREFERRED_NYT_FOLDER_LABELS)
                if label.casefold() == folder.label.casefold()
            )
        except StopIteration:
            order = len(_PREFERRED_NYT_FOLDER_LABELS)
        return order, folder.label.casefold()

    picked.sort(key=_preferred_sort_key)
    return [*picked, *remaining]


def list_recipe_box_folders(client: NYTCookingClient) -> list[NytRecipeBoxFolder]:
    """Return recipe-box folder choices for UI sync (collections only)."""
    try:
        collections = client.list_collections()
    except NytAuthError:
        raise
    except NYTCookingError:
        return []

    return _recipe_box_folders_from_collections(collections)


class NYTCookingClient:
    """HTTP client for cooking.nytimes.com JSON endpoints."""

    def __init__(
        self,
        credentials: NytCredentials | None = None,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self._credentials = credentials or load_credentials()
        self._http = session or requests.Session()
        self._http.headers["User-Agent"] = USER_AGENT
        if self._credentials:
            self._apply_nyt_cookie()

    def _apply_nyt_cookie(self) -> None:
        """Re-apply NYT-S before each request; NYT may drop it on responses."""
        if self._credentials is None:
            return
        self._http.cookies.set(
            "NYT-S",
            self._credentials.nyt_s_cookie,
            domain=".nytimes.com",
        )

    @property
    def credentials(self) -> NytCredentials | None:
        return self._credentials

    def _require_credentials(self) -> NytCredentials:
        if self._credentials is None:
            raise NytAuthError(
                "NYT Cooking credentials are not configured. Set NYT_S_COOKIE and "
                "NYT_REGI_ID (or NYT_USER_ID) in your environment."
            )
        return self._credentials

    def _get(self, url: str, **kwargs: Any) -> requests.Response:
        self._apply_nyt_cookie()
        try:
            response = self._http.get(url, timeout=REQUEST_TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            raise NytNetworkError(str(exc)) from exc

        if response.status_code in (401, 403):
            raise NytAuthError(
                "NYT Cooking rejected the request — cookie missing, invalid, or expired."
            )
        if response.status_code == 404:
            raise NytNotFoundError(f"Nothing found at {url}.")
        if not response.ok:
            raise NytNetworkError(f"NYT Cooking returned HTTP {response.status_code}.")
        return response

    def _post(self, url: str, **kwargs: Any) -> requests.Response:
        self._apply_nyt_cookie()
        try:
            response = self._http.post(url, timeout=REQUEST_TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            raise NytNetworkError(str(exc)) from exc
        if response.status_code in (401, 403):
            raise NytAuthError(
                "NYT Cooking rejected the request — cookie missing, invalid, or expired."
            )
        return response

    def _delete(self, url: str, **kwargs: Any) -> requests.Response:
        self._apply_nyt_cookie()
        try:
            response = self._http.delete(url, timeout=REQUEST_TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            raise NytNetworkError(str(exc)) from exc
        if response.status_code in (401, 403):
            raise NytAuthError(
                "NYT Cooking rejected the request — cookie missing, invalid, or expired."
            )
        return response

    def _json(self, response: requests.Response, what: str) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise NytNetworkError(f"{what} response was not valid JSON.") from exc
        if not isinstance(data, dict):
            raise NytNetworkError(f"{what} response was not a JSON object.")
        return data

    def verify_auth(self) -> bool:
        """Verify credentials by fetching the first page of the recipe box."""
        self._require_credentials()
        self.list_saved_recipes(page=1, per_page=1)
        return True

    def list_collections(self) -> list[NytCollection]:
        """List recipe-box folders/collections for the signed-in user."""
        self._require_credentials()
        response = self._get(
            f"{SITE}/api/v5/users/me/collections",
            params={"sort": "alphanumeric", "per_page": 9999},
            headers=API_HEADERS,
        )
        payload = self._json(response, "Collections")
        collections = payload.get("collections") or []
        results: list[NytCollection] = []
        for item in collections:
            if not isinstance(item, dict):
                continue
            results.append(
                NytCollection(
                    id=str(item.get("id", "")),
                    name=str(item.get("name", "")),
                    recipe_count=int(item.get("collectables_count") or 0),
                )
            )
        return results

    def find_collection_by_name(self, name: str) -> NytCollection | None:
        """Case-insensitive match on folder/collection name."""
        target = name.strip().casefold()
        for collection in self.list_collections():
            if collection.name.casefold() == target:
                return collection
        return None

    def create_collection(self, name: str) -> NytCollection:
        """Create a recipe-box folder (collection)."""
        self._require_credentials()
        response = self._post(
            f"{SITE}/api/v5/users/me/collections",
            json={"name": name},
            headers={**API_HEADERS, "Content-Type": "application/json"},
        )
        if response.status_code != 201:
            raise NytNetworkError(
                f"NYT Cooking returned HTTP {response.status_code} creating collection."
            )
        payload = self._json(response, "Collection")
        return NytCollection(
            id=str(payload.get("id", "")),
            name=str(payload.get("name", name)),
            recipe_count=0,
        )

    def ensure_collection(self, name: str) -> NytCollection:
        """Return existing folder by name or create it."""
        existing = self.find_collection_by_name(name)
        if existing is not None:
            return existing
        return self.create_collection(name)

    def collection_recipe_ids(self, collection_id: str | int) -> list[str]:
        """Recipe ids in a folder via GET /api/v5/collections/{id}."""
        self._require_credentials()
        response = self._get(
            f"{SITE}/api/v5/collections/{int(collection_id)}",
            headers=API_HEADERS,
        )
        col = self._json(response, "Collection detail").get("collection") or {}
        ids: list[str] = []
        for item in col.get("collectables") or []:
            if not isinstance(item, dict):
                continue
            recipe_id = item.get("recipe_id")
            item_type = str(item.get("type") or "")
            if recipe_id is not None and item_type in ("", "recipe"):
                ids.append(str(recipe_id))
        return ids

    def list_saved_recipes(
        self,
        *,
        page: int = 1,
        per_page: int = DEFAULT_PER_PAGE,
        collection_id: str | None = None,
    ) -> dict[str, Any]:
        """Return one page of saved recipes from the recipe box."""
        self._require_credentials()
        params: dict[str, str | int] = {
            "q": "",
            "page": page,
            "per_page": per_page,
            "sort": "rating",
        }
        if collection_id:
            params["collection_id"] = collection_id

        response = self._get(
            f"{SITE}/api/v2/users/me/search/recipe_box_search",
            params=params,
            headers=API_HEADERS,
        )
        return self._json(response, "Recipe box")

    def iter_all_saved_recipes(
        self,
        *,
        collection_id: str | None = None,
        per_page: int = DEFAULT_PER_PAGE,
    ) -> Iterator[NytSavedRecipe]:
        """Yield every saved recipe, paging through the recipe box."""
        seen: set[str] = set()
        page = 1
        while True:
            payload = self.list_saved_recipes(
                page=page,
                per_page=per_page,
                collection_id=collection_id,
            )
            items = payload.get("collectables") or []
            if not items:
                break
            for item in items:
                if not isinstance(item, dict):
                    continue
                rid = str(item.get("id", ""))
                if not rid or rid in seen:
                    continue
                seen.add(rid)
                yield NytSavedRecipe(
                    id=rid,
                    name=str(item.get("name", "")),
                    url=_absolute_url(str(item.get("url", ""))),
                    author=item.get("byline"),
                )

            meta = payload.get("meta") or {}
            total_pages = int(meta.get("total_pages") or 0)
            if total_pages and page >= total_pages:
                break
            total = int(payload.get("collectables_count") or 0)
            if total and page * per_page >= total:
                break
            page += 1

    def save_recipe(self, recipe_id: int | str) -> int:
        """Save an NYT recipe to the recipe box. Returns HTTP 201 or 409."""
        creds = self._require_credentials()
        response = self._post(
            f"{SITE}/api/v2/users/{creds.regi_id}/collectables/recipe",
            json={"id": int(recipe_id)},
            headers={**API_HEADERS, "Content-Type": "application/json"},
        )
        if response.status_code not in (201, 409):
            raise NytNetworkError(
                f"NYT Cooking returned HTTP {response.status_code} saving recipe."
            )
        return response.status_code

    def unsave_recipe(self, recipe_id: int | str) -> int:
        """Remove a recipe from the recipe box."""
        creds = self._require_credentials()
        response = self._delete(
            f"{SITE}/api/v2/users/{creds.regi_id}/collectables/recipe/{int(recipe_id)}",
            headers=API_HEADERS,
        )
        if response.status_code not in (204, 404):
            raise NytNetworkError(
                f"NYT Cooking returned HTTP {response.status_code} unsaving recipe."
            )
        return response.status_code

    def add_to_collection(self, collection_id: str | int, recipe_id: int | str) -> int:
        """Add a saved recipe to a folder. Returns HTTP 201 or 409."""
        self._require_credentials()
        response = self._post(
            f"{SITE}/api/v5/collections/{int(collection_id)}/collectables",
            json={"recipe_id": int(recipe_id)},
            headers={**API_HEADERS, "Content-Type": "application/json"},
        )
        if response.status_code not in (201, 409):
            raise NytNetworkError(
                f"NYT Cooking returned HTTP {response.status_code} adding to collection."
            )
        return response.status_code

    def save_recipe_to_collection(
        self,
        collection_id: str | int,
        recipe_id: int | str,
    ) -> tuple[int, int]:
        """Save to recipe box, then add to folder."""
        save_status = self.save_recipe(recipe_id)
        folder_status = self.add_to_collection(collection_id, recipe_id)
        return save_status, folder_status

    def get_recipe(self, recipe_id: str) -> NytRecipe:
        """Fetch full recipe details from the JSON recipe endpoint."""
        response = self._get(
            f"{SITE}/api/v2/recipes/{recipe_id}",
            headers=API_HEADERS,
        )
        payload = self._json(response, "Recipe")
        return _parse_recipe_payload(payload)

    def get_recipe_by_url(self, url: str) -> NytRecipe:
        """Fetch recipe details using an id parsed from a cooking.nytimes.com URL."""
        recipe_id = _recipe_id_from_url(url)
        if not recipe_id:
            raise NytNotFoundError(f"Could not parse NYT recipe id from URL: {url}")
        recipe = self.get_recipe(recipe_id)
        if recipe.url:
            return recipe
        return NytRecipe(
            id=recipe.id,
            name=recipe.name,
            url=url,
            ingredients=recipe.ingredients,
            author=recipe.author,
        )


def default_orphan_target_folder() -> str:
    """Default NYT folder for filing unfiled recipes (Streamlit + scripts)."""
    custom = os.getenv(NYT_ORPHAN_FOLDER_ENV, "").strip()
    if custom:
        return custom
    return DEFAULT_NYT_ORPHAN_FOLDER


def list_recipe_ids_in_any_folder(client: NYTCookingClient) -> set[str]:
    """Recipe ids that appear in at least one recipe-box folder."""
    ids: set[str] = set()
    for collection in client.list_collections():
        ids.update(client.collection_recipe_ids(collection.id))
    return ids


def list_orphan_recipes(client: NYTCookingClient) -> list[NytSavedRecipe]:
    """Saved recipes in the recipe box that are not in any folder."""
    in_folders = list_recipe_ids_in_any_folder(client)
    return [recipe for recipe in client.iter_all_saved_recipes() if recipe.id not in in_folders]


@dataclass
class NytOrphanFileSummary:
    orphans_total: int = 0
    added: int = 0
    already_in_folder: int = 0
    failed: int = 0
    dry_run: bool = False
    target_folder: str = ""
    failed_ids: list[str] = field(default_factory=list)


def format_orphan_file_summary(summary: NytOrphanFileSummary) -> str:
    if summary.dry_run:
        return (
            f"Preview: {summary.orphans_total} unfiled recipe(s) would be added to "
            f"'{summary.target_folder}' on NYT Cooking."
        )
    return (
        f"Filing complete: added {summary.added}, already in folder {summary.already_in_folder}, "
        f"failed {summary.failed} (target '{summary.target_folder}')."
    )


def file_orphans_into_folder(
    client: NYTCookingClient,
    *,
    folder_name: str | None = None,
    dry_run: bool = False,
    delay_seconds: float = DEFAULT_ORPHAN_FILE_DELAY_SECONDS,
    on_progress: NytSyncProgressCallback | None = None,
) -> NytOrphanFileSummary:
    """Add unfiled saved recipes to a folder (does not remove other folder memberships)."""
    target = (folder_name or default_orphan_target_folder()).strip()
    orphans = list_orphan_recipes(client)
    summary = NytOrphanFileSummary(
        orphans_total=len(orphans),
        dry_run=dry_run,
        target_folder=target,
    )
    if dry_run or not orphans:
        _notify_sync_progress(
            on_progress,
            format_orphan_file_summary(summary),
            processed=0,
            total=len(orphans) or None,
        )
        return summary

    folder = client.ensure_collection(target)
    total = len(orphans)
    for index, recipe in enumerate(orphans, start=1):
        try:
            status = client.add_to_collection(folder.id, recipe.id)
            if status == 201:
                summary.added += 1
                message = f"Added: {recipe.name}"
            else:
                summary.already_in_folder += 1
                message = f"Already in folder: {recipe.name}"
        except NYTCookingError:
            summary.failed += 1
            summary.failed_ids.append(recipe.id)
            message = f"Failed: {recipe.name}"
        _notify_sync_progress(on_progress, message, processed=index, total=total)
        if delay_seconds > 0 and index < total:
            time.sleep(delay_seconds)

    _notify_sync_progress(
        on_progress,
        format_orphan_file_summary(summary),
        processed=total,
        total=total,
    )
    return summary


def _recipe_box_total_count(client: NYTCookingClient) -> int | None:
    try:
        payload = client.list_saved_recipes(page=1, per_page=1)
    except NYTCookingError:
        return None
    return int(payload.get("collectables_count") or 0)


def prompt_collection_choice(
    client: NYTCookingClient,
    *,
    prompt_fn: Callable[[str], str] = input,
    on_info: Callable[[str], None] | None = None,
) -> tuple[str | None, str]:
    """Interactively pick a recipe-box collection.

    Returns ``(collection_id, label)``.
    Raises ``NytSyncCancelledError`` when the user declines or enters an invalid choice.
    """
    info = on_info or (lambda _message: None)

    collections: list[NytCollection] = []
    try:
        collections = client.list_collections()
    except NytAuthError:
        raise
    except NYTCookingError as exc:
        info(f"Could not load recipe-box folders ({exc}).")
        raise NytSyncCancelledError("No recipe-box folders available.") from exc

    if not collections:
        info("No recipe-box folders found in your NYT Cooking account.")
        raise NytSyncCancelledError("No recipe-box folders available.")

    folders = _recipe_box_folders_from_collections(collections)
    options: list[tuple[str, str, int | None]] = [
        (folder.collection_id or "", folder.label, folder.recipe_count) for folder in folders
    ]

    info("Choose a recipe-box folder to sync:")
    for index, (_collection_id, label, count) in enumerate(options, start=1):
        count_note = f" ({count} recipes)" if count is not None else ""
        info(f"  {index}. {label}{count_note}")

    while True:
        choice = prompt_fn("Folder [#]: ").strip()
        if not choice:
            raise NytSyncCancelledError("Sync cancelled.")
        try:
            picked = int(choice)
        except ValueError:
            info("Enter a number from the list.")
            continue
        if 1 <= picked <= len(options):
            collection_id, label, _count = options[picked - 1]
            return collection_id, label
        info(f"Enter a number between 1 and {len(options)}.")


@dataclass
class NytCreatedRecipe:
    page_id: str
    name: str
    url: str
    metadata: dict[str, Any]
    flags: list[str] = field(default_factory=list)
    ingredient_count: int = 0


@dataclass
class NytSyncSummary:
    total: int = 0
    skipped_existing: int = 0
    updated_existing: int = 0
    created: int = 0
    failed: int = 0
    dry_run: int = 0
    collection_label: str | None = None
    created_recipes: list[NytCreatedRecipe] = field(default_factory=list)

    @property
    def notion_writes(self) -> int:
        return self.created + self.updated_existing


@dataclass(frozen=True, slots=True)
class NytSyncProgressUpdate:
    """Progress event for NYT recipe-box sync (UI bar + optional log line)."""

    message: str
    processed: int = 0
    total: int | None = None


NytSyncProgressCallback = Callable[[NytSyncProgressUpdate], None]


def _notify_sync_progress(
    on_progress: NytSyncProgressCallback | None,
    message: str,
    *,
    processed: int = 0,
    total: int | None = None,
) -> None:
    if on_progress is not None:
        on_progress(NytSyncProgressUpdate(message=message, processed=processed, total=total))


def _expected_recipe_count_for_sync(
    client: NYTCookingClient,
    collection_id: str | None,
    explicit: int | None,
) -> int | None:
    if explicit is not None and explicit > 0:
        return explicit
    if collection_id:
        try:
            for collection in client.list_collections():
                if collection.id == collection_id and collection.recipe_count > 0:
                    return collection.recipe_count
        except NYTCookingError:
            return None
        return None
    return _recipe_box_total_count(client)


def _resolve_sync_collection(
    client: NYTCookingClient,
    *,
    collection_name: str | None,
    collection_id: str | None,
    collection_label: str | None,
    on_progress: NytSyncProgressCallback | None,
) -> tuple[str | None, str | None]:
    resolved_id = collection_id
    resolved_label = collection_label

    if resolved_id is None and collection_name:
        collection = client.find_collection_by_name(collection_name)
        if collection is None:
            _notify_sync_progress(
                on_progress,
                f"Collection '{collection_name}' not found; syncing full recipe box.",
            )
        else:
            resolved_id = collection.id
            resolved_label = collection.name
            _notify_sync_progress(
                on_progress,
                f"Syncing collection: {collection.name} ({collection.recipe_count} recipes)",
            )
    elif resolved_label:
        if resolved_id is not None:
            _notify_sync_progress(on_progress, f"Syncing collection: {resolved_label}")
        else:
            total = _recipe_box_total_count(client)
            count_note = f" ({total} recipes)" if total is not None else ""
            _notify_sync_progress(on_progress, f"Syncing: {resolved_label}{count_note}")

    return resolved_id, resolved_label


def _report_sync_nyt_checkbox_column(
    db: Any,
    on_progress: NytSyncProgressCallback | None,
    *,
    recipe_total: int | None,
) -> None:
    nyt_column = db.nyt_synced_column_name()
    if nyt_column:
        _notify_sync_progress(
            on_progress,
            f"Marking synced recipes with checkbox: {nyt_column}",
            processed=0,
            total=recipe_total,
        )
    else:
        _notify_sync_progress(
            on_progress,
            f"Warning: checkbox column '{DEFAULT_NYT_SYNCED_COLUMN}' "
            "not found in Notion — add it to tag NYT imports.",
            processed=0,
            total=recipe_total,
        )


def _process_saved_recipe_in_sync(
    db: Any,
    client: NYTCookingClient,
    saved: NytSavedRecipe,
    summary: NytSyncSummary,
    *,
    dry_run: bool,
    no_confirm: bool,
    confirm: Callable[[str], bool] | None,
    on_progress: NytSyncProgressCallback | None,
    recipe_total: int | None,
) -> None:
    # Lazy import: add_recipe pulls NYT helpers; keep sync entry import-light.
    from src.grocery_wizard.recipes.add_recipe import add_prefetched_recipes

    summary.total += 1
    processed = summary.total
    url = saved.url
    if not url:
        summary.failed += 1
        _notify_sync_progress(
            on_progress,
            f"Skipping recipe without URL: {saved.name}",
            processed=processed,
            total=recipe_total,
        )
        return

    existing = db.find_by_link(url)
    if existing:
        summary.skipped_existing += 1
        nyt_column = db.nyt_synced_column_name()
        if not dry_run and nyt_column and existing.properties.get(nyt_column) is not True:
            db.update_recipe(existing.page_id, {nyt_column: True})
            summary.updated_existing += 1
            _notify_sync_progress(
                on_progress,
                f"Tagged existing (link match): {existing.name}",
                processed=processed,
                total=recipe_total,
            )
        else:
            _notify_sync_progress(
                on_progress,
                f"Skip (link already in Notion): {existing.name}",
                processed=processed,
                total=recipe_total,
            )
        return

    total_minutes, ingredients = _fetch_nyt_recipe_for_sync(client, saved.id, saved.url)

    if dry_run:
        summary.dry_run += 1
        metadata = _metadata_for_recipe(
            db,
            saved.name,
            url,
            mark_nyt_synced=True,
            total_minutes=total_minutes,
            ingredients=ingredients,
        )
        flags = flag_metadata_issues(saved.name, metadata)
        ingredient_count = len(ingredients)
        summary.created_recipes.append(
            NytCreatedRecipe(
                page_id="",
                name=saved.name,
                url=url,
                metadata=metadata,
                flags=flags,
                ingredient_count=ingredient_count,
            )
        )
        if ingredient_count:
            would_add_message = f"Would add: {saved.name} ({ingredient_count} ingredients)"
        else:
            would_add_message = f"Would add: {saved.name} (no ingredients found)"
        _notify_sync_progress(
            on_progress,
            would_add_message,
            processed=processed,
            total=recipe_total,
        )
        return

    results = add_prefetched_recipes(
        db,
        [(saved.name, url, ingredients, total_minutes)],
        confirm=confirm,
        no_confirm=no_confirm,
        include_ingredients=True,
        mark_nyt_synced=True,
    )
    if results:
        summary.created += 1
        result = results[0]
        metadata = _metadata_from_field_values(db, result.field_values)
        flags = flag_metadata_issues(result.name, metadata)
        entry = NytCreatedRecipe(
            page_id=result.page_id,
            name=result.name,
            url=result.url,
            metadata=metadata,
            flags=flags,
            ingredient_count=len(ingredients),
        )
        summary.created_recipes.append(entry)
        flag_note = f" [{'; '.join(flags)}]" if flags else ""
        _notify_sync_progress(
            on_progress,
            f"Created: {result.name}{flag_note}",
            processed=processed,
            total=recipe_total,
        )
    else:
        _notify_sync_progress(
            on_progress,
            f"Skipped: {saved.name}",
            processed=processed,
            total=recipe_total,
        )


def sync_saved_recipes_to_notion(
    db: Any,
    client: NYTCookingClient,
    *,
    collection_name: str | None = None,
    collection_id: str | None = None,
    collection_label: str | None = None,
    dry_run: bool = False,
    no_confirm: bool = True,
    confirm: Callable[[str], bool] | None = None,
    on_progress: NytSyncProgressCallback | None = None,
    expected_recipe_count: int | None = None,
) -> NytSyncSummary:
    """Sync NYT saved recipes to Notion, skipping duplicates by link."""
    resolved_id, resolved_label = _resolve_sync_collection(
        client,
        collection_name=collection_name,
        collection_id=collection_id,
        collection_label=collection_label,
        on_progress=on_progress,
    )

    recipe_total = _expected_recipe_count_for_sync(client, resolved_id, expected_recipe_count)

    summary = NytSyncSummary(collection_label=resolved_label)
    _report_sync_nyt_checkbox_column(db, on_progress, recipe_total=recipe_total)

    for saved in client.iter_all_saved_recipes(collection_id=resolved_id):
        _process_saved_recipe_in_sync(
            db,
            client,
            saved,
            summary,
            dry_run=dry_run,
            no_confirm=no_confirm,
            confirm=confirm,
            on_progress=on_progress,
            recipe_total=recipe_total,
        )

    if on_progress is not None and summary.total:
        if recipe_total and recipe_total >= summary.total:
            effective_total = recipe_total
        else:
            effective_total = summary.total
        _notify_sync_progress(
            on_progress,
            f"Finished processing {summary.total} recipe(s).",
            processed=summary.total,
            total=effective_total,
        )

    return summary


@dataclass(frozen=True, slots=True)
class NytSyncRunResult:
    summary: NytSyncSummary
    review_report: dict[str, Any] | None = None


def _sync_report_from_summary(summary: NytSyncSummary) -> dict[str, Any]:
    return {
        "synced_at": datetime.now(UTC).isoformat(),
        "collection": summary.collection_label,
        "created": [
            {
                "page_id": recipe.page_id,
                "name": recipe.name,
                "url": recipe.url,
                "metadata": recipe.metadata,
                "flags": recipe.flags,
                "ingredient_count": recipe.ingredient_count,
            }
            for recipe in summary.created_recipes
        ],
    }


def format_sync_summary(summary: NytSyncSummary) -> str:
    """One-line counts after a sync or dry run."""
    return (
        f"Sync complete: {summary.total} in NYT folder, "
        f"{summary.skipped_existing} matched existing Notion link(s), "
        f"{summary.created} new page(s) created, "
        f"{summary.updated_existing} existing page(s) tagged, "
        f"{summary.dry_run} would add, "
        f"{summary.failed} failed."
    )


def format_notion_sync_outcome_message(summary: NytSyncSummary) -> tuple[str, str]:
    """Return (streamlit_message_kind, user-facing sentence) after a live sync."""
    if summary.created and summary.updated_existing:
        return (
            "success",
            (
                f"Notion updated — added {summary.created} new recipe(s) and tagged "
                f"{summary.updated_existing} existing match(es) with the NYT sync checkbox."
            ),
        )
    if summary.created:
        return ("success", f"Notion updated — added {summary.created} new recipe(s).")
    if summary.updated_existing:
        return (
            "success",
            (
                f"Notion updated — tagged {summary.updated_existing} existing recipe(s) "
                f"(link already in Notion; no new pages)."
            ),
        )
    if summary.skipped_existing:
        return (
            "info",
            (
                f"No Notion changes — all {summary.skipped_existing} recipe(s) already had a "
                "matching link and NYT sync checkbox. New NYT saves only create Notion pages when "
                "the cooking.nytimes.com URL is not already on a card."
            ),
        )
    if summary.failed:
        return ("warning", f"Sync finished with {summary.failed} failure(s) and no new pages.")
    return ("info", "Sync finished — no recipes were processed.")


def run_recipe_box_sync(
    db: Any,
    client: NYTCookingClient,
    *,
    collection_name: str | None = None,
    collection_id: str | None = None,
    collection_label: str | None = None,
    dry_run: bool = False,
    no_confirm: bool = True,
    save_report: bool = True,
    on_progress: NytSyncProgressCallback | None = None,
    expected_recipe_count: int | None = None,
) -> NytSyncRunResult:
    """Run NYT recipe-box sync and optionally persist the metadata review report."""
    summary = sync_saved_recipes_to_notion(
        db,
        client,
        collection_name=collection_name,
        collection_id=collection_id,
        collection_label=collection_label,
        dry_run=dry_run,
        no_confirm=no_confirm,
        on_progress=on_progress,
        expected_recipe_count=expected_recipe_count,
    )
    review_report: dict[str, Any] | None = None
    if summary.created_recipes:
        review_report = _sync_report_from_summary(summary)
    if save_report and not dry_run and summary.created_recipes:
        save_sync_report(summary)
    return NytSyncRunResult(summary=summary, review_report=review_report)


_TITLE_MEAL_HINTS: dict[str, list[str]] = {
    "Dessert": ["cake", "cookie", "brownie", "pie", "pudding", "tart", "muffin"],
    "Breakfast": ["pancake", "waffle", "oatmeal", "frittata", "omelet", "omelette"],
    "Drink": ["smoothie", "cocktail", "lemonade", "limeade", "mocktail"],
    "Lunch": ["sandwich"],
    "Snack/Side": ["salad"],
}


def _metadata_for_recipe(
    db: Any,
    title: str,
    url: str,
    *,
    mark_nyt_synced: bool = False,
    total_minutes: float | None = None,
    ingredients: list[str] | None = None,
) -> dict[str, Any]:
    # Lazy import: recipe classify stack is heavy; used on sync/reclassify paths only.
    from src.grocery_wizard.recipes.classify import classify_recipe
    from src.grocery_wizard.recipes.recipe_meal_plan_stats import filter_columns_for_recipe_classify
    from src.grocery_wizard.recipes.weeknight import DEFAULT_WEEKNIGHT_COLUMN

    filter_columns = filter_columns_for_recipe_classify(db.schema.filter_columns)
    weeknight_column = (
        DEFAULT_WEEKNIGHT_COLUMN if DEFAULT_WEEKNIGHT_COLUMN in db.schema.all_columns else None
    )
    inferred = classify_recipe(
        title,
        ingredients or [],
        filter_columns,
        total_minutes=total_minutes,
        weeknight_column=weeknight_column,
    )
    metadata: dict[str, Any] = {
        db.schema.name_column: title,
        db.schema.link_column: url,
    }
    metadata.update(inferred)
    if mark_nyt_synced:
        nyt_column = db.nyt_synced_column_name()
        if nyt_column:
            metadata[nyt_column] = True
    return _metadata_from_field_values(db, metadata)


def _metadata_from_field_values(db: Any, field_values: dict[str, Any]) -> dict[str, Any]:
    schema = db.schema
    skip = {schema.name_column, schema.link_column}
    if schema.ingredients_column:
        skip.add(schema.ingredients_column)
    if schema.instructions_column:
        skip.add(schema.instructions_column)
    return {
        key: value
        for key, value in field_values.items()
        if key not in skip and value not in (None, "", [])
    }


def flag_metadata_issues(name: str, metadata: dict[str, Any]) -> list[str]:
    """Return human-readable flags when title and assigned metadata look inconsistent."""
    title = name.lower()
    meal = metadata.get("Meal")
    if isinstance(meal, str):
        for suggested_meal, keywords in _TITLE_MEAL_HINTS.items():
            if any(keyword in title for keyword in keywords) and meal != suggested_meal:
                return [f"title suggests {suggested_meal} but Meal={meal}"]
    missing = [column for column, value in metadata.items() if value in (None, "", [])]
    if len(missing) >= 2:
        return [f"missing metadata: {', '.join(sorted(missing))}"]
    return []


def save_sync_report(summary: NytSyncSummary, path: Path = NYT_LAST_SYNC_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "synced_at": datetime.now(UTC).isoformat(),
        "collection": summary.collection_label,
        "created": [asdict(recipe) for recipe in summary.created_recipes],
        "counts": {
            "total": summary.total,
            "skipped_existing": summary.skipped_existing,
            "updated_existing": summary.updated_existing,
            "created": summary.created,
            "dry_run": summary.dry_run,
            "failed": summary.failed,
        },
    }
    path.write_text(json.dumps(payload, indent=2))


def load_sync_report(path: Path = NYT_LAST_SYNC_PATH) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def format_metadata_review(report: dict[str, Any]) -> str:
    lines: list[str] = []
    collection = report.get("collection") or "recipe box"
    lines.append(f"NYT sync review — {collection}")
    lines.append(f"Synced at: {report.get('synced_at', 'unknown')}")
    lines.append("")

    created = report.get("created", [])
    if not created:
        lines.append("No recipes to review.")
        return "\n".join(lines)

    for index, recipe in enumerate(created, start=1):
        name = recipe.get("name", "?")
        ingredient_count = recipe.get("ingredient_count")
        if ingredient_count is not None and ingredient_count > 0:
            lines.append(f"{index}. {name} ({ingredient_count} ingredients)")
        elif ingredient_count == 0:
            lines.append(f"{index}. {name} (no ingredients)")
        else:
            lines.append(f"{index}. {name}")
        metadata = recipe.get("metadata", {})
        if metadata:
            for key, value in sorted(metadata.items()):
                lines.append(f"   {key}: {value}")
        flags = recipe.get("flags") or []
        if flags:
            lines.append(f"   ⚠ {flags[0]}")
        lines.append("")

    flagged = sum(1 for recipe in created if recipe.get("flags"))
    lines.append(f"{len(created)} recipe(s), {flagged} flagged for review.")
    return "\n".join(lines)


@dataclass
class NytReclassifyChange:
    page_id: str
    name: str
    field: str
    old_value: Any
    new_value: Any


@dataclass
class NytReclassifySummary:
    total: int = 0
    meal_changes: int = 0
    weeknight_set: int = 0
    weeknight_cleared: int = 0
    dinner_category_cleared: int = 0
    unchanged: int = 0
    api_failures: int = 0
    changes: list[NytReclassifyChange] = field(default_factory=list)


def _require_nyt_synced_column(db: Any) -> str:
    nyt_column = db.nyt_synced_column_name()
    if not nyt_column:
        raise NYTCookingError(
            f"NYT synced checkbox column not found. Add '{DEFAULT_NYT_SYNCED_COLUMN}' to Notion."
        )
    return nyt_column


def _reclassify_ingredient_lines(recipe: Any) -> list[str]:
    from src.grocery_wizard.ingredients.sync import parse_ingredients_text

    raw = (recipe.ingredients or "").replace("<br />", "\n").replace("<br>", "\n")
    lines, _ = parse_ingredients_text(raw)
    if lines:
        return lines
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _dinner_category_column_name(schema: Any) -> str:
    from src.grocery_wizard.recipes.recipe_schema_columns import (
        dinner_lunch_category_column_from_schema,
    )

    return dinner_lunch_category_column_from_schema(schema) or ""


def _weeknight_column_for_reclassify(db: Any) -> str:
    # Lazy import: weeknight defaults live in recipes package (avoid import at module load).
    from src.grocery_wizard.recipes.weeknight import DEFAULT_WEEKNIGHT_COLUMN

    weeknight_column = DEFAULT_WEEKNIGHT_COLUMN
    if weeknight_column not in db.schema.all_columns:
        return ""
    return weeknight_column


def _fetch_reclassify_total_minutes(
    client: NYTCookingClient,
    recipe: Any,
    summary: NytReclassifySummary,
    *,
    on_progress: NytSyncProgressCallback | None,
) -> float | None:
    recipe_id = _recipe_id_from_url(recipe.link or "")
    if not recipe_id:
        return None
    try:
        nyt_recipe = client.get_recipe(recipe_id)
    except NYTCookingError:
        summary.api_failures += 1
        from src.grocery_wizard.recipes.recipe_maintenance import format_recipe_progress_line

        _notify_sync_progress(
            on_progress,
            format_recipe_progress_line("Could not fetch NYT timing for: ", recipe),
        )
        return None
    else:
        return nyt_recipe.total_time_minutes


def _build_reclassify_field_updates(
    recipe: Any,
    *,
    schema: Any,
    new_meal: Any,
    old_meal: Any,
    total_minutes: float | None,
    weeknight_column: str,
    dinner_category_column: str,
    summary: NytReclassifySummary,
) -> dict[str, Any]:
    # Lazy import: weeknight helper used only during NYT reclassify updates.
    from src.grocery_wizard.recipes.classify import MEALS_WITHOUT_DINNER_CATEGORY
    from src.grocery_wizard.recipes.recipe_maintenance import (
        is_blank_metadata_value,
        normalize_meal_values,
    )
    from src.grocery_wizard.recipes.weeknight import is_weeknight_friendly

    title = recipe.name
    fields: dict[str, Any] = {}

    if new_meal and normalize_meal_values(new_meal) != normalize_meal_values(old_meal):
        fields["Meal"] = new_meal
        summary.meal_changes += 1
        summary.changes.append(
            NytReclassifyChange(
                page_id=recipe.page_id,
                name=title,
                field="Meal",
                old_value=old_meal,
                new_value=new_meal,
            )
        )

    effective_meal = fields.get("Meal", old_meal)
    if weeknight_column:
        new_weeknight = is_weeknight_friendly(
            title,
            meal=effective_meal,
            total_minutes=total_minutes,
        )
        old_weeknight = bool(recipe.properties.get(weeknight_column))
        if new_weeknight != old_weeknight:
            fields[weeknight_column] = new_weeknight
            if new_weeknight:
                summary.weeknight_set += 1
            else:
                summary.weeknight_cleared += 1
            summary.changes.append(
                NytReclassifyChange(
                    page_id=recipe.page_id,
                    name=title,
                    field=weeknight_column,
                    old_value=old_weeknight,
                    new_value=new_weeknight,
                )
            )

    effective_meal = fields.get("Meal", old_meal)
    meals = normalize_meal_values(effective_meal)
    if dinner_category_column and meals & MEALS_WITHOUT_DINNER_CATEGORY:
        from src.grocery_wizard.recipes.recipe_schema_columns import (
            dinner_lunch_category_na_option,
            is_dinner_lunch_category_na_only,
        )

        col = schema.all_columns.get(dinner_category_column)
        na_label = dinner_lunch_category_na_option(col.options) if col else None
        current_dinner_category = recipe.properties.get(dinner_category_column)
        needs_na = na_label and (
            is_blank_metadata_value("multi_select", current_dinner_category)
            or not is_dinner_lunch_category_na_only(current_dinner_category, na_label=na_label)
        )
        if needs_na:
            fields[dinner_category_column] = [na_label]
            summary.dinner_category_cleared += 1
            summary.changes.append(
                NytReclassifyChange(
                    page_id=recipe.page_id,
                    name=title,
                    field=dinner_category_column,
                    old_value=current_dinner_category,
                    new_value=[na_label],
                )
            )

    return fields


def _apply_reclassify_recipe_updates(
    db: Any,
    recipe: Any,
    fields: dict[str, Any],
    summary: NytReclassifySummary,
    *,
    dry_run: bool,
    on_progress: NytSyncProgressCallback | None,
) -> None:
    if fields:
        from src.grocery_wizard.recipes.recipe_maintenance import format_recipe_progress_line

        detail = ", ".join(f"{key}={value}" for key, value in fields.items())
        _notify_sync_progress(
            on_progress,
            format_recipe_progress_line("Update: ", recipe, suffix=f" ({detail})"),
            processed=summary.total,
        )
        if not dry_run:
            db.update_recipe(recipe.page_id, fields)
    else:
        summary.unchanged += 1


def reclassify_nyt_synced_recipes(
    db: Any,
    client: NYTCookingClient,
    *,
    dry_run: bool = False,
    on_progress: NytSyncProgressCallback | None = None,
) -> NytReclassifySummary:
    """Re-run Meal and Weeknight Friendly for NYT-synced recipes in Notion."""
    # Lazy import: classify stack (see ``_metadata_for_recipe``).
    from src.grocery_wizard.recipes.classify import classify_recipe
    from src.grocery_wizard.recipes.recipe_meal_plan_stats import filter_columns_for_recipe_classify

    nyt_column = _require_nyt_synced_column(db)
    weeknight_column = _weeknight_column_for_reclassify(db)
    filter_columns = filter_columns_for_recipe_classify(db.schema.filter_columns)
    dinner_category_column = _dinner_category_column_name(db.schema)
    summary = NytReclassifySummary()

    for recipe in db.query_recipes():
        if not recipe.properties.get(nyt_column):
            continue

        summary.total += 1
        title = recipe.name
        inferred = classify_recipe(
            title,
            _reclassify_ingredient_lines(recipe),
            filter_columns,
        )
        new_meal = inferred.get("Meal")
        old_meal = recipe.properties.get("Meal")

        total_minutes = _fetch_reclassify_total_minutes(
            client, recipe, summary, on_progress=on_progress
        )
        fields = _build_reclassify_field_updates(
            recipe,
            schema=db.schema,
            new_meal=new_meal,
            old_meal=old_meal,
            total_minutes=total_minutes,
            weeknight_column=weeknight_column,
            dinner_category_column=dinner_category_column,
            summary=summary,
        )
        _apply_reclassify_recipe_updates(
            db,
            recipe,
            fields,
            summary,
            dry_run=dry_run,
            on_progress=on_progress,
        )

    return summary


def _format_reclassify_value(value: Any) -> str:
    """Stable display for old/new values in grouped reclassify summaries."""
    if isinstance(value, bool):
        return str(value)
    if value is None:
        return "(empty)"
    if isinstance(value, (list, tuple)):
        return repr(list(value))
    if isinstance(value, str) and not value.strip():
        return "(empty)"
    if isinstance(value, str):
        return value
    return repr(value)


def _reclassify_field_rank(field: str) -> tuple[int, str]:
    from src.grocery_wizard.recipes.weeknight import DEFAULT_WEEKNIGHT_COLUMN

    if field == "Meal":
        return (0, field)
    if field == DEFAULT_WEEKNIGHT_COLUMN or "Weeknight" in field:
        return (1, field)
    if "Category" in field:
        return (2, field)
    return (3, field)


def reclassify_summary_updated_count(summary: NytReclassifySummary) -> int:
    """Recipes with at least one metadata change (unique Notion page ids)."""
    if not summary.changes:
        return 0
    return len({change.page_id for change in summary.changes if change.page_id})


def format_reclassify_summary_headline(summary: NytReclassifySummary) -> str:
    """One-line counts after NYT reclassify (progress bar + status label)."""
    updated = reclassify_summary_updated_count(summary)
    headline = (
        f"NYT reclassify — {summary.total} recipes · {updated} updated · "
        f"{summary.unchanged} unchanged"
    )
    subparts: list[str] = []
    if summary.meal_changes:
        subparts.append(f"meal {summary.meal_changes}")
    if summary.weeknight_set:
        subparts.append(f"weeknight set {summary.weeknight_set}")
    if summary.weeknight_cleared:
        subparts.append(f"weeknight cleared {summary.weeknight_cleared}")
    if summary.dinner_category_cleared:
        subparts.append(f"category {summary.dinner_category_cleared}")
    if summary.api_failures:
        subparts.append(f"NYT timing failures {summary.api_failures}")
    if subparts:
        headline += f" ({' · '.join(subparts)})"
    return headline


def format_reclassify_summary(summary: NytReclassifySummary) -> str:
    """Grouped Markdown summary: headline, then field groups with Notion recipe links."""
    lines = [format_reclassify_summary_headline(summary)]
    if not summary.changes:
        return lines[0]

    from src.grocery_wizard.integrations.notion import Recipe
    from src.grocery_wizard.recipes.recipe_maintenance import recipe_notion_markdown_link

    buckets: dict[tuple[str, str, str], list[NytReclassifyChange]] = {}
    for change in summary.changes:
        group_key = (
            change.field,
            _format_reclassify_value(change.old_value),
            _format_reclassify_value(change.new_value),
        )
        buckets.setdefault(group_key, []).append(change)

    group_items = sorted(
        buckets.items(),
        key=lambda item: (
            _reclassify_field_rank(item[0][0]),
            item[0][1],
            item[0][2],
        ),
    )

    lines.append("")
    for (_field, old_display, new_display), changes in group_items:
        field = changes[0].field
        count = len(changes)
        recipe_word = "recipe" if count == 1 else "recipes"
        lines.append(f"**({count} {recipe_word}) {field}: `{old_display}` → `{new_display}`**")
        for change in sorted(changes, key=lambda c: c.name.casefold()):
            recipe = Recipe(
                page_id=change.page_id,
                name=change.name,
                link=None,
                ingredients=None,
                properties={},
            )
            lines.append(f"- {recipe_notion_markdown_link(recipe)}")
        lines.append("")

    return "\n".join(lines).rstrip()


def apply_metadata_corrections(
    db: Any,
    corrections: list[dict[str, Any]],
) -> int:
    """Apply metadata updates. Each item: ``{"page_id": "...", "fields": {...}}``."""
    updated = 0
    for item in corrections:
        page_id = item.get("page_id")
        fields = item.get("fields")
        if not page_id or not fields:
            continue
        db.update_recipe(page_id, fields)
        updated += 1
    return updated


def _absolute_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return f"{SITE}{url}"
    return url


def _fetch_nyt_total_minutes(
    client: NYTCookingClient,
    recipe_id: str,
    url: str,
) -> float | None:
    total_minutes, _ingredients = _fetch_nyt_recipe_for_sync(client, recipe_id, url)
    return total_minutes


def _fetch_nyt_recipe_for_sync(
    client: NYTCookingClient,
    recipe_id: str,
    url: str,
) -> tuple[float | None, list[str]]:
    """Load timing and ingredients for NYT sync (API first, URL scrape fallback)."""
    resolved_id = recipe_id or _recipe_id_from_url(url) or ""
    total_minutes: float | None = None
    ingredients: list[str] = []

    if resolved_id:
        try:
            nyt_recipe = client.get_recipe(resolved_id)
            total_minutes = nyt_recipe.total_time_minutes
            ingredients = list(nyt_recipe.ingredients)
        except NYTCookingError:
            pass

    if not ingredients and url.strip():
        # Lazy import: scraper pulls ingredient pipeline; fallback when NYT API omits list.
        from src.grocery_wizard.recipes.scraper import ScrapeError, scrape_recipe

        try:
            scraped = scrape_recipe(url)
        except ScrapeError:
            pass
        else:
            ingredients = list(scraped.ingredients)
            if total_minutes is None:
                total_minutes = scraped.total_time_minutes

    return total_minutes, ingredients


def _recipe_id_from_url(url: str) -> str | None:
    match = re.search(r"/recipes/(\d+)", url)
    return match.group(1) if match else None


def _plain_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return _WHITESPACE.sub(" ", unescape(_HTML_TAGS.sub(" ", value))).strip()


def _ingredients_from_parts(parts: Any) -> list[str]:
    lines: list[str] = []
    if not isinstance(parts, list):
        return lines
    for group in parts:
        if not isinstance(group, dict):
            continue
        for item in group.get("ingredients", []):
            if not isinstance(item, dict):
                continue
            quantity = str(item.get("display_quantity") or "").strip()
            text = _plain_text(item.get("display_text", ""))
            line = f"{quantity} {text}".strip()
            if line:
                lines.append(line)
    return lines


def _parse_minutes(value: Any) -> float | None:
    if not isinstance(value, dict):
        return None
    minutes = value.get("minutes")
    if minutes is None:
        return None
    try:
        return float(minutes)
    except (TypeError, ValueError):
        return None


def _parse_recipe_payload(payload: dict[str, Any]) -> NytRecipe:
    byline = payload.get("byline")
    author = byline.strip().title() if isinstance(byline, str) and byline else None
    return NytRecipe(
        id=str(payload.get("id", "")),
        name=_plain_text(payload.get("name", "")) or str(payload.get("name", "")),
        url=_absolute_url(str(payload.get("url", ""))),
        ingredients=_ingredients_from_parts(payload.get("parts")),
        author=author,
        total_time_minutes=_parse_minutes(payload.get("cooking_time")),
        prep_time_minutes=_parse_minutes(payload.get("prep_time")),
        cook_time_minutes=_parse_minutes(payload.get("cook_time")),
    )
