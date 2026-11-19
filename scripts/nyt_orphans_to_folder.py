#!/usr/bin/env python3
"""Add recipe-box recipes that are not in any folder to a named folder."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from src.grocery_wizard.integrations.nyt_cooking import (  # noqa: E402
    NYTCookingClient,
    load_credentials,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--folder",
        default="1 to make",
        help="Target folder name (default: 1 to make)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delay", type=float, default=0.25)
    args = parser.parse_args()

    if load_credentials() is None:
        raise SystemExit("Set NYT_S_COOKIE and NYT_REGI_ID")

    client = NYTCookingClient()
    client.verify_auth()

    in_folder: set[str] = set()
    for col in client.list_collections():
        for rid in client.collection_recipe_ids(col.id):
            in_folder.add(rid)

    in_box = {r.id for r in client.iter_all_saved_recipes()}
    orphans = sorted(in_box - in_folder, key=int)
    print(f"recipe box: {len(in_box)} | in any folder: {len(in_folder)} | orphans: {len(orphans)}")

    if args.dry_run:
        for rid in orphans[:20]:
            print(f"  would add {rid}")
        if len(orphans) > 20:
            print(f"  ... and {len(orphans) - 20} more")
        return

    folder = client.ensure_collection(args.folder)
    print(f"target folder {args.folder!r} id={folder.id}")

    added = already = failed = 0
    for rid in orphans:
        try:
            status = client.add_to_collection(folder.id, rid)
            if status == 201:
                added += 1
                print(f"added {rid}")
            else:
                already += 1
        except Exception as exc:
            failed += 1
            print(f"failed {rid}: {exc}")
        if args.delay > 0:
            time.sleep(args.delay)

    print(f"done: added={added} already_in_folder={already} failed={failed}")


if __name__ == "__main__":
    main()