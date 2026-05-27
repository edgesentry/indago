#!/usr/bin/env python3
"""W8 — generate demo-enhanced fleet fixtures (seeded, reproducible)."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipelines.maritime_cyber.eval import evaluate_port_clearance  # noqa: E402
from pipelines.maritime_cyber.fleet_demo import (  # noqa: E402
    FLEET_DEMO_ASSET_MAP,
    FLEET_DEMO_CVE_SNAPSHOT,
    FLEET_DEMO_MANIFEST,
    FLEET_DEMO_ROOT,
    FLEET_DEMO_SBOM_DIR,
)
from pipelines.maritime_cyber.graph import build_maritime_cyber_graph  # noqa: E402
from pipelines.maritime_cyber.rules import validate_asset_map  # noqa: E402

# Demo-enhanced tier (scale-up-plan): 12 vessels, multi-asset, ~25 SBOM components each.
FLEET_SIZE = 12
COMPONENTS_PER_VESSEL = 25

ASSET_CATALOG: list[dict[str, str]] = [
    {
        "id": "ecdis-01",
        "name": "ECDIS Workstation",
        "cbs_category": "navigation",
        "safety_function": "essential",
        "ecu_zone": "bridge_nav",
        "network_zone": "zone_1",
    },
    {
        "id": "radar-01",
        "name": "X-Band Radar Processor",
        "cbs_category": "navigation",
        "safety_function": "important",
        "ecu_zone": "bridge_nav",
        "network_zone": "zone_1",
    },
    {
        "id": "vdr-01",
        "name": "Voyage Data Recorder",
        "cbs_category": "navigation",
        "safety_function": "essential",
        "ecu_zone": "bridge_nav",
        "network_zone": "zone_1",
    },
    {
        "id": "ams-01",
        "name": "Alarm Management Server",
        "cbs_category": "other",
        "safety_function": "important",
        "ecu_zone": "engine_room",
        "network_zone": "zone_2",
    },
    {
        "id": "comms-01",
        "name": "SATCOM Gateway",
        "cbs_category": "communications",
        "safety_function": "normal",
        "ecu_zone": "comms_closet",
        "network_zone": "zone_3",
    },
    {
        "id": "eng-01",
        "name": "Engine Control Unit",
        "cbs_category": "propulsion",
        "safety_function": "essential",
        "ecu_zone": "engine_room",
        "network_zone": "zone_2",
    },
]

# (name, maven coord suffix, hold_version, pass_version)
MAVEN_LIBS: list[tuple[str, str, str, str]] = [
    ("log4j-core", "org.apache.logging.log4j/log4j-core", "2.14.1", "2.23.1"),
    ("spring-core", "org.springframework/spring-core", "5.3.27", "5.3.39"),
    ("jackson-databind", "com.fasterxml.jackson.core/jackson-databind", "2.13.4", "2.15.4"),
    ("netty-handler", "io.netty/netty-handler", "4.1.86.Final", "4.1.100.Final"),
    ("tomcat-embed-core", "org.apache.tomcat.embed/tomcat-embed-core", "9.0.70", "9.0.90"),
    ("commons-compress", "org.apache.commons/commons-compress", "1.21", "1.26.0"),
    ("guava", "com.google.guava/guava", "31.1-jre", "32.1.3-jre"),
    ("snakeyaml", "org.yaml/snakeyaml", "1.33", "2.2"),
    ("bouncycastle-prov", "org.bouncycastle/bcprov-jdk15on", "1.70", "1.78.1"),
    ("hibernate-core", "org.hibernate/hibernate-core", "5.6.14.Final", "5.6.15.Final"),
]

HOLD_REASON_LOG4J = "log4j_navigation_ecdis"
HOLD_REASON_NO_SUPPLIER = "sbom_missing_supplier"
HOLD_REASON_NO_ZONE = "asset_map_missing_zone"


def _purl(coord: str, version: str) -> str:
    return f"pkg:maven/{coord}@{version}"


def _build_cve_snapshot() -> dict[str, Any]:
    """Pinned OSV subset — Log4Shell KEV + representative high-severity entries."""
    return {
        "snapshot_id": "fleet-demo-2026-05-27",
        "schema": "OSV",
        "description": "Demo-enhanced pinned subset for fleet-demo fixtures (synthetic SBOM linkage)",
        "vulnerabilities": [
            {
                "id": "GHSA-jfhr-c2vg-8q4j",
                "aliases": ["CVE-2021-44228"],
                "summary": "Apache Log4j2 remote code execution (Log4Shell)",
                "severity": "CRITICAL",
                "database_specific": {"cvss_score": 10.0, "in_kev": True},
                "affected": [
                    {
                        "package": {
                            "ecosystem": "Maven",
                            "name": "org.apache.logging.log4j:log4j-core",
                        },
                        "ranges": [
                            {
                                "type": "ECOSYSTEM",
                                "events": [
                                    {"introduced": "2.0-beta9"},
                                    {"fixed": "2.15.0"},
                                ],
                            }
                        ],
                    }
                ],
            },
            {
                "id": "GHSA-4wrc-f8pq-fpwx",
                "aliases": ["CVE-2022-22965"],
                "summary": "Spring Framework RCE (Spring4Shell) — demo path not wired by default",
                "severity": "CRITICAL",
                "database_specific": {"cvss_score": 9.8, "in_kev": False},
                "affected": [
                    {
                        "package": {
                            "ecosystem": "Maven",
                            "name": "org.springframework:spring-core",
                        },
                        "ranges": [
                            {
                                "type": "ECOSYSTEM",
                                "events": [
                                    {"introduced": "5.3.0"},
                                    {"fixed": "5.3.18"},
                                ],
                            }
                        ],
                    }
                ],
            },
            {
                "id": "GHSA-vmq6-5fm6-3xx7",
                "aliases": ["CVE-2020-36518"],
                "summary": "Jackson-databind denial of service",
                "severity": "HIGH",
                "database_specific": {"cvss_score": 7.5, "in_kev": False},
                "affected": [
                    {
                        "package": {
                            "ecosystem": "Maven",
                            "name": "com.fasterxml.jackson.core:jackson-databind",
                        },
                        "ranges": [
                            {
                                "type": "ECOSYSTEM",
                                "events": [
                                    {"introduced": "2.0.0"},
                                    {"fixed": "2.13.4.2"},
                                ],
                            }
                        ],
                    }
                ],
            },
        ],
    }


def _vessel_plan(seed: int) -> list[dict[str, str]]:
    rng = random.Random(seed)
    plans: list[dict[str, str]] = []
    hold_patterns = [HOLD_REASON_LOG4J] * 4 + [HOLD_REASON_NO_SUPPLIER, HOLD_REASON_NO_ZONE]
    pass_count = FLEET_SIZE - len(hold_patterns)
    for i, reason in enumerate(hold_patterns):
        plans.append(
            {
                "vessel_key": f"fleet-hold-{i + 1:02d}",
                "pattern": reason,
                "expected_outcome": "hold",
            }
        )
    for j in range(pass_count):
        plans.append(
            {
                "vessel_key": f"fleet-pass-{j + 1:02d}",
                "pattern": "pass",
                "expected_outcome": "pass",
            }
        )
    rng.shuffle(plans)
    return plans


def _sbom_components(
    vessel_key: str,
    pattern: str,
    rng: random.Random,
) -> list[dict[str, Any]]:
    libs = list(MAVEN_LIBS)
    rng.shuffle(libs)
    selected = libs[:COMPONENTS_PER_VESSEL]
    components: list[dict[str, Any]] = []
    use_hold_versions = pattern in (HOLD_REASON_LOG4J, HOLD_REASON_NO_SUPPLIER, HOLD_REASON_NO_ZONE)

    for name, coord, hold_ver, pass_ver in selected:
        version = hold_ver if use_hold_versions else pass_ver
        comp: dict[str, Any] = {
            "type": "library",
            "name": name,
            "version": version,
            "purl": _purl(coord, version),
            "supplier": {"name": "Synthetic Vendor Co."},
        }
        if pattern == HOLD_REASON_NO_SUPPLIER and name == "log4j-core":
            comp.pop("supplier", None)
        components.append(comp)

    # Pad to COMPONENTS_PER_VESSEL with benign filler libs (pass versions only)
    filler_idx = 0
    while len(components) < COMPONENTS_PER_VESSEL:
        name, coord, hold_ver, pass_ver = MAVEN_LIBS[filler_idx % len(MAVEN_LIBS)]
        filler_idx += 1
        version = pass_ver
        components.append(
            {
                "type": "library",
                "name": f"{name}-f{filler_idx}",
                "version": version,
                "purl": _purl(coord, version),
                "supplier": {"name": "Synthetic Vendor Co."},
            }
        )
    return components


def _physical_assets(pattern: str, log4j_version: str) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for template in ASSET_CATALOG:
        asset = dict(template)
        asset["manufacturer"] = "Demo Marine Electronics"
        fw_id = f"{asset['id']}-fw-2024"
        firmware: dict[str, Any] = {
            "id": fw_id,
            "version": "2024.1",
            "contains": [],
        }
        if asset["id"] == "ecdis-01":
            ver = log4j_version
            firmware["contains"] = [
                {
                    "purl": _purl("org.apache.logging.log4j/log4j-core", ver),
                    "component_name": "log4j-core",
                }
            ]
        elif asset["id"] == "radar-01":
            firmware["contains"] = [
                {
                    "purl": _purl("org.springframework/spring-core", "5.3.39"),
                    "component_name": "spring-core",
                }
            ]
        asset["firmware"] = firmware
        if pattern == HOLD_REASON_NO_ZONE and asset["id"] == "radar-01":
            asset["ecu_zone"] = ""
            asset["network_zone"] = ""
        assets.append(asset)
    return assets


def _build_asset_map(plans: list[dict[str, str]], seed: int) -> dict[str, Any]:
    rng = random.Random(seed + 1)
    vessels: dict[str, Any] = {}
    for idx, plan in enumerate(plans):
        key = plan["vessel_key"]
        pattern = plan["pattern"]
        log4j_ver = "2.23.1" if pattern == "pass" else "2.14.1"
        vessels[key] = {
            "imo": f"IMO9991{idx + 1:03d}",
            "display_name": key.replace("-", " ").title(),
            "physical_assets": _physical_assets(pattern, log4j_ver),
        }
        _ = rng  # reserved for future per-vessel asset shuffle
    return {
        "version": "0.1.0",
        "synthetic": True,
        "tier": "demo-enhanced",
        "generator_seed": seed,
        "vessels": vessels,
    }


def _write_sboms(plans: list[dict[str, str]], seed: int, sbom_dir: Path) -> None:
    sbom_dir.mkdir(parents=True, exist_ok=True)
    for plan in plans:
        key = plan["vessel_key"]
        vessel_rng = random.Random(f"{seed}:{key}")
        components = _sbom_components(key, plan["pattern"], vessel_rng)
        doc = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "serialNumber": f"urn:uuid:{key}-demo",
            "version": 1,
            "metadata": {
                "component": {
                    "type": "application",
                    "name": f"{key}-stack",
                    "version": "2024.1",
                }
            },
            "components": components,
        }
        path = sbom_dir / f"{key}.json"
        path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def generate(seed: int, out_root: Path) -> dict[str, Any]:
    plans = _vessel_plan(seed)
    asset_map = _build_asset_map(plans, seed)

    out_root.mkdir(parents=True, exist_ok=True)
    cve_dir = out_root / "cve"
    cve_dir.mkdir(parents=True, exist_ok=True)
    sbom_dir = out_root / "sbom"

    asset_map_path = out_root / "asset_map.yaml"
    asset_map_path.write_text(
        yaml.safe_dump(asset_map, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    cve_path = cve_dir / "snapshot-fleet-demo.json"
    cve_doc = _build_cve_snapshot()
    cve_path.write_text(json.dumps(cve_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    _write_sboms(plans, seed, sbom_dir)

    errors = validate_asset_map(asset_map)
    if errors:
        raise ValueError(f"asset_map validation failed: {errors}")

    manifest: dict[str, Any] = {
        "tier": "demo-enhanced",
        "generator_seed": seed,
        "vessel_count": len(plans),
        "components_per_vessel": COMPONENTS_PER_VESSEL,
        "assets_per_vessel": len(ASSET_CATALOG),
        "cve_snapshot": "cve/snapshot-fleet-demo.json",
        "asset_map": "asset_map.yaml",
        "sbom_dir": "sbom",
        "vessels": [
            {
                "vessel_key": p["vessel_key"],
                "expected_outcome": p["expected_outcome"],
                "hold_pattern": p["pattern"],
            }
            for p in plans
        ],
    }
    return manifest


def verify_fleet(manifest: dict[str, Any], out_root: Path) -> dict[str, Any]:
    """Run eval for each vessel; attach actual outcome and decision_hash."""
    asset_map = out_root / "asset_map.yaml"
    sbom_dir = out_root / "sbom"
    cve_path = out_root / manifest["cve_snapshot"]

    updated: list[dict[str, Any]] = []
    total_nodes = 0
    total_edges = 0
    for entry in manifest["vessels"]:
        key = str(entry["vessel_key"])
        graph = build_maritime_cyber_graph(
            [key],
            asset_map_path=asset_map,
            cve_snapshot_path=cve_path,
            sbom_dir=sbom_dir,
        )
        total_nodes += len(graph.nodes)
        total_edges += len(graph.edges)
        result = evaluate_port_clearance(
            key,
            port_call_id="port-call-fleet-demo",
            graph_result=graph,
            asset_map_path=asset_map,
            cve_snapshot_path=cve_path,
            sbom_dir=sbom_dir,
        )
        row = dict(entry)
        row["actual_outcome"] = result.outcome
        row["decision_hash"] = result.decision_hash
        row["rules_fired_count"] = len(result.rules_fired)
        if row["actual_outcome"] != row["expected_outcome"]:
            raise ValueError(
                f"{key}: expected {row['expected_outcome']}, got {row['actual_outcome']}"
            )
        updated.append(row)

    manifest = dict(manifest)
    manifest["vessels"] = updated
    manifest["graph_node_count"] = total_nodes
    manifest["graph_edge_count"] = total_edges
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate fleet-demo maritime cyber fixtures (W8)")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed (default: 42)")
    parser.add_argument(
        "--out",
        type=Path,
        default=FLEET_DEMO_ROOT,
        help="Output directory (default: fixtures/fleet-demo)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run port_clearance_eval and record decision_hash per vessel",
    )
    args = parser.parse_args(argv)

    manifest = generate(args.seed, args.out)
    if args.verify:
        manifest = verify_fleet(manifest, args.out)

    manifest_path = args.out / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"wrote {args.out}/asset_map.yaml")
    print(f"wrote {args.out}/cve/snapshot-fleet-demo.json")
    print(f"wrote {len(manifest['vessels'])} SBOMs under {args.out}/sbom/")
    print(f"wrote {manifest_path}")
    if args.verify:
        holds = sum(1 for v in manifest["vessels"] if v["actual_outcome"] == "hold")
        print(f"verified: {len(manifest['vessels'])} vessels ({holds} hold)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
