"""Deterministic port cyber clearance evaluation (W3)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx
import polars as pl

from pipelines.maritime_cyber.graph import (
    DEFAULT_CVE_SNAPSHOT,
    DEFAULT_SBOM_DIR,
    GraphBuildResult,
    affected_vessels_for_cve,
    build_maritime_cyber_graph,
    load_sbom,
)
from pipelines.maritime_cyber.audit_refs import (
    build_bom_baseline_ref,
    build_cve_snapshot_ref,
    integrated_snapshot_fingerprint,
)
from pipelines.maritime_cyber.rules import DEFAULT_RULE_PACK, load_asset_map, load_rule_pack

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = _REPO_ROOT / "data/processed/maritime_cyber"


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    title: str
    severity: str
    outcome: str
    requirements: list[str]
    evidence: dict[str, Any]


@dataclass(frozen=True)
class EvaluationResult:
    vessel_key: str
    port_call_id: str
    outcome: str
    rules_fired: tuple[RuleHit, ...]
    facts: dict[str, Any]
    manifest: dict[str, Any]
    decision_hash: str


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def normalize_cve_node_id(cve_id: str) -> str:
    if cve_id.startswith("cve:"):
        return cve_id
    if cve_id.upper().startswith("CVE-"):
        return f"cve:{cve_id.upper()}"
    return f"cve:{cve_id}"


def node_properties(nodes: pl.DataFrame, node_id: str) -> dict[str, Any]:
    rows = nodes.filter(pl.col("node_id") == node_id)
    if len(rows) == 0:
        return {}
    raw = rows["properties"][0]
    if not raw:
        return {}
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


def iter_cve_asset_paths(
    graph: nx.DiGraph,
    nodes: pl.DataFrame,
    vessel_key: str,
) -> list[dict[str, Any]]:
    """Forward walk: vessel → asset → firmware → component → CVE."""
    vessel_id = f"vessel:{vessel_key}"
    if vessel_id not in graph:
        return []
    paths: list[dict[str, Any]] = []
    for asset_id in graph.successors(vessel_id):
        if graph.nodes[asset_id].get("node_type") != "PhysicalAsset":
            continue
        asset_props = node_properties(nodes, asset_id)
        for fw_id in graph.successors(asset_id):
            if graph.edges.get((asset_id, fw_id), {}).get("rel_type") != "runs":
                continue
            for comp_id in graph.successors(fw_id):
                if graph.edges.get((fw_id, comp_id), {}).get("rel_type") != "contains":
                    continue
                for cve_id in graph.successors(comp_id):
                    if graph.edges.get((comp_id, cve_id), {}).get("rel_type") != "affectedBy":
                        continue
                    cve_props = node_properties(nodes, cve_id)
                    paths.append(
                        {
                            "vessel_id": vessel_id,
                            "asset_id": asset_id,
                            "firmware_id": fw_id,
                            "component_id": comp_id,
                            "cve_id": cve_id,
                            "asset": asset_props,
                            "cve": cve_props,
                            "component": node_properties(nodes, comp_id),
                        }
                    )
    return paths


def format_impacted_paths(cve_paths: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """G12: structured paths for auditors (component → CVE → asset → vessel)."""
    formatted: list[dict[str, Any]] = []
    for p in cve_paths:
        asset = p.get("asset") or {}
        component = p.get("component") or {}
        cve = p.get("cve") or {}
        formatted.append(
            {
                "vessel_id": p.get("vessel_id"),
                "asset_id": p.get("asset_id"),
                "asset_name": asset.get("name"),
                "firmware_id": p.get("firmware_id"),
                "component_id": p.get("component_id"),
                "component_name": component.get("name"),
                "component_purl": component.get("purl"),
                "cve_id": p.get("cve_id"),
                "cve_osv_id": cve.get("osv_id"),
                "cvss_score": cve.get("cvss_score"),
                "path_nodes": [
                    p.get("asset_id"),
                    p.get("firmware_id"),
                    p.get("component_id"),
                    p.get("cve_id"),
                ],
            }
        )
    return formatted


def _match_cve_on_asset_path(path: dict[str, Any], match: dict[str, Any]) -> bool:
    cve = path.get("cve") or {}
    asset = path.get("asset") or {}
    cvss = cve.get("cvss_score")
    if cvss is None:
        return False
    if float(cvss) < float(match.get("cvss_gte", 0)):
        return False
    sf_in = match.get("safety_function_in")
    if sf_in and asset.get("safety_function") not in sf_in:
        return False
    cat_in = match.get("cbs_category_in")
    if cat_in and asset.get("cbs_category") not in cat_in:
        return False
    return True


def _evaluate_rule(
    rule: dict[str, Any],
    *,
    vessel_key: str,
    graph: nx.DiGraph,
    nodes: pl.DataFrame,
    asset_map: dict[str, Any],
    sbom_components: list[dict[str, Any]],
    cve_paths: list[dict[str, Any]],
) -> RuleHit | None:
    rule_id = str(rule["id"])
    cond = rule.get("condition") or {}
    ctype = cond.get("type")
    evidence: dict[str, Any] = {}

    if ctype == "cve_on_asset_path":
        match = cond.get("match") or {}
        for path in cve_paths:
            if _match_cve_on_asset_path(path, match):
                evidence = {
                    "path": [
                        path["asset_id"],
                        path["firmware_id"],
                        path["component_id"],
                        path["cve_id"],
                    ],
                    "cve_id": path["cve_id"],
                    "cvss_score": path["cve"].get("cvss_score"),
                    "cbs_category": path["asset"].get("cbs_category"),
                }
                break
        else:
            return None

    elif ctype == "sbom_field_missing":
        field_name = str(cond.get("field", ""))
        missing: list[str] = []
        for comp in sbom_components:
            if field_name == "supplier.name":
                supplier = comp.get("supplier") or {}
                if not isinstance(supplier, dict) or not supplier.get("name"):
                    missing.append(str(comp.get("purl") or comp.get("name")))
            elif field_name == "version":
                if not comp.get("version"):
                    missing.append(str(comp.get("purl") or comp.get("name")))
        if not missing:
            return None
        evidence = {"missing_components": missing, "field": field_name}

    elif ctype == "sbom_identifier_missing":
        require_any = cond.get("require_any") or ["purl", "cpe"]
        missing = []
        for comp in sbom_components:
            if not any(comp.get(k) for k in require_any):
                missing.append(str(comp.get("name")))
        if not missing:
            return None
        evidence = {"missing_identifiers": missing}

    elif ctype == "asset_map_field_missing":
        fields = cond.get("fields") or []
        vessels = asset_map.get("vessels") or {}
        vessel_cfg = vessels.get(vessel_key) or {}
        gaps: list[dict[str, str]] = []
        for asset in vessel_cfg.get("physical_assets") or []:
            if not isinstance(asset, dict):
                continue
            for fld in fields:
                if not asset.get(fld):
                    gaps.append({"asset_id": str(asset.get("id")), "field": fld})
        if not gaps:
            return None
        evidence = {"gaps": gaps}

    elif ctype == "cve_flag":
        flag = cond.get("flag")
        want = cond.get("value")
        for path in cve_paths:
            if path["cve"].get(flag) == want:
                evidence = {"cve_id": path["cve_id"], flag: want}
                break
        else:
            return None

    elif ctype == "mandatory_cbs_categories":
        required = set(cond.get("required") or [])
        vessels = asset_map.get("vessels") or {}
        vessel_cfg = vessels.get(vessel_key) or {}
        present = {
            a.get("cbs_category")
            for a in (vessel_cfg.get("physical_assets") or [])
            if isinstance(a, dict) and a.get("cbs_category")
        }
        missing_cats = sorted(required - present)
        if not missing_cats:
            return None
        evidence = {"missing_categories": missing_cats}

    elif ctype in ("process_log_required", "patch_age_exceeded"):
        # PoC: no ProcessLog fixtures or CVE published_at in snapshot — never auto-fire
        return None

    else:
        return None

    return RuleHit(
        rule_id=rule_id,
        title=str(rule.get("title", "")),
        severity=str(rule.get("severity", "")),
        outcome=str(rule.get("outcome", "hold")),
        requirements=list(rule.get("requirements") or []),
        evidence=evidence,
    )


def evaluate_port_clearance(
    vessel_key: str,
    *,
    port_call_id: str = "port-call-demo-sgsin",
    graph_result: GraphBuildResult | None = None,
    rule_pack_path: Path | None = None,
    asset_map_path: Path | None = None,
    cve_snapshot_path: Path | None = None,
    sbom_dir: Path | None = None,
) -> EvaluationResult:
    """Evaluate clearance for one vessel; deterministic on pinned fixtures."""
    pack = load_rule_pack(rule_pack_path)
    asset_map = load_asset_map(asset_map_path)
    gresult = graph_result or build_maritime_cyber_graph(
        [vessel_key],
        asset_map_path=asset_map_path,
        cve_snapshot_path=cve_snapshot_path,
        sbom_dir=sbom_dir,
    )
    g = gresult.nx_graph
    nodes = gresult.nodes

    sbom_path = (sbom_dir or DEFAULT_SBOM_DIR) / f"{vessel_key}.json"
    sbom_components = load_sbom(sbom_path) if sbom_path.is_file() else []
    cve_paths = iter_cve_asset_paths(g, nodes, vessel_key)

    hits: list[RuleHit] = []
    for rule in pack.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        hit = _evaluate_rule(
            rule,
            vessel_key=vessel_key,
            graph=g,
            nodes=nodes,
            asset_map=asset_map,
            sbom_components=sbom_components,
            cve_paths=cve_paths,
        )
        if hit is not None:
            hits.append(hit)

    hold_outcomes = {h.outcome for h in hits if h.outcome == "hold"}
    outcome = "hold" if hold_outcomes else str(pack.get("default_outcome", "pass"))

    cve_path = Path(cve_snapshot_path or DEFAULT_CVE_SNAPSHOT)
    rule_path = rule_pack_path or DEFAULT_RULE_PACK
    bom_baseline_ref = build_bom_baseline_ref(
        vessel_key,
        asset_map_path=asset_map_path,
        sbom_dir=sbom_dir,
    )
    cve_snapshot_ref = build_cve_snapshot_ref(cve_snapshot_path=cve_path)
    impacted_paths = format_impacted_paths(cve_paths)

    manifest = {
        "vessel_key": vessel_key,
        "port_call_id": port_call_id,
        "rule_pack_id": pack.get("pack_id"),
        "rule_pack_version": pack.get("version"),
        "rule_pack_sha256": _file_sha256(rule_path),
        "bom_baseline_ref": bom_baseline_ref,
        "cve_snapshot_ref": cve_snapshot_ref,
        "cve_snapshot_sha256": cve_snapshot_ref["cve_snapshot_sha256"],
        "sbom_sha256": bom_baseline_ref["sbom_sha256"],
        "outcome": outcome,
        "rules_fired": [h.rule_id for h in hits],
        "graph_node_count": len(nodes),
        "graph_edge_count": len(gresult.edges),
        "impacted_path_count": len(impacted_paths),
    }
    manifest["integrated_snapshot_fingerprint"] = integrated_snapshot_fingerprint(manifest)
    decision_hash = _canonical_hash(manifest)

    paths_for_facts = [
        {
            "rule_ids": [h.rule_id for h in hits if h.evidence.get("cve_id") == p["cve_id"]],
            "nodes": [p["asset_id"], p["firmware_id"], p["component_id"], p["cve_id"]],
            "summary": (
                f"{p['asset'].get('name')} → {p['cve'].get('osv_id', p['cve_id'])} "
                f"(CVSS {p['cve'].get('cvss_score')})"
            ),
        }
        for p in cve_paths
    ]

    facts: dict[str, Any] = {
        "vessel_key": vessel_key,
        "port_call_id": port_call_id,
        "outcome": outcome,
        "decision_hash": decision_hash,
        "bom_baseline_ref": bom_baseline_ref,
        "cve_snapshot_ref": cve_snapshot_ref,
        "integrated_snapshot_fingerprint": manifest["integrated_snapshot_fingerprint"],
        "impacted_paths": impacted_paths,
        "rules_fired": [
            {
                "id": h.rule_id,
                "title": h.title,
                "severity": h.severity,
                "requirements": h.requirements,
                "evidence": h.evidence,
            }
            for h in hits
        ],
        "paths": paths_for_facts,
        "cve_ids": sorted({p["cve_id"] for p in cve_paths}),
        "disclaimer": (
            "PoC clearance from public CVE snapshot and synthetic SBOM/asset_map fixtures. "
            "Not an official port-state or MPA berth approval."
        ),
    }

    return EvaluationResult(
        vessel_key=vessel_key,
        port_call_id=port_call_id,
        outcome=outcome,
        rules_fired=tuple(hits),
        facts=facts,
        manifest=manifest,
        decision_hash=decision_hash,
    )


def write_evaluation_artifacts(
    result: EvaluationResult,
    output_dir: Path | None = None,
) -> dict[str, Path]:
    """Write facts.json and evaluation manifest for audit/documaris."""
    out = Path(output_dir or DEFAULT_OUTPUT_DIR)
    out.mkdir(parents=True, exist_ok=True)
    prefix = f"{result.vessel_key}_{result.port_call_id}".replace("/", "-")
    facts_path = out / f"{prefix}_facts.json"
    manifest_path = out / f"{prefix}_evaluation_manifest.json"
    facts_path.write_text(json.dumps(result.facts, indent=2), encoding="utf-8")
    manifest_on_disk = {**result.manifest, "decision_hash": result.decision_hash}
    manifest_path.write_text(json.dumps(manifest_on_disk, indent=2), encoding="utf-8")

    snapshot_path = out / f"{prefix}_integrated_snapshot.json"
    snapshot_body = {
        "vessel_key": result.vessel_key,
        "port_call_id": result.port_call_id,
        "outcome": result.outcome,
        "decision_hash": result.decision_hash,
        "bom_baseline_ref": result.manifest.get("bom_baseline_ref"),
        "cve_snapshot_ref": result.manifest.get("cve_snapshot_ref"),
        "integrated_snapshot_fingerprint": result.manifest.get("integrated_snapshot_fingerprint"),
        "impacted_paths": result.facts.get("impacted_paths"),
    }
    snapshot_path.write_text(json.dumps(snapshot_body, indent=2), encoding="utf-8")

    return {"facts": facts_path, "manifest": manifest_path, "integrated_snapshot": snapshot_path}


def affected_vessels(
    cve_id: str,
    graph_result: GraphBuildResult | None = None,
) -> list[str]:
    """UC2: list vessel keys affected by a CVE (public API for CLI)."""
    gresult = graph_result or build_maritime_cyber_graph()
    return affected_vessels_for_cve(gresult.nx_graph, normalize_cve_node_id(cve_id))
