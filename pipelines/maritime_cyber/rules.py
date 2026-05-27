"""Load and validate maritime cyber rule packs and fixture schemas (W0)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RULE_PACK = _REPO_ROOT / "rules" / "sg-cyber-clearance-v0.yaml"
DEFAULT_ASSET_MAP = _REPO_ROOT / "fixtures" / "asset_map.yaml"
PROFILE_MANIFEST = _REPO_ROOT / "profiles" / "maritime_cyber" / "manifest.yaml"

KNOWN_REQUIREMENT_IDS = frozenset(
    {
        "IACS-E26-1",
        "IACS-E27-2",
        "IACS-E27-3",
        "IMO-428-5",
        "IMO-FAL3-2",
        "IEC-62443-2-1",
        "IEC-62443-TR2-3",
        "NTIA-SBOM-7",
        "OSV-1",
    }
)

REQUIRED_ASSET_FIELDS = frozenset(
    {
        "id",
        "name",
        "cbs_category",
        "safety_function",
        "ecu_zone",
        "network_zone",
    }
)

VALID_CBS_CATEGORIES = frozenset(
    {"navigation", "propulsion", "cargo", "communications", "other"}
)

VALID_SAFETY_FUNCTIONS = frozenset({"essential", "important", "normal"})


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        msg = f"Expected mapping at root of {path}"
        raise ValueError(msg)
    return data


def load_rule_pack(path: Path | None = None) -> dict[str, Any]:
    """Load the Singapore cyber clearance rule pack."""
    return _load_yaml(path or DEFAULT_RULE_PACK)


def load_asset_map(path: Path | None = None) -> dict[str, Any]:
    """Load the synthetic OT inventory bridge."""
    return _load_yaml(path or DEFAULT_ASSET_MAP)


def load_profile_manifest(path: Path | None = None) -> dict[str, Any]:
    """Load the maritime_cyber profile manifest."""
    return _load_yaml(path or PROFILE_MANIFEST)


def validate_rule_pack(pack: dict[str, Any]) -> list[str]:
    """Return validation errors (empty if valid)."""
    errors: list[str] = []
    rules = pack.get("rules")
    if not isinstance(rules, list) or not rules:
        errors.append("rule pack must contain a non-empty 'rules' list")
        return errors

    if len(rules) < 5 or len(rules) > 15:
        errors.append(f"expected 5–15 rules, got {len(rules)}")

    seen_ids: set[str] = set()
    for i, rule in enumerate(rules):
        prefix = f"rules[{i}]"
        if not isinstance(rule, dict):
            errors.append(f"{prefix}: must be a mapping")
            continue
        rule_id = rule.get("id")
        if not rule_id or not isinstance(rule_id, str):
            errors.append(f"{prefix}: missing string 'id'")
            continue
        if rule_id in seen_ids:
            errors.append(f"{prefix}: duplicate id {rule_id!r}")
        seen_ids.add(rule_id)

        reqs = rule.get("requirements")
        if not isinstance(reqs, list) or not reqs:
            errors.append(f"{prefix} ({rule_id}): missing 'requirements' list")
        else:
            for req in reqs:
                if req not in KNOWN_REQUIREMENT_IDS:
                    errors.append(f"{prefix} ({rule_id}): unknown requirement id {req!r}")

        cond = rule.get("condition")
        if not isinstance(cond, dict) or "type" not in cond:
            errors.append(f"{prefix} ({rule_id}): condition must include 'type'")

        if rule.get("outcome") not in ("hold", "pass", "investigate"):
            errors.append(f"{prefix} ({rule_id}): invalid outcome")

    return errors


def validate_asset_map(asset_map: dict[str, Any]) -> list[str]:
    """Validate E27-style inventory fields on all physical assets."""
    errors: list[str] = []
    vessels = asset_map.get("vessels")
    if not isinstance(vessels, dict) or not vessels:
        errors.append("asset_map must contain non-empty 'vessels'")
        return errors

    for vessel_key, vessel in vessels.items():
        assets = vessel.get("physical_assets") if isinstance(vessel, dict) else None
        if not isinstance(assets, list) or not assets:
            errors.append(f"vessels.{vessel_key}: missing physical_assets")
            continue
        for j, asset in enumerate(assets):
            prefix = f"vessels.{vessel_key}.physical_assets[{j}]"
            if not isinstance(asset, dict):
                errors.append(f"{prefix}: must be a mapping")
                continue
            missing = REQUIRED_ASSET_FIELDS - set(asset)
            if missing:
                errors.append(f"{prefix}: missing fields {sorted(missing)}")
            cat = asset.get("cbs_category")
            if cat and cat not in VALID_CBS_CATEGORIES:
                errors.append(f"{prefix}: invalid cbs_category {cat!r}")
            sf = asset.get("safety_function")
            if sf and sf not in VALID_SAFETY_FUNCTIONS:
                errors.append(f"{prefix}: invalid safety_function {sf!r}")
    return errors
