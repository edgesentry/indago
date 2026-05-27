"""G11/G12 — audit refs, drift detection, integrated snapshot fingerprint."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipelines.maritime_cyber.audit_refs import (
    ManifestDriftError,
    assert_manifest_audit_refs,
    audit_path_label,
    build_bom_baseline_ref,
    build_cve_snapshot_ref,
    integrated_snapshot_fingerprint,
    resolve_audit_path,
)
from pipelines.maritime_cyber.fleet_demo import (
    FLEET_DEMO_ASSET_MAP,
    FLEET_DEMO_CVE_SNAPSHOT,
    FLEET_DEMO_SBOM_DIR,
)
from pipelines.maritime_cyber.eval import evaluate_port_clearance, write_evaluation_artifacts
from pipelines.maritime_cyber.graph import build_maritime_cyber_graph


def test_manifest_includes_audit_refs_and_fingerprint() -> None:
    graph = build_maritime_cyber_graph(["vessel-hold"])
    result = evaluate_port_clearance("vessel-hold", graph_result=graph)
    assert "bom_baseline_ref" in result.manifest
    assert "cve_snapshot_ref" in result.manifest
    assert result.manifest["bom_baseline_ref"]["sbom_sha256"] == result.manifest["sbom_sha256"]
    assert (
        result.manifest["cve_snapshot_ref"]["cve_snapshot_sha256"]
        == result.manifest["cve_snapshot_sha256"]
    )
    assert len(result.manifest["integrated_snapshot_fingerprint"]) == 64
    assert result.facts["impacted_paths"]
    assert result.facts["bom_baseline_ref"] == result.manifest["bom_baseline_ref"]


def test_integrated_snapshot_written(tmp_path: Path) -> None:
    graph = build_maritime_cyber_graph(["vessel-hold"])
    result = evaluate_port_clearance("vessel-hold", graph_result=graph)
    paths = write_evaluation_artifacts(result, tmp_path)
    snap = paths["integrated_snapshot"]
    assert snap.is_file()
    body = json.loads(snap.read_text(encoding="utf-8"))
    assert body["integrated_snapshot_fingerprint"] == result.manifest["integrated_snapshot_fingerprint"]
    assert body["impacted_paths"]


def test_manifest_audit_refs_stable_across_reruns() -> None:
    graph = build_maritime_cyber_graph(["vessel-hold"])
    a = evaluate_port_clearance("vessel-hold", graph_result=graph)
    b = evaluate_port_clearance("vessel-hold", graph_result=graph)
    assert a.decision_hash == b.decision_hash
    assert_manifest_audit_refs(a.manifest, "vessel-hold")
    assert_manifest_audit_refs(b.manifest, "vessel-hold")


def test_manifest_drift_detects_tampered_sbom(tmp_path: Path) -> None:
    sbom_dir = tmp_path / "sbom"
    sbom_dir.mkdir()
    src = Path(__file__).resolve().parents[2] / "fixtures" / "sbom" / "vessel-hold.json"
    dst = sbom_dir / "vessel-hold.json"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    result = evaluate_port_clearance(
        "vessel-hold",
        graph_result=build_maritime_cyber_graph(["vessel-hold"], sbom_dir=sbom_dir),
        sbom_dir=sbom_dir,
    )
    assert_manifest_audit_refs(result.manifest, "vessel-hold", sbom_dir=sbom_dir)

    data = json.loads(dst.read_text(encoding="utf-8"))
    data["metadata"] = {"tampered": True}
    dst.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ManifestDriftError, match="bom_baseline_ref drift"):
        assert_manifest_audit_refs(result.manifest, "vessel-hold", sbom_dir=sbom_dir)


def test_integrated_snapshot_fingerprint_changes_on_outcome_change() -> None:
    hold = evaluate_port_clearance(
        "vessel-hold",
        graph_result=build_maritime_cyber_graph(["vessel-hold"]),
    )
    clean = evaluate_port_clearance(
        "vessel-clean",
        graph_result=build_maritime_cyber_graph(["vessel-clean"]),
    )
    assert integrated_snapshot_fingerprint(hold.manifest) != integrated_snapshot_fingerprint(
        clean.manifest
    )


def test_build_bom_baseline_ref_paths_exist() -> None:
    ref = build_bom_baseline_ref("vessel-hold")
    assert resolve_audit_path(ref["sbom_path"]).is_file()
    assert resolve_audit_path(ref["asset_map_path"]).is_file()
    assert len(ref["sbom_sha256"]) == 64


def test_audit_refs_use_repo_relative_paths_for_fleet_demo() -> None:
    ref = build_bom_baseline_ref(
        "fleet-hold-01",
        asset_map_path=FLEET_DEMO_ASSET_MAP,
        sbom_dir=FLEET_DEMO_SBOM_DIR,
    )
    assert ref["asset_map_path"] == audit_path_label(FLEET_DEMO_ASSET_MAP)
    assert ref["sbom_path"] == "fixtures/fleet-demo/sbom/fleet-hold-01.json"
    assert not Path(ref["asset_map_path"]).is_absolute()

    cve_ref = build_cve_snapshot_ref(cve_snapshot_path=FLEET_DEMO_CVE_SNAPSHOT)
    assert cve_ref["cve_snapshot_path"] == audit_path_label(FLEET_DEMO_CVE_SNAPSHOT)
