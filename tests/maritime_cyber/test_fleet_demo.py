"""W8 — demo-enhanced fleet fixtures and fleet-wide evaluation."""

from __future__ import annotations

import pytest

from pipelines.maritime_cyber.eval import evaluate_port_clearance
from pipelines.maritime_cyber.fleet_demo import (
    FLEET_DEMO_ASSET_MAP,
    FLEET_DEMO_CVE_SNAPSHOT,
    FLEET_DEMO_SBOM_DIR,
    fleet_demo_available,
    fleet_demo_vessel_keys,
    load_fleet_demo_manifest,
)
from pipelines.maritime_cyber.graph import build_maritime_cyber_graph
from pipelines.maritime_cyber.rules import validate_asset_map

pytestmark = pytest.mark.skipif(
    not fleet_demo_available(),
    reason="fixtures/fleet-demo not generated — run scripts/generate_maritime_cyber_fixtures.py --verify",
)


def test_fleet_demo_manifest_shape() -> None:
    manifest = load_fleet_demo_manifest()
    assert manifest["tier"] == "demo-enhanced"
    assert manifest["vessel_count"] >= 10
    vessels = manifest["vessels"]
    assert len(vessels) == manifest["vessel_count"]
    for v in vessels:
        assert v["vessel_key"]
        assert v["expected_outcome"] in ("hold", "pass")
        assert len(v["decision_hash"]) == 64


def test_fleet_demo_asset_map_valid() -> None:
    import yaml

    asset_map = yaml.safe_load(FLEET_DEMO_ASSET_MAP.read_text(encoding="utf-8"))
    errors = validate_asset_map(asset_map)
    assert errors == []
    assert len(asset_map["vessels"]) >= 10


def test_fleet_demo_graph_builds_all_vessels() -> None:
    keys = [v["vessel_key"] for v in load_fleet_demo_manifest()["vessels"]]
    result = build_maritime_cyber_graph(
        keys,
        asset_map_path=FLEET_DEMO_ASSET_MAP,
        cve_snapshot_path=FLEET_DEMO_CVE_SNAPSHOT,
        sbom_dir=FLEET_DEMO_SBOM_DIR,
    )
    assert len(result.manifest["vessel_keys"]) == len(keys)
    assert result.nx_graph.number_of_nodes() > len(keys) * 5


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if metafunc.definition.name == "test_fleet_vessel_outcome_and_hash":
        if not fleet_demo_available():
            return
        manifest = load_fleet_demo_manifest()
        cases = [(v["vessel_key"], v["expected_outcome"], v["decision_hash"]) for v in manifest["vessels"]]
        metafunc.parametrize(
            "vessel_key,expected_outcome,expected_hash",
            cases,
            ids=[c[0] for c in cases],
        )


def test_fleet_vessel_outcome_and_hash(
    vessel_key: str,
    expected_outcome: str,
    expected_hash: str,
) -> None:
    graph = build_maritime_cyber_graph(
        [vessel_key],
        asset_map_path=FLEET_DEMO_ASSET_MAP,
        cve_snapshot_path=FLEET_DEMO_CVE_SNAPSHOT,
        sbom_dir=FLEET_DEMO_SBOM_DIR,
    )
    result = evaluate_port_clearance(
        vessel_key,
        port_call_id="port-call-fleet-demo",
        graph_result=graph,
        asset_map_path=FLEET_DEMO_ASSET_MAP,
        cve_snapshot_path=FLEET_DEMO_CVE_SNAPSHOT,
        sbom_dir=FLEET_DEMO_SBOM_DIR,
    )
    assert result.outcome == expected_outcome
    assert result.decision_hash == expected_hash


def test_fleet_hold_count_in_range() -> None:
    manifest = load_fleet_demo_manifest()
    holds = [v for v in manifest["vessels"] if v["expected_outcome"] == "hold"]
    assert 3 <= len(holds) <= 6


def test_fleet_log4j_affected_subset() -> None:
    from pipelines.maritime_cyber.eval import affected_vessels

    graph = build_maritime_cyber_graph(
        fleet_demo_vessel_keys(),
        asset_map_path=FLEET_DEMO_ASSET_MAP,
        cve_snapshot_path=FLEET_DEMO_CVE_SNAPSHOT,
        sbom_dir=FLEET_DEMO_SBOM_DIR,
    )
    affected = set(affected_vessels("CVE-2021-44228", graph_result=graph))
    manifest = load_fleet_demo_manifest()
    hold_log4j = {
        v["vessel_key"]
        for v in manifest["vessels"]
        if v.get("hold_pattern") == "log4j_navigation_ecdis"
    }
    pass_keys = {v["vessel_key"] for v in manifest["vessels"] if v["expected_outcome"] == "pass"}
    assert hold_log4j.issubset(affected)
    assert not pass_keys & affected
