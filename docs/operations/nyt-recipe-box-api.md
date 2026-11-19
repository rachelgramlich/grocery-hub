# NYT Cooking recipe box API (unofficial)

Grocery Wizard uses the same JSON endpoints as [cooking.nytimes.com](https://cooking.nytimes.com).  
`NYTCookingClient` in `src/grocery_wizard/integrations/nyt_cooking.py` supports **read** (sync to Notion) and **write** (save, folders).

## Credentials

`NYT_S_COOKIE` and `NYT_REGI_ID` (or `NYT_USER_ID`) in `.env` or Cloud Agent secrets. See `src/grocery_wizard/README.md`.

## Write operations

| Method | Purpose |
| --- | --- |
| `save_recipe(recipe_id)` | Add NYT recipe to recipe box (201 / 409) |
| `unsave_recipe(recipe_id)` | Remove from recipe box |
| `create_collection(name)` / `ensure_collection(name)` | Recipe-box folders |
| `add_to_collection(collection_id, recipe_id)` | Put saved recipe in a folder |
| `save_recipe_to_collection(collection_id, recipe_id)` | Save + folder in one call |
| `collection_recipe_ids(collection_id)` | List recipe ids in a folder |

## Paging

`iter_all_saved_recipes` uses `/api/v2/users/me/search/recipe_box_search` with `sort=rating` and re-applies the `NYT-S` cookie on each request so multi-page export works.

## Streamlit

The UI still uses **sync to Notion** only. Write APIs are for scripts and maintenance (account moves, bulk saves), not exposed in the app yet.

## One-off account migration

Migration from rg-playground (Nov 2025) proved bulk folder recreate via API.  
Archived scripts live in [rg-playground](https://github.com/rachelgramlich/rg-playground) `scripts/` on branch history; prefer `NYTCookingClient` here for any new automation.