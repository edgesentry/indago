"""D5 — Operator explanation from clearance facts (non-authoritative, guardrailed)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_POLICY_PATH = Path(__file__).resolve().parent / "prompts" / "operator_explanation_policy.txt"

_OUTCOME_CONTRADICTION_PATTERNS: dict[str, list[str]] = {
    "hold": [
        r"\boutcome\s+is\s+pass\b",
        r"\bclearance\s+outcome\s+pass\b",
        r"\brecommend(?:ed)?\s+(?:for\s+)?pass\b",
        r"\bshould\s+(?:be\s+)?pass\b",
        r"\bberth\s+approved\b",
    ],
    "pass": [
        r"\boutcome\s+is\s+hold\b",
        r"\bclearance\s+outcome\s+hold\b",
        r"\brecommend(?:ed)?\s+(?:for\s+)?hold\b",
        r"\bshould\s+(?:be\s+)?hold\b",
        r"\bdo\s+not\s+(?:allow|permit)\s+entry\b",
    ],
}


class NarrativeGuardrailError(ValueError):
    """Raised when synthesized text violates D5 policy."""


def load_operator_explanation_policy() -> str:
    return _POLICY_PATH.read_text(encoding="utf-8")


def normalize_cve_id(raw: str) -> str:
    token = raw.strip()
    if token.lower().startswith("cve:"):
        token = token[4:]
    return token.upper()


def allowed_cve_ids(facts: dict[str, Any]) -> set[str]:
    allowed: set[str] = set()
    for raw in facts.get("cve_ids") or []:
        if isinstance(raw, str) and raw.strip():
            allowed.add(normalize_cve_id(raw))
    for path in facts.get("impacted_paths") or []:
        if not isinstance(path, dict):
            continue
        cve_id = path.get("cve_id")
        if isinstance(cve_id, str) and cve_id.strip():
            allowed.add(normalize_cve_id(cve_id))
    return allowed


def build_deterministic_narrative(facts: dict[str, Any]) -> str:
    """Template synthesis from facts only (no LLM)."""
    outcome = str(facts.get("outcome", "")).strip().lower()
    outcome_upper = outcome.upper() if outcome else "UNKNOWN"
    vessel = facts.get("vessel_key", "—")
    port_call = facts.get("port_call_id", "—")
    rules = [r for r in (facts.get("rules_fired") or []) if isinstance(r, dict)]
    paths = [p for p in (facts.get("paths") or []) if isinstance(p, dict)]

    rule_lines = "\n".join(
        f"- {r.get('id', '?')}: {r.get('title', '—')} ({r.get('severity', '—')})" for r in rules
    )
    path_lines = "\n".join(
        f"- {', '.join(p.get('rule_ids') or [])}: {p.get('summary', '—')}" for p in paths
    )

    cve_tokens = sorted(allowed_cve_ids(facts))
    cve_line = ", ".join(cve_tokens) if cve_tokens else "none on cited paths"

    paragraphs = [
        (
            "Operator context (non-authoritative). This explanation is synthesized from "
            "evaluation facts only. It does not alter the deterministic clearance outcome "
            "or the decision hash sealed in the audit manifest."
        ),
        (
            f"The rule engine recorded clearance outcome {outcome_upper} for vessel {vessel} "
            f"on port call {port_call}. {len(rules)} rule(s) fired across {len(paths)} "
            "cited path(s)."
        ),
    ]
    if rule_lines:
        paragraphs.append("Rules cited in this evaluation:\n" + rule_lines)
    if path_lines:
        paragraphs.append("Vulnerability paths summarized for operators:\n" + path_lines)
    paragraphs.append(f"CVE identifiers present on cited paths: {cve_line}.")
    paragraphs.append(
        f"The authoritative outcome remains {outcome_upper} as determined by the "
        "maritime_cyber rule profile; this narrative is for operator explanation only."
    )
    return "\n\n".join(paragraphs)


def validate_narrative_guardrails(narrative: str, facts: dict[str, Any]) -> None:
    """Raise NarrativeGuardrailError if text contradicts facts or invents CVEs."""
    outcome = str(facts.get("outcome", "")).strip().lower()
    if outcome not in {"pass", "hold"}:
        raise NarrativeGuardrailError(f"unsupported facts.outcome: {outcome!r}")

    lowered = narrative.lower()
    if outcome not in lowered:
        raise NarrativeGuardrailError(
            f"narrative must mention recorded outcome '{outcome}'"
        )

    for pattern in _OUTCOME_CONTRADICTION_PATTERNS[outcome]:
        if re.search(pattern, lowered):
            raise NarrativeGuardrailError(
                f"narrative contradicts recorded outcome '{outcome}' (pattern: {pattern})"
            )

    allowed = allowed_cve_ids(facts)
    for match in re.finditer(r"CVE-\d{4}-\d+", narrative, flags=re.IGNORECASE):
        token = normalize_cve_id(match.group(0))
        if token not in allowed:
            raise NarrativeGuardrailError(
                f"narrative cites CVE not in facts: {token} (allowed: {sorted(allowed)})"
            )


def generate_operator_explanation(
    facts: dict[str, Any],
    *,
    mode: str = "template",
) -> str:
    """Return guardrailed operator explanation text."""
    if mode != "template":
        raise ValueError(f"unsupported narrative mode: {mode!r} (use 'template')")

    narrative = build_deterministic_narrative(facts)
    validate_narrative_guardrails(narrative, facts)
    return narrative


def write_operator_explanation_artifacts(
    facts_path: Path,
    *,
    prefix: str | None = None,
    output_dir: Path | None = None,
) -> dict[str, Path]:
    """Write *_operator_explanation.txt and *_operator_explanation_meta.json."""
    facts_path = facts_path.resolve()
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    narrative = generate_operator_explanation(facts, mode="template")

    out_dir = output_dir or facts_path.parent
    stem = prefix or facts_path.stem.replace("_facts", "")
    text_path = out_dir / f"{stem}_operator_explanation.txt"
    meta_path = out_dir / f"{stem}_operator_explanation_meta.json"

    text_path.write_text(narrative + "\n", encoding="utf-8")
    meta_path.write_text(
        json.dumps(
            {
                "source": "template",
                "policy": str(_POLICY_PATH.relative_to(Path(__file__).resolve().parents[2])),
                "facts_path": str(facts_path),
                "outcome": facts.get("outcome"),
                "decision_hash": facts.get("decision_hash"),
                "non_authoritative": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {"text": text_path, "meta": meta_path}
