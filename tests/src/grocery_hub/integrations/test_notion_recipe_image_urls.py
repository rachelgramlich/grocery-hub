"""Notion recipe list queries and cover image URL hydration."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.grocery_hub.config import Config
from src.grocery_hub.integrations.notion import ColumnInfo, DatabaseSchema, NotionRecipesDB


def _db() -> NotionRecipesDB:
    schema = DatabaseSchema(
        name_column="Name",
        link_column="Link",
        ingredients_column=None,
        filter_columns=[],
        checkbox_columns=[],
        all_columns={
            "Name": ColumnInfo(name="Name", type="title"),
            "Link": ColumnInfo(name="Link", type="url"),
            "Cover image": ColumnInfo(name="Cover image", type="files"),
        },
        image_column="Cover image",
    )
    config = Config.model_construct(
        notion_api_key="secret",
        notion_recipe_database_id="db-id",
        notion_pantry_database_id="pantry-id",
        notion_recurring_weekly_database_id="recurring-id",
        notion_weekly_meal_plans_database_id="plans-id",
        recipe_image_column="Cover image",
    )
    db = NotionRecipesDB.__new__(NotionRecipesDB)
    db._client = MagicMock()
    db._database_id = "db-id"
    db._config = config
    db._data_source_id = "ds-id"
    db.schema = schema
    return db


def _list_page(page_id: str, *, image_prop: dict) -> dict:
    return {
        "id": page_id,
        "last_edited_time": "2026-11-25T12:00:00.000Z",
        "properties": {
            "Name": {"type": "title", "title": [{"plain_text": "Soup", "type": "text"}]},
            "Link": {"type": "url", "url": None},
            "Cover image": image_prop,
        },
    }


def test_query_recipes_retrieves_page_when_list_row_lacks_download_url() -> None:
    db = _db()
    list_prop = {
        "type": "files",
        "files": [
            {
                "type": "file_upload",
                "name": "cover.jpg",
                "file_upload": {"id": "upload-1"},
            },
        ],
    }
    full_prop = {
        "type": "files",
        "files": [
            {
                "type": "file",
                "file": {
                    "url": "https://prod-files-secure.s3.us-west-2.amazonaws.com/cover.jpg",
                    "expiry_time": "2026-11-25T19:00:00.000Z",
                },
                "name": "cover.jpg",
            },
        ],
    }
    db._client.data_sources.query.return_value = {
        "results": [_list_page("page-1", image_prop=list_prop)],
        "has_more": False,
    }
    db._client.pages.retrieve.return_value = _list_page("page-1", image_prop=full_prop)

    recipes = db.query_recipes()

    db._client.pages.retrieve.assert_called_once_with(page_id="page-1")
    assert len(recipes) == 1
    assert recipes[0].image_file_url.endswith("cover.jpg")
    assert recipes[0].image_file_url_expires_at is not None
