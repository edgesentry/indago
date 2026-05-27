#!/usr/bin/env python3
"""W6 — E2E port cyber clearance: manifest → graph → eval → HTML → audit seal.

Cap Vista UC1 demo path. Deterministic evaluation (indago) + certificate (eds) + chain (eds).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from pipelines.maritime_cyber.eval import (
    evaluate_port_clearance,
    write_evaluation_artifacts,
)
from pipelines.maritime_cyber.graph import (
    DEFAULT_OUTPUT_DIR,
    build_maritime_cyber_graph,
    write_graph_parquet,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROFILE_MANIFEST = _REPO_ROOT / "profiles" / "maritime_cyber" / "manifest.yaml"
_DEFAULT_EDS_REL = _REPO_ROOT.parent / "edgesentry-rs" / "target" / "debug" / "eds"
_DEMO_PRIV_KEY = "0101010101010101010101010101010101010101010101010101010101010101"


@dataclass(frozen=True)
class ClearanceRunResult:
    vessel_key: str
    port_call_id: str
    outcome: str
    decision_hash: str
    output_dir: Path
    facts_path: Path
    manifest_path: Path
    html_path: Path | None
    chain_path: Path | None
    verify_url: str


def load_profile_manifest(path: Path | None = None) -> dict[str, Any]:
    """Load maritime_cyber profile manifest (fixture paths, pipeline ids)."""
    manifest_path = path or _PROFILE_MANIFEST
    if not manifest_path.is_file():
        raise FileNotFoundError(f"profile manifest not found: {manifest_path}")
    with manifest_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"invalid manifest YAML: {manifest_path}")
    return data


def find_eds_binary(explicit: str | None = None) -> Path:
    """Resolve eds CLI: explicit path, EDS_BIN, PATH, or sibling edgesentry-rs build."""
    if explicit:
        p = Path(explicit)
        if p.is_file() and os.access(p, os.X_OK):
            return p
        raise FileNotFoundError(f"eds binary not executable: {p}")

    for candidate in (
        os.environ.get("EDS_BIN"),
        shutil.which("eds"),
    ):
        if candidate:
            p = Path(candidate)
            if p.is_file():
                return p

    sibling = _DEFAULT_EDS_REL
    if sibling.is_file():
        return sibling

    raise FileNotFoundError(
        "eds not found — set EDS_BIN, install eds on PATH, or build edgesentry-rs: "
        "cargo build -p eds"
    )


def _run_eds(args: list[str], eds: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(eds), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _default_verify_url(decision_hash: str) -> str:
    return f"https://verify.edgesentry.io/clearance/{decision_hash}"


def run_clearance(
    vessel_key: str,
    *,
    port_call_id: str = "port-call-demo-sgsin",
    output_dir: Path | None = None,
    profile_manifest: Path | None = None,
    graph_output_dir: Path | None = None,
    write_graph: bool = True,
    eds_bin: str | Path | None = None,
    verify_url: str | None = None,
    private_key_hex: str = _DEMO_PRIV_KEY,
    device_id: str = "port-clearance-poc",
    skip_render: bool = False,
    skip_seal: bool = False,
) -> ClearanceRunResult:
    """Run full clearance pipeline; return paths and outcome."""
    profile = load_profile_manifest(profile_manifest)
    out = Path(output_dir or DEFAULT_OUTPUT_DIR / "clearance_runs" / vessel_key)
    out.mkdir(parents=True, exist_ok=True)

    graph_dir = Path(graph_output_dir or DEFAULT_OUTPUT_DIR)
    graph_result = build_maritime_cyber_graph([vessel_key])
    if write_graph:
        write_graph_parquet(graph_result, graph_dir)

    eval_result = evaluate_port_clearance(
        vessel_key,
        port_call_id=port_call_id,
        graph_result=graph_result,
    )
    artifact_paths = write_evaluation_artifacts(eval_result, out)
    facts_path = artifact_paths["facts"]
    manifest_path = artifact_paths["manifest"]

    url = verify_url or _default_verify_url(eval_result.decision_hash)
    prefix = f"{vessel_key}_{port_call_id}".replace("/", "-")
    html_path: Path | None = out / f"{prefix}_port-cyber-clearance.html"
    chain_path: Path | None = out / f"{prefix}_clearance_chain.json"

    if skip_render:
        html_path = None
    if skip_seal:
        chain_path = None

    eds: Path | None = None
    if not skip_render or not skip_seal:
        eds = find_eds_binary(str(eds_bin) if eds_bin else None)

    if not skip_render and html_path is not None and eds is not None:
        render = _run_eds(
            [
                "document",
                "render-clearance",
                "--facts",
                str(facts_path),
                "--verify-url",
                url,
                "--out",
                str(html_path),
            ],
            eds,
        )
        if render.returncode != 0:
            raise RuntimeError(f"eds document render-clearance failed:\n{render.stderr}")

    if not skip_seal and chain_path is not None and eds is not None:
        sign = _run_eds(
            [
                "audit",
                "sign-clearance",
                "--manifest",
                str(manifest_path),
                "--key",
                private_key_hex,
                "--device-id",
                device_id,
                "--out",
                str(chain_path),
            ],
            eds,
        )
        if sign.returncode != 0:
            raise RuntimeError(f"eds audit sign-clearance failed:\n{sign.stderr}")

    # Persist run summary for W7 / demo tooling
    summary = {
        "vessel_key": vessel_key,
        "port_call_id": port_call_id,
        "outcome": eval_result.outcome,
        "decision_hash": eval_result.decision_hash,
        "profile_id": profile.get("profile_id"),
        "profile_version": profile.get("version"),
        "facts": str(facts_path),
        "manifest": str(manifest_path),
        "html": str(html_path) if html_path else None,
        "chain": str(chain_path) if chain_path else None,
        "verify_url": url,
    }
    (out / f"{prefix}_run_summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    return ClearanceRunResult(
        vessel_key=vessel_key,
        port_call_id=port_call_id,
        outcome=eval_result.outcome,
        decision_hash=eval_result.decision_hash,
        output_dir=out,
        facts_path=facts_path,
        manifest_path=manifest_path,
        html_path=html_path,
        chain_path=chain_path,
        verify_url=url,
    )


def print_verify_instructions(result: ClearanceRunResult, eds: Path | None = None) -> None:
    """Print third-party verify commands (G6/G7 demo script)."""
    print("\n=== Port Cyber Clearance — verify (third party) ===\n")
    print(f"  outcome:        {result.outcome.upper()}")
    print(f"  decision_hash:  {result.decision_hash}")
    print(f"  verify_url:     {result.verify_url}\n")

    if result.html_path:
        print(f"  certificate:    {result.html_path}")
        print("  (open in browser → Print → Save as PDF)\n")

    if result.chain_path is None:
        print("  audit chain:    (skipped — re-run without --skip-seal)\n")
        return

    eds_path = eds or find_eds_binary()
    print("  audit chain:    ", result.chain_path)
    print("\n  eds audit verify-chain \\")
    print(f"    --records-file {result.chain_path}\n")
    print("  eds audit verify-clearance \\")
    print(f"    --manifest {result.manifest_path} \\")
    print(f"    --chain {result.chain_path}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="E2E port cyber clearance (graph → eval → HTML → audit seal)",
    )
    parser.add_argument("vessel_key", help="Fixture vessel key (e.g. vessel-hold)")
    parser.add_argument(
        "--port-call-id",
        default="port-call-demo-sgsin",
        help="Port call identifier",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for facts, manifest, HTML, chain (default: data/processed/.../clearance_runs/<vessel>)",
    )
    parser.add_argument(
        "--profile-manifest",
        type=Path,
        default=_PROFILE_MANIFEST,
        help="maritime_cyber profile manifest.yaml",
    )
    parser.add_argument(
        "--no-write-graph",
        action="store_true",
        help="Skip writing graph Parquet (eval still builds in memory)",
    )
    parser.add_argument("--eds-bin", help="Path to eds binary (or set EDS_BIN)")
    parser.add_argument("--verify-url", help="URL printed on certificate")
    parser.add_argument(
        "--key",
        default=_DEMO_PRIV_KEY,
        help="Ed25519 private key hex for sign-clearance (demo default)",
    )
    parser.add_argument("--device-id", default="port-clearance-poc")
    parser.add_argument("--skip-render", action="store_true", help="Skip HTML certificate")
    parser.add_argument("--skip-seal", action="store_true", help="Skip audit sign-clearance")
    parser.add_argument("--json", action="store_true", help="Print run summary JSON to stdout")
    args = parser.parse_args(argv)

    try:
        profile = load_profile_manifest(args.profile_manifest)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(
        f"profile: {profile.get('profile_id')} v{profile.get('version')} "
        f"({args.profile_manifest})",
        file=sys.stderr,
    )

    try:
        result = run_clearance(
            args.vessel_key,
            port_call_id=args.port_call_id,
            output_dir=args.output_dir,
            profile_manifest=args.profile_manifest,
            write_graph=not args.no_write_graph,
            eds_bin=args.eds_bin,
            verify_url=args.verify_url,
            private_key_hex=args.key,
            device_id=args.device_id,
            skip_render=args.skip_render,
            skip_seal=args.skip_seal,
        )
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "vessel_key": result.vessel_key,
                    "outcome": result.outcome,
                    "decision_hash": result.decision_hash,
                    "facts": str(result.facts_path),
                    "manifest": str(result.manifest_path),
                    "html": str(result.html_path) if result.html_path else None,
                    "chain": str(result.chain_path) if result.chain_path else None,
                    "verify_url": result.verify_url,
                },
                indent=2,
            )
        )
    else:
        print(f"\noutcome: {result.outcome}")
        print(f"decision_hash: {result.decision_hash}")
        if result.html_path:
            print(f"html: {result.html_path}")
        if result.chain_path:
            print(f"chain: {result.chain_path}")

    try:
        eds = None if args.skip_seal else find_eds_binary(args.eds_bin)
    except FileNotFoundError:
        eds = None
    print_verify_instructions(result, eds=eds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
