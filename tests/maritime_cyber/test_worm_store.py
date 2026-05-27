"""D3 — mock WORM publish and retention verification (G11)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.port_clearance.run_clearance import run_clearance
from agents.port_clearance.worm_store import (
    WormTamperError,
    publish_clearance_run,
    tamper_worm_object,
    verify_retention,
)


def test_run_clearance_publishes_worm_record(tmp_path: Path) -> None:
    worm_root = tmp_path / "worm"
    result = run_clearance(
        "vessel-hold",
        output_dir=tmp_path / "hold",
        write_graph=False,
        skip_render=True,
        skip_seal=True,
        worm_root=worm_root,
    )
    assert result.worm_publish_path is not None
    assert result.worm_publish_path.is_file()

    record = json.loads(result.worm_publish_path.read_text(encoding="utf-8"))
    assert record["storage_target"] == "mock"
    assert len(record["objects"]) >= 2
    keys = {o["object_key"] for o in record["objects"]}
    assert "evaluation_manifest.json" in keys
    assert "integrated_snapshot.json" in keys

    verified = verify_retention(result.worm_publish_path, worm_root=worm_root)
    assert verified["status"] == "verified"
    assert verified["manifest_audit_refs"] == "ok"


def test_publish_refuses_object_lock_violation(tmp_path: Path) -> None:
    worm_root = tmp_path / "worm"
    source = tmp_path / "artifact.json"
    source.write_text('{"v":1}', encoding="utf-8")

    namespace_hash = "a" * 64
    manifest_v1 = tmp_path / "manifest_v1.json"
    manifest_v1.write_text(
        json.dumps({"decision_hash": namespace_hash, "vessel_key": "vessel-hold", "v": 1}),
        encoding="utf-8",
    )
    publish_clearance_run(
        tmp_path / "run1",
        prefix="vessel-hold_pc1",
        manifest_path=manifest_v1,
        worm_root=worm_root,
    )

    manifest_v2 = tmp_path / "manifest_v2.json"
    manifest_v2.write_text(
        json.dumps({"decision_hash": namespace_hash, "vessel_key": "vessel-hold", "v": 2}),
        encoding="utf-8",
    )
    with pytest.raises(WormTamperError, match="object-lock"):
        publish_clearance_run(
            tmp_path / "run2",
            prefix="vessel-hold_pc1",
            manifest_path=manifest_v2,
            worm_root=worm_root,
        )


def test_verify_retention_fails_after_tamper(tmp_path: Path) -> None:
    worm_root = tmp_path / "worm"
    result = run_clearance(
        "vessel-hold",
        output_dir=tmp_path / "hold",
        write_graph=False,
        skip_render=True,
        skip_seal=True,
        worm_root=worm_root,
    )
    assert result.worm_publish_path is not None
    tamper_worm_object(result.worm_publish_path, "integrated_snapshot.json", worm_root=worm_root)

    with pytest.raises(WormTamperError, match="hash mismatch"):
        verify_retention(result.worm_publish_path, worm_root=worm_root)


def test_skip_worm_skips_publish_record(tmp_path: Path) -> None:
    result = run_clearance(
        "vessel-hold",
        output_dir=tmp_path / "hold",
        write_graph=False,
        skip_render=True,
        skip_seal=True,
        skip_worm=True,
    )
    assert result.worm_publish_path is None
