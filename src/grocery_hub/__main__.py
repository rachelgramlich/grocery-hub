"""``python -m grocery_hub`` delegates to the CLI."""

from __future__ import annotations

from src.grocery_hub.cli.main import main

if __name__ == "__main__":
    raise SystemExit(main())
