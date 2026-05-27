"""W6 — E2E run_clearance orchestration."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from agents.port_clearance.run_clearance import (
    load_profile_manifest,
    run_clearance,
    run_hold_to_pass_scenario,
)


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


def test_hold_to_pass_scenario_eval_only(tmp_path: Path) -> None:
    """D1: hold -> remediation -> pass without eds (CI-safe)."""
    results = run_hold_to_pass_scenario(
        "vessel-hold",
        output_dir=tmp_path / "scenario",
        skip_render=True,
        skip_seal=True,
    )
    assert results["baseline"].outcome == "hold"
    assert results["remediated"].outcome == "pass"
    assert results["baseline"].decision_hash != results["remediated"].decision_hash


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
