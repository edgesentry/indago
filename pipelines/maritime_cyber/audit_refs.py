"""G11/G12 audit evidence references — frozen BOM baseline + CVE snapshot (Cap Vista D2)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ASSET_MAP = _REPO_ROOT / "fixtures" / "asset_map.yaml"
DEFAULT_CVE_SNAPSHOT = _REPO_ROOT / "fixtures" / "cve" / "snapshot-2026-05-26.json"
DEFAULT_SBOM_DIR = _REPO_ROOT / "fixtures" / "sbom"


class ManifestDriftError(ValueError):
    """Pinned inputs no longer match manifest audit references."""


def file_sha256(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"missing file for audit ref: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_path_label(path: Path) -> str:
    """Stable path for manifests and decision_hash (repo-relative when under repo root)."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(_REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def resolve_audit_path(label: str) -> Path:
    """Resolve a path label from build_bom_baseline_ref / build_cve_snapshot_ref."""
    candidate = Path(label)
    if candidate.is_absolute():
        return candidate
    return _REPO_ROOT / candidate


def build_bom_baseline_ref(
    vessel_key: str,
    *,
    asset_map_path: Path | None = None,
    sbom_dir: Path | None = None,
) -> dict[str, Any]:
    asset_map = Path(asset_map_path or DEFAULT_ASSET_MAP)
    sbom_dir_path = Path(sbom_dir or DEFAULT_SBOM_DIR)
    sbom_path = sbom_dir_path / f"{vessel_key}.json"
    return {
        "asset_map_path": audit_path_label(asset_map),
        "asset_map_sha256": file_sha256(asset_map),
        "sbom_path": audit_path_label(sbom_path),
        "sbom_sha256": file_sha256(sbom_path),
    }


def build_cve_snapshot_ref(*, cve_snapshot_path: Path | None = None) -> dict[str, Any]:
    cve_path = Path(cve_snapshot_path or DEFAULT_CVE_SNAPSHOT)
    return {
        "cve_snapshot_path": audit_path_label(cve_path),
        "cve_snapshot_sha256": file_sha256(cve_path),
    }


def assert_manifest_audit_refs(
    manifest: dict[str, Any],
    vessel_key: str,
    *,
    asset_map_path: Path | None = None,
    cve_snapshot_path: Path | None = None,
    sbom_dir: Path | None = None,
) -> None:
    """Re-read pinned files; fail if SHA-256 drifted from manifest refs (G11 tamper detection)."""
    expected_bom = build_bom_baseline_ref(
        vessel_key,
        asset_map_path=asset_map_path,
        sbom_dir=sbom_dir,
    )
    expected_cve = build_cve_snapshot_ref(cve_snapshot_path=cve_snapshot_path)

    for key, expected in (
        ("bom_baseline_ref", expected_bom),
        ("cve_snapshot_ref", expected_cve),
    ):
        actual = manifest.get(key)
        if actual != expected:
            raise ManifestDriftError(
                f"{key} drift: manifest refs do not match current pinned inputs\n"
                f"  manifest: {json.dumps(actual, sort_keys=True)}\n"
                f"  expected: {json.dumps(expected, sort_keys=True)}"
            )

    # Legacy flat fields must stay aligned with structured refs
    bom = manifest.get("bom_baseline_ref") or expected_bom
    cve = manifest.get("cve_snapshot_ref") or expected_cve
    if manifest.get("sbom_sha256") and manifest["sbom_sha256"] != bom.get("sbom_sha256"):
        raise ManifestDriftError("sbom_sha256 flat field drift vs bom_baseline_ref")
    if manifest.get("cve_snapshot_sha256") and manifest["cve_snapshot_sha256"] != cve.get(
        "cve_snapshot_sha256"
    ):
        raise ManifestDriftError("cve_snapshot_sha256 flat field drift vs cve_snapshot_ref")


def integrated_snapshot_fingerprint(manifest: dict[str, Any]) -> str:
    """Tamper-evident fingerprint over BOM×CVE refs + evaluation outcome (G11)."""
    body = {
        "bom_baseline_ref": manifest.get("bom_baseline_ref"),
        "cve_snapshot_ref": manifest.get("cve_snapshot_ref"),
        "vessel_key": manifest.get("vessel_key"),
        "port_call_id": manifest.get("port_call_id"),
        "outcome": manifest.get("outcome"),
        "rules_fired": manifest.get("rules_fired"),
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
