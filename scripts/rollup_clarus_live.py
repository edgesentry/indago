"""CLI: merge clarus raw Parquet → per-site rollup files in clarus-dev-public-raw.

Usage
-----
  uv run python scripts/rollup_clarus_live.py            # live R2 run (90-day window)
  uv run python scripts/rollup_clarus_live.py --dry-run  # print result, skip write
  uv run python scripts/rollup_clarus_live.py --days 0   # all history
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser(description="clarus live rollup pipeline")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from pipelines.clarus.live_rollup import run

    results = run(dry_run=args.dry_run, days=args.days)

    if not results:
        logging.warning("No rollup files written")
        sys.exit(1)

    for label, rows in results.items():
        print(f"  {label}: {rows} rows")
    print(f"\n{len(results)} rollup file(s) {'(dry-run)' if args.dry_run else 'written'}")


if __name__ == "__main__":
    main()
