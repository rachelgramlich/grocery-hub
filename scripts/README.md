# Scripts

Small **maintainer** Python scripts that are not part of the installable package. Run from the **repo root** with `PYTHONPATH=src` (or via `uv run` after `just setup`).

| Script | Purpose |
| --- | --- |
| `recipe_metadata_repair.py` | Strip invalid Dinner/Lunch Category tags and/or backfill empty metadata (`--strip`, `--backfill`, `--dry-run`) |
| `record_weekly_loading_smoke.py` | Capture weekly-plan loading smoke for UI perf work |

Product entry points live in **`Justfile`** (`just grocery-ui`, `just check`, …) and **`src/grocery_wizard/`**, not here.
