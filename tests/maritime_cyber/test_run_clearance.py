"""W6 — E2E run_clearance orchestration."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agents.port_clearance.run_clearance import (
    load_profile_manifest,
    run_clearance,
    run_hold_to_pass_scenario,
    verify_clearance_with_eds,
)


def _eds_with_sign_clearance() -> str | None:
    """Prefer sibling edgesentry-rs build when PATH eds lacks W4 subcommands."""
    repo_root = Path(__file__).resolve().parents[2]
    candidates: list[str] = []
    sibling = repo_root.parent / "edgesentry-rs" / "target" / "debug" / "eds"
    if sibling.is_file():
        candidates.append(str(sibling))
    for name in (os.environ.get("EDS_BIN"), shutil.which("eds")):
        if name and name not in candidates:
            candidates.append(name)

    for eds in candidates:
        probe = subprocess.run(
            [eds, "audit", "sign-clearance", "--help"],
            capture_output=True,
            check=False,
        )
        if probe.returncode == 0:
            return eds
    return None


def test_load_profile_manifest() -> None:
    profile = load_profile_manifest()
    assert profile["profile_id"] == "maritime_cyber"
    assert profile["pipelines"]["evaluate"] == "port_clearance_eval"


@pytest.mark.parametrize(
    "vessel_key,expected_outcome",
    [
        ("vessel-hold", "hold"),
        ("vessel-clean", "pass"),
    ],
)
def test_run_clearance_eval_only(tmp_path: Path, vessel_key: str, expected_outcome: str) -> None:
    """Deterministic path without eds (CI-safe)."""
    result = run_clearance(
        vessel_key,
        output_dir=tmp_path / vessel_key,
        write_graph=False,
        skip_render=True,
        skip_seal=True,
    )
    assert result.outcome == expected_outcome
    assert result.facts_path.is_file()
    assert result.manifest_path.is_file()
    assert len(result.decision_hash) == 64

    facts = json.loads(result.facts_path.read_text(encoding="utf-8"))
    assert facts["outcome"] == expected_outcome

    summary_path = tmp_path / vessel_key / f"{vessel_key}_port-call-demo-sgsin_run_summary.json"
    assert summary_path.is_file()


def test_ai_narrative_does_not_change_decision_hash(tmp_path: Path) -> None:
    """D5: operator explanation is sidecar-only; facts hash unchanged."""
    baseline = run_clearance(
        "vessel-hold",
        output_dir=tmp_path / "without",
        write_graph=False,
        skip_render=True,
        skip_seal=True,
        ai_narrative=False,
    )
    with_narrative = run_clearance(
        "vessel-hold",
        output_dir=tmp_path / "with",
        write_graph=False,
        skip_render=True,
        skip_seal=True,
        ai_narrative=True,
    )
    assert baseline.decision_hash == with_narrative.decision_hash
    assert with_narrative.operator_explanation_path is not None
    assert with_narrative.operator_explanation_path.is_file()
    baseline_facts = json.loads(baseline.facts_path.read_text(encoding="utf-8"))
    narrative_facts = json.loads(with_narrative.facts_path.read_text(encoding="utf-8"))
    assert baseline_facts == narrative_facts


def test_hold_to_pass_scenario_eval_only(tmp_path: Path) -> None:
    """D1: E7 -> E9 -> E10 -> re-E7 without eds (CI-safe)."""
    results = run_hold_to_pass_scenario(
        "vessel-hold",
        output_dir=tmp_path / "scenario",
        skip_render=True,
        skip_seal=True,
        worm_root=tmp_path / "worm",
    )
    assert results["baseline"].outcome == "hold"
    assert results["remediated"].outcome == "pass"
    assert results["baseline"].decision_hash != results["remediated"].decision_hash
    assert results["e9_vessels"] == ["vessel-hold"]

    run_root = results["run_root"]
    assert (run_root / "e9_affected_vessels.json").is_file()
    assert (run_root / "e10_remediation.json").is_file()
    scenario = json.loads((run_root / "scenario_summary.json").read_text(encoding="utf-8"))
    assert scenario["lifecycle_sequence"] == ["E7", "E9", "E10", "E7"]
    assert scenario["decision_hash_continuity"]["baseline"] == results["baseline"].decision_hash

    remediated_summary = json.loads(
        next(results["remediated"].output_dir.glob("*_run_summary.json")).read_text(encoding="utf-8")
    )
    assert remediated_summary["prior_decision_hash"] == results["baseline"].decision_hash
    assert remediated_summary["lifecycle_event"] == "E7"
    assert "run_at" in remediated_summary


@pytest.mark.integration
def test_hold_to_pass_scenario_verify_clearance_both_runs(tmp_path: Path) -> None:
    """D1-4: verify-clearance passes on baseline and remediated manifests."""
    eds = _eds_with_sign_clearance()
    if not eds:
        pytest.skip("eds with sign-clearance / verify-clearance not available")

    results = run_hold_to_pass_scenario(
        "vessel-hold",
        output_dir=tmp_path / "scenario",
        skip_render=True,
        skip_seal=False,
        eds_bin=eds,
        worm_root=tmp_path / "worm",
    )
    eds_path = Path(eds)
    for label in ("baseline", "remediated"):
        run = results[label]
        assert run.chain_path is not None and run.chain_path.is_file()
        out = verify_clearance_with_eds(
            manifest_path=run.manifest_path,
            chain_path=run.chain_path,
            eds=eds_path,
        )
        assert "VERIFIED" in out
        summary = json.loads(next(run.output_dir.glob("*_run_summary.json")).read_text(encoding="utf-8"))
        assert summary["verify_clearance"] == "ok"

    assert results["e9_vessels"] == ["vessel-hold"]


@pytest.mark.integration
def test_run_clearance_full_e2e(tmp_path: Path) -> None:
    eds = os.environ.get("EDS_BIN") or shutil.which("eds")
    sibling = (
        Path(__file__).resolve().parents[2].parent / "edgesentry-rs" / "target" / "debug" / "eds"
    )
    if not eds and sibling.is_file():
        eds = str(sibling)
    if not eds:
        pytest.skip("eds not available")

    probe = __import__("subprocess").run(
        [eds, "document", "render-clearance", "--help"],
        capture_output=True,
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip("eds lacks W5 render-clearance")

    result = run_clearance(
        "vessel-hold",
        output_dir=tmp_path / "hold",
        write_graph=False,
        eds_bin=eds,
    )
    assert result.outcome == "hold"
    assert result.html_path is not None and result.html_path.is_file()
    assert result.chain_path is not None and result.chain_path.is_file()
    html = result.html_path.read_text(encoding="utf-8")
    assert "HOLD" in html
    assert result.verify_url in html
