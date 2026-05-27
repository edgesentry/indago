"""Paths and helpers for demo-enhanced fleet fixtures (W8 / #196)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
FLEET_DEMO_ROOT = _REPO_ROOT / "fixtures" / "fleet-demo"
FLEET_DEMO_MANIFEST = FLEET_DEMO_ROOT / "manifest.json"
FLEET_DEMO_ASSET_MAP = FLEET_DEMO_ROOT / "asset_map.yaml"
FLEET_DEMO_SBOM_DIR = FLEET_DEMO_ROOT / "sbom"
FLEET_DEMO_CVE_SNAPSHOT = FLEET_DEMO_ROOT / "cve" / "snapshot-fleet-demo.json"
FLEET_DEMO_PROFILE_MANIFEST = _REPO_ROOT / "profiles" / "maritime_cyber" / "fleet-demo-manifest.yaml"


def fleet_demo_available() -> bool:
    return FLEET_DEMO_MANIFEST.is_file() and FLEET_DEMO_ASSET_MAP.is_file()


def load_fleet_demo_manifest() -> dict[str, Any]:
    if not FLEET_DEMO_MANIFEST.is_file():
        msg = f"fleet-demo manifest not found: {FLEET_DEMO_MANIFEST}"
        raise FileNotFoundError(msg)
    data = json.loads(FLEET_DEMO_MANIFEST.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("fleet-demo manifest must be a JSON object")
    return data


def fleet_demo_vessel_keys() -> list[str]:
    """All vessel keys listed in fleet-demo manifest."""
    manifest = load_fleet_demo_manifest()
    vessels = manifest.get("vessels")
    if not isinstance(vessels, list):
        raise ValueError("manifest.vessels must be a list")
    keys: list[str] = []
    for entry in vessels:
        if isinstance(entry, dict) and entry.get("vessel_key"):
            keys.append(str(entry["vessel_key"]))
    return keys
