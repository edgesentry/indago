"""Cross-tool smoke: indago evaluation manifest ↔ edgesentry-rs sign-clearance (W4)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from pipelines.maritime_cyber.eval import (
    _canonical_hash,
    evaluate_port_clearance,
    write_evaluation_artifacts,
)
from pipelines.maritime_cyber.graph import build_maritime_cyber_graph

# Fields required by edgesentry_audit::ClearanceManifestBody (W4).
W4_MANIFEST_KEYS = frozenset(
    {
        "vessel_key",
        "port_call_id",
        "rule_pack_id",
        "rule_pack_version",
        "rule_pack_sha256",
        "cve_snapshot_sha256",
        "sbom_sha256",
        "outcome",
        "rules_fired",
        "graph_node_count",
        "graph_edge_count",
        "decision_hash",
    }
)

PRIV_HEX = "0101010101010101010101010101010101010101010101010101010101010101"


def _eds_binary() -> str | None:
    candidate = os.environ.get("EDS_BIN") or shutil.which("eds")
    if not candidate:
        return None
    probe = subprocess.run(
        [candidate, "audit", "sign-clearance", "--help"],
        check=False,
        capture_output=True,
    )
    if probe.returncode != 0:
        pytest.skip(
            "eds lacks audit sign-clearance (build edgesentry-rs W4 branch and set EDS_BIN)"
        )
    return candidate


def test_evaluation_manifest_matches_w4_contract(tmp_path: Path) -> None:
    graph = build_maritime_cyber_graph(["vessel-hold"])
    result = evaluate_port_clearance("vessel-hold", graph_result=graph)
    paths = write_evaluation_artifacts(result, tmp_path)
    on_disk = json.loads(paths["manifest"].read_text(encoding="utf-8"))

    assert W4_MANIFEST_KEYS <= set(on_disk)
    assert on_disk["decision_hash"] == result.decision_hash
    assert on_disk["outcome"] == "hold"

    body = {k: v for k, v in on_disk.items() if k != "decision_hash"}
    assert _canonical_hash(body) == result.decision_hash


@pytest.mark.integration
def test_eds_sign_and_verify_clearance_chain(tmp_path: Path) -> None:
    eds = _eds_binary()
    if not eds:
        pytest.skip("eds binary not available (set EDS_BIN or install eds)")

    graph = build_maritime_cyber_graph(["vessel-hold"])
    result = evaluate_port_clearance("vessel-hold", graph_result=graph)
    paths = write_evaluation_artifacts(result, tmp_path)
    manifest = paths["manifest"]
    chain = tmp_path / "clearance_chain.json"

    sign = subprocess.run(
        [
            eds,
            "audit",
            "sign-clearance",
            "--manifest",
            str(manifest),
            "--key",
            PRIV_HEX,
            "--device-id",
            "port-clearance-poc",
            "--out",
            str(chain),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert sign.returncode == 0, sign.stderr

    verify_chain = subprocess.run(
        [eds, "audit", "verify-chain", "--records-file", str(chain)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert verify_chain.returncode == 0, verify_chain.stderr
    assert "CHAIN_VALID" in verify_chain.stdout

    verify_manifest = subprocess.run(
        [
            eds,
            "audit",
            "verify-clearance",
            "--manifest",
            str(manifest),
            "--chain",
            str(chain),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert verify_manifest.returncode == 0, verify_manifest.stderr
    assert "VERIFIED" in verify_manifest.stdout
