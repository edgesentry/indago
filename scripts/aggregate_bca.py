"""CLI: aggregate clarus BCA audit_chain data → documaris outlet features.

Usage
-----
  uv run python scripts/aggregate_bca.py            # live R2 run
  uv run python scripts/aggregate_bca.py --dry-run  # print result, skip write
  uv run python scripts/aggregate_bca.py --verbose  # debug logging

Environment
-----------
  AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY — Cloudflare R2 credentials
  S3_ENDPOINT                               — override R2 endpoint (optional)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser(description="BCA Green Mark aggregation pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Skip R2 write, print result only")
    parser.add_argument("--days", type=int, default=90, help="Retention window in days (default 90, 0=all)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not os.getenv("AWS_ACCESS_KEY_ID"):
        logging.warning("AWS_ACCESS_KEY_ID not set — R2 reads/writes will fail unless the bucket is public")

    from pipelines.bca.aggregate import run

    features = run(dry_run=args.dry_run, days=args.days)

    if features.is_empty():
        logging.warning("No BCA outlet features generated")
        sys.exit(1)

    print(features)
    print(f"\n{len(features)} outlet(s) aggregated")


if __name__ == "__main__":
    main()
