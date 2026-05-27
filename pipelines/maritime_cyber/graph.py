"""Build maritime cyber clearance graph from fixtures (W2)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx
import polars as pl

from pipelines.maritime_cyber.rules import load_asset_map

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CVE_SNAPSHOT = _REPO_ROOT / "fixtures/cve/snapshot-2026-05-26.json"
DEFAULT_SBOM_DIR = _REPO_ROOT / "fixtures/sbom"
DEFAULT_OUTPUT_DIR = _REPO_ROOT / "data/processed/maritime_cyber"

NODE_SCHEMA = {
    "node_id": pl.Utf8,
    "node_type": pl.Utf8,
    "label": pl.Utf8,
    "vessel_key": pl.Utf8,
    "properties": pl.Utf8,
}

EDGE_SCHEMA = {
    "src_id": pl.Utf8,
    "dst_id": pl.Utf8,
    "rel_type": pl.Utf8,
    "vessel_key": pl.Utf8,
    "properties": pl.Utf8,
}


@dataclass(frozen=True)
class GraphBuildResult:
    """Nodes, edges, and in-memory graph for one build."""

    nodes: pl.DataFrame
    edges: pl.DataFrame
    nx_graph: nx.DiGraph
    manifest: dict[str, Any]


def _parse_version(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for segment in re.split(r"[.\-+]", version):
        if segment.isdigit():
            parts.append(int(segment))
        else:
            break
    return tuple(parts) if parts else (0,)


def _version_in_osv_range(version: str, events: list[dict[str, Any]]) -> bool:
    v = _parse_version(version)
    lower: tuple[int, ...] | None = None
    upper: tuple[int, ...] | None = None
    for event in events:
        if "introduced" in event:
            lower = _parse_version(str(event["introduced"]))
        if "fixed" in event:
            upper = _parse_version(str(event["fixed"]))
        if "last_affected" in event:
            upper = _parse_version(str(event["last_affected"]))
    if lower is not None and v < lower:
        return False
    if upper is not None and v >= upper:
        return False
    return True


def parse_purl(purl: str) -> tuple[str, str, str] | None:
    """Return (ecosystem, package_name, version) for supported pkg: URLs."""
    if not purl.startswith("pkg:"):
        return None
    body = purl[4:]
    if "@" not in body:
        return None
    coord, version = body.rsplit("@", 1)
    parts = coord.split("/", 2)
    if len(parts) < 3:
        return None
    ecosystem, namespace, name = parts[0], parts[1], parts[2]
    if ecosystem.lower() == "maven":
        pkg_name = f"{namespace}:{name}"
    else:
        pkg_name = f"{namespace}/{name}"
    return ecosystem, pkg_name, version


def load_cve_snapshot(path: Path | None = None) -> list[dict[str, Any]]:
    with (path or DEFAULT_CVE_SNAPSHOT).open(encoding="utf-8") as f:
        data = json.load(f)
    vulns = data.get("vulnerabilities", [])
    if not isinstance(vulns, list):
        msg = "CVE snapshot must contain vulnerabilities list"
        raise ValueError(msg)
    return vulns


def load_sbom(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    components = data.get("components", [])
    if not isinstance(components, list):
        return []
    return [c for c in components if isinstance(c, dict)]


def _component_node_id(vessel_key: str, purl: str) -> str:
    digest = hashlib.sha256(purl.encode()).hexdigest()[:12]
    return f"component:{vessel_key}:{digest}"


def _cve_node_id(vuln: dict[str, Any]) -> str:
    aliases = vuln.get("aliases") or []
    for alias in aliases:
        if isinstance(alias, str) and alias.startswith("CVE-"):
            return f"cve:{alias}"
    return f"cve:{vuln.get('id', 'unknown')}"


def _vuln_affects_component(vuln: dict[str, Any], component: dict[str, Any]) -> bool:
    purl = component.get("purl")
    version = component.get("version")
    if not purl or not version:
        return False
    parsed = parse_purl(str(purl))
    if parsed is None:
        return False
    _eco, pkg_name, _ver = parsed
    for affected in vuln.get("affected") or []:
        if not isinstance(affected, dict):
            continue
        pkg = affected.get("package") or {}
        if str(pkg.get("name")) != pkg_name:
            continue
        for rng in affected.get("ranges") or []:
            if not isinstance(rng, dict):
                continue
            events = rng.get("events") or []
            if isinstance(events, list) and _version_in_osv_range(str(version), events):
                return True
    return False


def build_maritime_cyber_graph(
    vessel_keys: list[str] | None = None,
    *,
    asset_map_path: Path | None = None,
    cve_snapshot_path: Path | None = None,
    sbom_dir: Path | None = None,
) -> GraphBuildResult:
    """Build node/edge tables and NetworkX graph for the demo fleet."""
    asset_map = load_asset_map(asset_map_path)
    vessels_cfg = asset_map.get("vessels") or {}
    if not isinstance(vessels_cfg, dict):
        msg = "asset_map vessels must be a mapping"
        raise ValueError(msg)

    keys = vessel_keys or list(vessels_cfg.keys())
    vulns = load_cve_snapshot(cve_snapshot_path)
    sbom_root = sbom_dir or DEFAULT_SBOM_DIR

    node_rows: list[dict[str, Any]] = []
    edge_rows: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()

    def add_node(
        node_id: str,
        node_type: str,
        label: str,
        vessel_key: str,
        properties: dict[str, Any],
    ) -> None:
        if node_id in seen_nodes:
            return
        seen_nodes.add(node_id)
        node_rows.append(
            {
                "node_id": node_id,
                "node_type": node_type,
                "label": label,
                "vessel_key": vessel_key,
                "properties": json.dumps(properties, sort_keys=True),
            }
        )

    def add_edge(
        src: str,
        dst: str,
        rel: str,
        vessel_key: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        edge_rows.append(
            {
                "src_id": src,
                "dst_id": dst,
                "rel_type": rel,
                "vessel_key": vessel_key,
                "properties": json.dumps(properties or {}, sort_keys=True),
            }
        )

    for vessel_key in keys:
        vessel_cfg = vessels_cfg.get(vessel_key)
        if not isinstance(vessel_cfg, dict):
            continue

        vessel_id = f"vessel:{vessel_key}"
        add_node(
            vessel_id,
            "Vessel",
            str(vessel_cfg.get("display_name") or vessel_key),
            vessel_key,
            {"imo": vessel_cfg.get("imo"), "vessel_key": vessel_key},
        )

        sbom_path = sbom_root / f"{vessel_key}.json"
        components = load_sbom(sbom_path) if sbom_path.is_file() else []
        sbom_id = f"sbom:{vessel_key}"
        add_node(
            sbom_id,
            "SBOM",
            f"SBOM {vessel_key}",
            vessel_key,
            {"path": str(sbom_path.name), "component_count": len(components)},
        )
        add_edge(vessel_id, sbom_id, "hasSBOM", vessel_key)

        purl_to_component_id: dict[str, str] = {}
        for comp in components:
            purl = str(comp.get("purl") or "")
            if not purl:
                continue
            comp_id = _component_node_id(vessel_key, purl)
            purl_to_component_id[purl] = comp_id
            supplier = comp.get("supplier") or {}
            add_node(
                comp_id,
                "SoftwareComponent",
                str(comp.get("name") or purl),
                vessel_key,
                {
                    "name": comp.get("name"),
                    "version": comp.get("version"),
                    "purl": purl,
                    "supplier_name": supplier.get("name") if isinstance(supplier, dict) else None,
                },
            )
            add_edge(sbom_id, comp_id, "lists", vessel_key)

            for vuln in vulns:
                if _vuln_affects_component(vuln, comp):
                    cve_id = _cve_node_id(vuln)
                    db = vuln.get("database_specific") or {}
                    add_node(
                        cve_id,
                        "CVE",
                        str(vuln.get("id")),
                        vessel_key,
                        {
                            "osv_id": vuln.get("id"),
                            "aliases": vuln.get("aliases"),
                            "cvss_score": db.get("cvss_score"),
                            "in_kev": bool(db.get("in_kev")),
                            "severity": vuln.get("severity"),
                        },
                    )
                    add_edge(comp_id, cve_id, "affectedBy", vessel_key)

        for asset in vessel_cfg.get("physical_assets") or []:
            if not isinstance(asset, dict):
                continue
            asset_id = f"asset:{vessel_key}:{asset['id']}"
            add_node(
                asset_id,
                "PhysicalAsset",
                str(asset.get("name")),
                vessel_key,
                {
                    "id": asset.get("id"),
                    "cbs_category": asset.get("cbs_category"),
                    "safety_function": asset.get("safety_function"),
                    "ecu_zone": asset.get("ecu_zone"),
                    "network_zone": asset.get("network_zone"),
                },
            )
            add_edge(vessel_id, asset_id, "hasAsset", vessel_key)

            firmware = asset.get("firmware") or {}
            if isinstance(firmware, dict) and firmware.get("id"):
                fw_id = f"firmware:{vessel_key}:{firmware['id']}"
                add_node(
                    fw_id,
                    "Firmware",
                    str(firmware.get("id")),
                    vessel_key,
                    {"version": firmware.get("version")},
                )
                add_edge(asset_id, fw_id, "runs", vessel_key)

                for link in firmware.get("contains") or []:
                    if not isinstance(link, dict):
                        continue
                    link_purl = str(link.get("purl") or "")
                    comp_id = purl_to_component_id.get(link_purl)
                    if comp_id:
                        add_edge(fw_id, comp_id, "contains", vessel_key)

    nodes = pl.DataFrame(node_rows, schema=NODE_SCHEMA) if node_rows else pl.DataFrame(schema=NODE_SCHEMA)
    edges = pl.DataFrame(edge_rows, schema=EDGE_SCHEMA) if edge_rows else pl.DataFrame(schema=EDGE_SCHEMA)
    nx_graph = to_networkx(nodes, edges)

    manifest = {
        "cve_snapshot": str(cve_snapshot_path or DEFAULT_CVE_SNAPSHOT),
        "sbom_dir": str(sbom_root),
        "vessel_keys": keys,
        "node_count": len(node_rows),
        "edge_count": len(edge_rows),
    }

    return GraphBuildResult(nodes=nodes, edges=edges, nx_graph=nx_graph, manifest=manifest)


def to_networkx(nodes: pl.DataFrame, edges: pl.DataFrame) -> nx.DiGraph:
    """Compile Parquet-style node/edge frames into a directed graph."""
    g = nx.DiGraph()
    for row in nodes.iter_rows(named=True):
        g.add_node(
            row["node_id"],
            node_type=row["node_type"],
            label=row["label"],
            vessel_key=row["vessel_key"],
        )
    for row in edges.iter_rows(named=True):
        g.add_edge(row["src_id"], row["dst_id"], rel_type=row["rel_type"])
    return g


def write_graph_parquet(
    result: GraphBuildResult,
    output_dir: Path | None = None,
    *,
    prefix: str = "maritime_cyber",
) -> dict[str, Path]:
    """Write nodes and edges Parquet under data/processed/maritime_cyber/."""
    out = Path(output_dir or DEFAULT_OUTPUT_DIR)
    out.mkdir(parents=True, exist_ok=True)
    nodes_path = out / f"{prefix}_graph_nodes.parquet"
    edges_path = out / f"{prefix}_graph_edges.parquet"
    result.nodes.write_parquet(nodes_path)
    result.edges.write_parquet(edges_path)
    manifest_path = out / f"{prefix}_graph_manifest.json"
    manifest_path.write_text(json.dumps(result.manifest, indent=2), encoding="utf-8")
    return {"nodes": nodes_path, "edges": edges_path, "manifest": manifest_path}


def affected_vessels_for_cve(
    nx_graph: nx.DiGraph,
    cve_node_id: str,
) -> list[str]:
    """UC2 reverse walk: CVE → component → firmware → asset → vessel."""
    if cve_node_id not in nx_graph:
        return []
    vessels: set[str] = set()
    for comp_id in nx_graph.predecessors(cve_node_id):
        for fw_id in nx_graph.predecessors(comp_id):
            if nx_graph.nodes[fw_id].get("node_type") != "Firmware":
                continue
            for asset_id in nx_graph.predecessors(fw_id):
                for vessel_id in nx_graph.predecessors(asset_id):
                    if nx_graph.nodes[vessel_id].get("node_type") == "Vessel":
                        vessels.add(nx_graph.nodes[vessel_id].get("vessel_key", vessel_id))
    return sorted(vessels)


def load_graph_from_parquet(
    nodes_path: Path,
    edges_path: Path,
) -> GraphBuildResult:
    """Reload graph from published Parquet files."""
    nodes = pl.read_parquet(nodes_path)
    edges = pl.read_parquet(edges_path)
    return GraphBuildResult(
        nodes=nodes,
        edges=edges,
        nx_graph=to_networkx(nodes, edges),
        manifest={"nodes": str(nodes_path), "edges": str(edges_path)},
    )
