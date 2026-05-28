#!/usr/bin/env python3
"""CLI — generate D5 operator explanation from clearance *_facts.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agents.port_clearance.ai_narrative import (
    NarrativeGuardrailError,
    generate_operator_explanation,
    write_operator_explanation_artifacts,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate guardrailed operator explanation (D5)")
    parser.add_argument("facts", type=Path, help="Path to *_facts.json")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write *_operator_explanation.txt and *_operator_explanation_meta.json",
    )
    parser.add_argument("--json", action="store_true", help="Print narrative JSON to stdout")
    args = parser.parse_args(argv)

    facts_path = args.facts.resolve()
    if not facts_path.is_file():
        print(f"error: facts not found: {facts_path}", file=sys.stderr)
        return 2

    try:
        facts = json.loads(facts_path.read_text(encoding="utf-8"))
        narrative = generate_operator_explanation(facts, mode="template")
    except (NarrativeGuardrailError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.write:
        paths = write_operator_explanation_artifacts(facts_path)
        print(paths["text"], file=sys.stderr)
        print(paths["meta"], file=sys.stderr)

    if args.json:
        print(json.dumps({"narrative": narrative, "facts": str(facts_path)}, indent=2))
    else:
        print(narrative)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
