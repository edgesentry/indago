"""D4 — export_vessel_graph impacted path JSON + HTML."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.port_clearance.run_clearance import run_clearance
import pipelines.export_vessel_graph as evg
from pipelines.maritime_cyber.eval import evaluate_port_clearance
from pipelines.maritime_cyber.graph import build_maritime_cyber_graph

CVE_LOG4SHELL = "CVE-2021-44228"


def test_hold_vessel_has_log4j_path() -> None:
    paths = evg.build_impacted_paths("vessel-hold")
    assert len(paths) >= 1
    assert any(CVE_LOG4SHELL in (p.get("cve_id") or "") for p in paths)
    assert paths[0]["component_purl"]
    assert paths[0]["path_nodes"]


def test_clean_vessel_has_no_impacted_paths() -> None:
    paths = evg.build_impacted_paths("vessel-clean")
    assert paths == []


def test_export_json_is_deterministic(tmp_path: Path) -> None:
    graph = build_maritime_cyber_graph(["vessel-hold"])
    eval_result = evaluate_port_clearance("vessel-hold", graph_result=graph)
    prefix = "vessel-hold_port-call-demo-sgsin"

    a = evg.write_vessel_graph_artifacts(
        "vessel-hold",
        tmp_path / "a",
        prefix=prefix,
        impacted_paths=eval_result.facts["impacted_paths"],
        outcome="hold",
    )
    b = evg.write_vessel_graph_artifacts(
        "vessel-hold",
        tmp_path / "b",
        prefix=prefix,
        impacted_paths=eval_result.facts["impacted_paths"],
        outcome="hold",
    )
    assert a["json"].read_bytes() == b["json"].read_bytes()


def test_html_contains_hold_path_and_disclaimer(tmp_path: Path) -> None:
    graph = build_maritime_cyber_graph(["vessel-hold"])
    eval_result = evaluate_port_clearance("vessel-hold", graph_result=graph)
    written = evg.write_vessel_graph_artifacts(
        "vessel-hold",
        tmp_path,
        prefix="vessel-hold_pc",
        impacted_paths=eval_result.facts["impacted_paths"],
        outcome="hold",
    )
    html = written["html"].read_text(encoding="utf-8")
    assert "log4j-core" in html or "GHSA" in html
    assert CVE_LOG4SHELL in html or "GHSA-jfhr" in html
    assert "synthetic SBOM" in html
    assert written["html"].is_file()


def test_paths_match_facts_impacted_paths() -> None:
    graph = build_maritime_cyber_graph(["vessel-hold"])
    eval_result = evaluate_port_clearance("vessel-hold", graph_result=graph)
    built = evg.build_impacted_paths("vessel-hold", graph_result=graph)
    assert built == eval_result.facts["impacted_paths"]


def test_run_clearance_writes_graph_exports(tmp_path: Path) -> None:
    run_clearance(
        "vessel-hold",
        output_dir=tmp_path / "hold",
        write_graph=False,
        skip_render=True,
        skip_seal=True,
        skip_worm=True,
    )
    prefix = "vessel-hold_port-call-demo-sgsin"
    json_path = tmp_path / "hold" / f"{prefix}_impacted_paths.json"
    html_path = tmp_path / "hold" / f"{prefix}_impacted-path.html"
    assert json_path.is_file()
    assert html_path.is_file()
    doc = json.loads(json_path.read_text(encoding="utf-8"))
    assert doc["impacted_paths"]


def test_render_pass_vessel_empty_paths() -> None:
    doc = evg.export_impacted_paths_document("vessel-clean", [], outcome="pass")
    html = evg.render_impacted_paths_html(doc)
    assert "No impacted vulnerability paths" in html


def test_copy_impacted_path_html_writes_bundle(tmp_path: Path) -> None:
    src = tmp_path / "src.html"
    dest_dir = tmp_path / "bundle"
    src.write_text("<p>hold path</p>", encoding="utf-8")

    copied = evg._copy_impacted_path_html(src, "vessel-hold", dest_dir)

    assert copied == dest_dir / "vessel-hold_impacted-path.html"
    assert copied is not None
    assert copied.read_text(encoding="utf-8") == src.read_text(encoding="utf-8")


def test_copy_impacted_path_html_skips_missing_parent(tmp_path: Path) -> None:
    src = tmp_path / "src.html"
    src.write_text("<p>x</p>", encoding="utf-8")
    dest_dir = tmp_path / "no_such_parent" / "bundle"

    assert evg._copy_impacted_path_html(src, "vessel-hold", dest_dir) is None


def test_write_vessel_graph_artifacts_copy_to_documaris_dist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "documaris-dist"
    monkeypatch.setattr(evg, "_DOCUMARIS_DIST", bundle)

    graph = build_maritime_cyber_graph(["vessel-hold"])
    eval_result = evaluate_port_clearance("vessel-hold", graph_result=graph)
    written = evg.write_vessel_graph_artifacts(
        "vessel-hold",
        tmp_path / "out",
        prefix="vessel-hold_pc",
        impacted_paths=eval_result.facts["impacted_paths"],
        outcome="hold",
        copy_to_documaris_dist=True,
    )

    assert written["documaris_dist_html"] == bundle / "vessel-hold_impacted-path.html"
    assert "capvista_submission_html" not in written


def test_write_vessel_graph_artifacts_copy_to_capvista_submission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "capvista-artefacts"
    monkeypatch.setattr(evg, "_CAPVISTA_SUBMISSION_ARTEFACTS", bundle)

    graph = build_maritime_cyber_graph(["vessel-hold"])
    eval_result = evaluate_port_clearance("vessel-hold", graph_result=graph)
    written = evg.write_vessel_graph_artifacts(
        "vessel-hold",
        tmp_path / "out",
        prefix="vessel-hold_pc",
        impacted_paths=eval_result.facts["impacted_paths"],
        outcome="hold",
        copy_to_capvista_submission=True,
    )

    assert written["capvista_submission_html"] == bundle / "vessel-hold_impacted-path.html"
    assert "documaris_dist_html" not in written
