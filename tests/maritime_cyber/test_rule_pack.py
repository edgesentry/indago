"""W0 — rule pack and asset_map schema validation."""

from pathlib import Path

import pytest

from pipelines.maritime_cyber.rules import (
    KNOWN_REQUIREMENT_IDS,
    load_asset_map,
    load_profile_manifest,
    load_rule_pack,
    validate_asset_map,
    validate_rule_pack,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_rule_pack_loads_and_validates() -> None:
    pack = load_rule_pack()
    assert pack["pack_id"] == "sg-cyber-clearance-v0"
    errors = validate_rule_pack(pack)
    assert errors == [], errors
    rule_ids = {r["id"] for r in pack["rules"]}
    assert "SG-CC-001" in rule_ids
    assert len(pack["rules"]) >= 5


def test_every_rule_cites_known_requirement() -> None:
    pack = load_rule_pack()
    for rule in pack["rules"]:
        for req in rule["requirements"]:
            assert req in KNOWN_REQUIREMENT_IDS, f"{rule['id']}: {req}"


def test_asset_map_e27_fields() -> None:
    asset_map = load_asset_map()
    assert asset_map.get("synthetic") is True
    errors = validate_asset_map(asset_map)
    assert errors == [], errors
    assert set(asset_map["vessels"]) >= {"vessel-hold", "vessel-clean", "vessel-thread"}


def test_profile_manifest_points_at_rule_pack() -> None:
    manifest = load_profile_manifest()
    assert manifest["profile_id"] == "maritime_cyber"
    rule_path = REPO_ROOT / "rules" / "sg-cyber-clearance-v0.yaml"
    assert rule_path.is_file()


def test_regulatory_matrix_ids_align_with_rule_pack() -> None:
    """Requirement IDs in rules must be subset of W0 matrix (code-defined set)."""
    pack = load_rule_pack()
    cited: set[str] = set()
    for rule in pack["rules"]:
        cited.update(rule["requirements"])
    assert cited <= KNOWN_REQUIREMENT_IDS
