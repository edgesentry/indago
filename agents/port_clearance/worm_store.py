"""G11 — mock WORM / append-only storage for clearance artefacts (Cap Vista D3)."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipelines.maritime_cyber.audit_refs import assert_manifest_audit_refs, file_sha256
from pipelines.maritime_cyber.graph import DEFAULT_OUTPUT_DIR

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORM_ROOT = DEFAULT_OUTPUT_DIR / "worm_store" / "clearance"


class WormTamperError(ValueError):
    """Stored object was modified or replaced (object-lock violation)."""


class WormRetentionError(ValueError):
    """Retention verification failed."""


@dataclass(frozen=True)
class WormObjectRecord:
    object_key: str
    source_path: str
    storage_path: str
    sha256: str
    size_bytes: int


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def resolve_worm_root(explicit: Path | str | None = None) -> Path:
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("CLEARANCE_WORM_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_WORM_ROOT.resolve()


def _storage_target_label(worm_root: Path) -> str:
    if os.environ.get("CLEARANCE_WORM_URI"):
        return "configured"
    return "mock"


def publish_artifact(
    *,
    worm_root: Path,
    publish_namespace: str,
    object_key: str,
    source: Path,
) -> WormObjectRecord:
    """Copy artefact into append-only store; refuse to replace differing content."""
    if not source.is_file():
        raise FileNotFoundError(f"artefact missing for WORM publish: {source}")

    digest = file_sha256(source)
    rel = Path("objects") / publish_namespace / object_key
    dest = worm_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        existing = file_sha256(dest)
        if existing != digest:
            raise WormTamperError(
                f"object-lock violation: {dest} exists with different content "
                f"(existing={existing}, new={digest})"
            )
        size = dest.stat().st_size
    else:
        shutil.copy2(source, dest)
        dest.chmod(0o444)
        size = dest.stat().st_size

    return WormObjectRecord(
        object_key=object_key,
        source_path=str(source.resolve()),
        storage_path=str(rel.as_posix()),
        sha256=digest,
        size_bytes=size,
    )


def publish_clearance_run(
    run_dir: Path,
    *,
    prefix: str,
    manifest_path: Path,
    integrated_snapshot_path: Path | None = None,
    chain_path: Path | None = None,
    worm_root: Path | None = None,
) -> dict[str, Any]:
    """Publish clearance artefacts to mock WORM; write `*_worm_publish.json` in run_dir."""
    run_dir.mkdir(parents=True, exist_ok=True)
    root = resolve_worm_root(worm_root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    decision_hash = manifest.get("decision_hash")
    if not isinstance(decision_hash, str) or len(decision_hash) < 16:
        raise WormRetentionError("manifest missing decision_hash for WORM namespace")
    namespace = f"{prefix.replace('/', '-')}/{decision_hash[:16]}"
    published_at = _utc_now_iso()

    objects: list[WormObjectRecord] = []
    artefacts: list[tuple[str, Path]] = [
        ("evaluation_manifest.json", manifest_path),
    ]
    if integrated_snapshot_path and integrated_snapshot_path.is_file():
        artefacts.append(("integrated_snapshot.json", integrated_snapshot_path))
    if chain_path and chain_path.is_file():
        artefacts.append(("clearance_chain.json", chain_path))

    for name, path in artefacts:
        objects.append(
            publish_artifact(
                worm_root=root,
                publish_namespace=namespace,
                object_key=name,
                source=path,
            )
        )

    record = {
        "storage_target": _storage_target_label(root),
        "worm_root": str(root),
        "publish_namespace": namespace,
        "published_at": published_at,
        "objects": [
            {
                "object_key": o.object_key,
                "source_path": o.source_path,
                "storage_path": o.storage_path,
                "sha256": o.sha256,
                "size_bytes": o.size_bytes,
            }
            for o in objects
        ],
    }
    publish_path = run_dir / f"{prefix}_worm_publish.json"
    publish_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    record["publish_record_path"] = str(publish_path)
    return record


def verify_retention(
    publish_record_path: Path,
    *,
    worm_root: Path | None = None,
    check_manifest_refs: bool = True,
) -> dict[str, Any]:
    """Fetch WORM copies and verify SHA-256; optional manifest drift check."""
    record = json.loads(publish_record_path.read_text(encoding="utf-8"))
    root = resolve_worm_root(worm_root or Path(record["worm_root"]))

    verified: list[dict[str, Any]] = []
    for obj in record.get("objects") or []:
        storage_rel = obj.get("storage_path")
        expected_sha = obj.get("sha256")
        if not storage_rel or not expected_sha:
            raise WormRetentionError(f"invalid publish record object entry: {obj}")

        stored = root / storage_rel
        if not stored.is_file():
            raise WormRetentionError(f"WORM object missing: {stored}")

        actual_sha = file_sha256(stored)
        if actual_sha != expected_sha:
            raise WormTamperError(
                f"hash mismatch for {obj.get('object_key')}: "
                f"expected {expected_sha}, got {actual_sha}"
            )
        verified.append(
            {
                "object_key": obj.get("object_key"),
                "storage_path": str(stored),
                "sha256": actual_sha,
                "status": "ok",
            }
        )

    manifest_path: Path | None = None
    for obj in record.get("objects") or []:
        if obj.get("object_key") == "evaluation_manifest.json":
            manifest_path = root / obj["storage_path"]
            break

    manifest_refs_status = "skipped"
    if check_manifest_refs and manifest_path and manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        vessel_key = manifest.get("vessel_key")
        if not vessel_key:
            raise WormRetentionError("manifest missing vessel_key")
        assert_manifest_audit_refs(manifest, vessel_key)
        manifest_refs_status = "ok"

    return {
        "status": "verified",
        "storage_target": record.get("storage_target"),
        "worm_root": str(root),
        "publish_record": str(publish_record_path.resolve()),
        "objects_verified": verified,
        "manifest_audit_refs": manifest_refs_status,
    }


def tamper_worm_object(publish_record_path: Path, object_key: str, *, worm_root: Path | None = None) -> Path:
    """PoC demo helper: mutate stored bytes to simulate integrity violation."""
    record = json.loads(publish_record_path.read_text(encoding="utf-8"))
    root = resolve_worm_root(worm_root or Path(record["worm_root"]))
    for obj in record.get("objects") or []:
        if obj.get("object_key") == object_key:
            path = root / obj["storage_path"]
            path.chmod(0o644)
            path.write_bytes(path.read_bytes() + b"\n# tampered\n")
            return path
    raise KeyError(f"object_key not in publish record: {object_key}")
