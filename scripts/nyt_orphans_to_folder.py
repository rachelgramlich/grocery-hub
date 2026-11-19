#!/usr/bin/env python3
"""Add recipe-box recipes that are not in any folder to a named folder."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from src.grocery_wizard.integrations.nyt_cooking import (  # noqa: E402
    NYTCookingClient,
    default_orphan_target_folder,
    file_orphans_into_folder,
    format_orphan_file_summary,
    load_credentials,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", default=None, help="Override target folder name")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delay", type=float, default=0.25)
    args = parser.parse_args()

    if load_credentials() is None:
        raise SystemExit("Set NYT_S_COOKIE and NYT_REGI_ID")

    client = NYTCookingClient()
    client.verify_auth()
    folder = args.folder or default_orphan_target_folder()
    summary = file_orphans_into_folder(
        client,
        folder_name=folder,
        dry_run=args.dry_run,
        delay_seconds=args.delay,
    )
    print(format_orphan_file_summary(summary))
    if summary.failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()