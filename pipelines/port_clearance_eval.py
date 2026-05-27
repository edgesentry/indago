"""CLI — port cyber clearance evaluation (W3)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipelines.maritime_cyber.eval import (
    DEFAULT_OUTPUT_DIR,
    affected_vessels,
    evaluate_port_clearance,
    write_evaluation_artifacts,
)
from pipelines.maritime_cyber.graph import build_maritime_cyber_graph


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate port cyber clearance (pass/hold)")
    sub = parser.add_subparsers(dest="command", required=True)

    eval_p = sub.add_parser("evaluate", help="Run clearance for one vessel")
    eval_p.add_argument("vessel_key", help="Fixture vessel key (e.g. vessel-hold)")
    eval_p.add_argument("--port-call-id", default="port-call-demo-sgsin")
    eval_p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    eval_p.add_argument("--write", action="store_true", help="Write facts.json + manifest")

    uc2_p = sub.add_parser("affected-vessels", help="UC2 domino query by CVE id")
    uc2_p.add_argument("cve_id", help="CVE-2021-44228 or cve:CVE-2021-44228")

    args = parser.parse_args()

    if args.command == "evaluate":
        graph = build_maritime_cyber_graph([args.vessel_key])
        result = evaluate_port_clearance(
            args.vessel_key,
            port_call_id=args.port_call_id,
            graph_result=graph,
        )
        print(json.dumps({"outcome": result.outcome, "decision_hash": result.decision_hash}))
        if args.write:
            paths = write_evaluation_artifacts(result, args.output_dir)
            for name, path in paths.items():
                print(f"{name}: {path}")
    elif args.command == "affected-vessels":
        vessels = affected_vessels(args.cve_id)
        print(json.dumps(vessels))


if __name__ == "__main__":
    main()
