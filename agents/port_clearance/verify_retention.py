#!/usr/bin/env python3
"""CLI — verify immutable WORM retention for a clearance run (D3-2)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agents.port_clearance.worm_store import verify_retention


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify clearance artefacts in mock WORM store (fetch + SHA-256)",
    )
    parser.add_argument(
        "publish_record",
        type=Path,
        help="Path to *_worm_publish.json from run_clearance",
    )
    parser.add_argument(
        "--worm-root",
        type=Path,
        help="Override WORM root (default: record or CLEARANCE_WORM_ROOT)",
    )
    parser.add_argument(
        "--skip-manifest-refs",
        action="store_true",
        help="Skip assert_manifest_audit_refs on stored manifest",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    args = parser.parse_args(argv)

    if not args.publish_record.is_file():
        print(f"error: publish record not found: {args.publish_record}", file=sys.stderr)
        return 2

    try:
        result = verify_retention(
            args.publish_record,
            worm_root=args.worm_root,
            check_manifest_refs=not args.skip_manifest_refs,
        )
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("RETENTION_VERIFIED")
        print(f"  worm_root: {result['worm_root']}")
        print(f"  objects:   {len(result['objects_verified'])}")
        print(f"  manifest_audit_refs: {result['manifest_audit_refs']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
