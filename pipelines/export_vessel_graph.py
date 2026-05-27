"""D4 — export per-vessel impacted vulnerability paths (Component → CVE → Asset → Vessel)."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

from pipelines.maritime_cyber.eval import format_impacted_paths, iter_cve_asset_paths
from pipelines.maritime_cyber.graph import (
    DEFAULT_OUTPUT_DIR,
    GraphBuildResult,
    build_maritime_cyber_graph,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOCUMARIS_DIST = _REPO_ROOT.parent / "documaris" / "dist"
_CAPVISTA_SUBMISSION_ARTEFACTS = (
    _REPO_ROOT.parent
    / "edgesentry-commercial"
    / "docs/programs/20260630-capvista-products/submission/artefacts"
)


def _copy_impacted_path_html(html_path: Path, vessel_key: str, dest_dir: Path) -> Path | None:
    """Copy HTML to an external bundle dir when the parent repo exists."""
    if not dest_dir.parent.is_dir():
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_html = dest_dir / f"{vessel_key}_impacted-path.html"
    dest_html.write_text(html_path.read_text(encoding="utf-8"), encoding="utf-8")
    return dest_html
_POC_DISCLAIMER = (
    "PoC: public CVE snapshot and synthetic SBOM/asset_map fixtures. "
    "Not an official port-state or MPA berth approval."
)


def build_impacted_paths(
    vessel_key: str,
    *,
    graph_result: GraphBuildResult | None = None,
    asset_map_path: Path | None = None,
    cve_snapshot_path: Path | None = None,
    sbom_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Build impacted paths from graph (same walk as port_clearance_eval)."""
    gresult = graph_result or build_maritime_cyber_graph(
        [vessel_key],
        asset_map_path=asset_map_path,
        cve_snapshot_path=cve_snapshot_path,
        sbom_dir=sbom_dir,
    )
    raw = iter_cve_asset_paths(gresult.nx_graph, gresult.nodes, vessel_key)
    return format_impacted_paths(raw)


def export_impacted_paths_document(
    vessel_key: str,
    impacted_paths: list[dict[str, Any]],
    *,
    port_call_id: str = "port-call-demo-sgsin",
    outcome: str | None = None,
) -> dict[str, Any]:
    """Canonical JSON document for D4-1 (deterministic key order)."""
    return {
        "vessel_key": vessel_key,
        "port_call_id": port_call_id,
        "outcome": outcome,
        "path_direction": "PhysicalAsset → Firmware → SoftwareComponent → CVE (forward walk from vessel)",
        "impacted_paths": impacted_paths,
    }


def render_impacted_paths_html(
    document: dict[str, Any],
) -> str:
    """Self-contained HTML table + chain summary for one vessel (D4-2)."""
    vessel_key = str(document.get("vessel_key", ""))
    port_call_id = str(document.get("port_call_id", ""))
    outcome = str(document.get("outcome") or "unknown").upper()
    paths: list[dict[str, Any]] = list(document.get("impacted_paths") or [])

    rows: list[str] = []
    chain_blocks: list[str] = []
    for idx, p in enumerate(paths, start=1):
        component = p.get("component_purl") or p.get("component_name") or "—"
        cve = p.get("cve_osv_id") or p.get("cve_id") or "—"
        asset = p.get("asset_name") or p.get("asset_id") or "—"
        cvss = p.get("cvss_score")
        cvss_s = f"{cvss:.1f}" if isinstance(cvss, (int, float)) else "—"
        nodes = p.get("path_nodes") or []
        node_line = " → ".join(html.escape(str(n)) for n in nodes)
        rows.append(
            f"<tr><td>{idx}</td>"
            f"<td>{html.escape(str(component))}</td>"
            f"<td>{html.escape(str(cve))}</td>"
            f"<td>{cvss_s}</td>"
            f"<td>{html.escape(str(asset))}</td>"
            f"<td><code>{node_line}</code></td></tr>"
        )
        chain_blocks.append(
            f'<div class="chain">'
            f"<strong>Path {idx}</strong>: "
            f"{html.escape(str(component))} "
            f"<span class=\"arrow\">→</span> "
            f"{html.escape(str(cve))} "
            f"<span class=\"arrow\">→</span> "
            f"{html.escape(str(asset))} "
            f"<span class=\"arrow\">→</span> "
            f"{html.escape(vessel_key)}"
            f"</div>"
        )

    if not rows:
        rows.append(
            '<tr><td colspan="6" class="muted">No impacted vulnerability paths on this vessel.</td></tr>'
        )
        chain_blocks.append('<p class="muted">No paths to display.</p>')

    chains_html = "\n".join(chain_blocks)
    table_rows = "\n".join(rows)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Impacted paths — {html.escape(vessel_key)}</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 24px; color: #0f172a; line-height: 1.45; }}
  h1 {{ font-size: 1.25rem; margin: 0 0 8px; }}
  .meta {{ color: #475569; font-size: 0.9rem; margin-bottom: 16px; }}
  .outcome {{ display: inline-block; padding: 4px 10px; border-radius: 4px; font-weight: 700; }}
  .outcome-HOLD {{ background: #fef2f2; color: #b91c1c; border: 1px solid #dc2626; }}
  .outcome-PASS {{ background: #ecfdf5; color: #047857; border: 1px solid #10b981; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.85rem; margin: 16px 0; }}
  th, td {{ border: 1px solid #cbd5e1; padding: 8px; text-align: left; vertical-align: top; }}
  th {{ background: #e2e8f0; }}
  .chain {{ background: #f8fafc; border: 1px solid #e2e8f0; padding: 10px 12px; margin: 8px 0; }}
  .arrow {{ color: #1e4a7a; font-weight: bold; }}
  .muted {{ color: #64748b; font-style: italic; }}
  .disclaimer {{ margin-top: 24px; font-size: 0.75rem; color: #64748b; border-top: 1px solid #e2e8f0; padding-top: 12px; }}
  code {{ font-size: 0.75rem; word-break: break-all; }}
</style>
</head>
<body>
<h1>Impacted vulnerability paths</h1>
<p class="meta">Vessel <strong>{html.escape(vessel_key)}</strong> · Port call <strong>{html.escape(port_call_id)}</strong> ·
<span class="outcome outcome-{html.escape(outcome)}">{html.escape(outcome)}</span></p>
<p class="meta">Traversal: Component → CVE → Asset → Vessel (see table for graph node IDs)</p>
{chains_html}
<table>
<thead>
<tr><th>#</th><th>Component</th><th>CVE</th><th>CVSS</th><th>Asset</th><th>Graph path</th></tr>
</thead>
<tbody>
{table_rows}
</tbody>
</table>
<p class="disclaimer">{html.escape(_POC_DISCLAIMER)}</p>
</body>
</html>
"""


def write_vessel_graph_artifacts(
    vessel_key: str,
    output_dir: Path,
    *,
    prefix: str,
    impacted_paths: list[dict[str, Any]] | None = None,
    port_call_id: str = "port-call-demo-sgsin",
    outcome: str | None = None,
    graph_result: GraphBuildResult | None = None,
    asset_map_path: Path | None = None,
    cve_snapshot_path: Path | None = None,
    sbom_dir: Path | None = None,
    copy_to_documaris_dist: bool = False,
    copy_to_capvista_submission: bool = False,
) -> dict[str, Path]:
    """Write JSON + HTML impacted-path exports; return paths."""
    paths = impacted_paths
    if paths is None:
        paths = build_impacted_paths(
            vessel_key,
            graph_result=graph_result,
            asset_map_path=asset_map_path,
            cve_snapshot_path=cve_snapshot_path,
            sbom_dir=sbom_dir,
        )

    document = export_impacted_paths_document(
        vessel_key,
        paths,
        port_call_id=port_call_id,
        outcome=outcome,
    )
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / f"{prefix}_impacted_paths.json"
    html_path = out / f"{prefix}_impacted-path.html"
    json_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    html_path.write_text(render_impacted_paths_html(document), encoding="utf-8")

    result = {"json": json_path, "html": html_path}

    if copy_to_documaris_dist:
        copied = _copy_impacted_path_html(html_path, vessel_key, _DOCUMARIS_DIST)
        if copied:
            result["documaris_dist_html"] = copied

    if copy_to_capvista_submission:
        copied = _copy_impacted_path_html(html_path, vessel_key, _CAPVISTA_SUBMISSION_ARTEFACTS)
        if copied:
            result["capvista_submission_html"] = copied

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export vessel impacted vulnerability paths (D4)")
    parser.add_argument("vessel_key", help="Fixture vessel key (e.g. vessel-hold)")
    parser.add_argument("--port-call-id", default="port-call-demo-sgsin")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--copy-to-documaris-dist",
        action="store_true",
        help="Also write documaris/dist/<vessel>_impacted-path.html",
    )
    parser.add_argument(
        "--copy-to-capvista-submission",
        action="store_true",
        help="Also write edgesentry-commercial/.../submission/artefacts/<vessel>_impacted-path.html",
    )
    parser.add_argument("--json", action="store_true", help="Print paths JSON to stdout")
    args = parser.parse_args(argv)

    graph = build_maritime_cyber_graph([args.vessel_key])
    from pipelines.maritime_cyber.eval import evaluate_port_clearance

    eval_result = evaluate_port_clearance(
        args.vessel_key,
        port_call_id=args.port_call_id,
        graph_result=graph,
    )
    prefix = f"{args.vessel_key}_{args.port_call_id}".replace("/", "-")
    out_dir = Path(args.output_dir) / "clearance_runs" / args.vessel_key
    paths = write_vessel_graph_artifacts(
        args.vessel_key,
        out_dir,
        prefix=prefix,
        impacted_paths=eval_result.facts["impacted_paths"],
        port_call_id=args.port_call_id,
        outcome=eval_result.outcome,
        copy_to_documaris_dist=args.copy_to_documaris_dist,
        copy_to_capvista_submission=args.copy_to_capvista_submission,
    )
    if args.json:
        print(json.dumps(json.loads(paths["json"].read_text(encoding="utf-8")), indent=2))
    else:
        for name, p in paths.items():
            print(f"{name}: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
