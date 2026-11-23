"""External service integrations (Notion, NYT Cooking, …)."""

from src.grocery_hub.integrations.notion import NotionRecipesDB, Recipe

__all__ = ["NotionRecipesDB", "Recipe"]
