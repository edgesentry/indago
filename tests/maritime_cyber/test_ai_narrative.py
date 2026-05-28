"""D5 — operator explanation guardrails and template synthesis."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.port_clearance.ai_narrative import (
    NarrativeGuardrailError,
    build_deterministic_narrative,
    generate_operator_explanation,
    validate_narrative_guardrails,
    write_operator_explanation_artifacts,
)
from pipelines.maritime_cyber.eval import evaluate_port_clearance
from pipelines.maritime_cyber.graph import build_maritime_cyber_graph


@pytest.fixture
def hold_facts() -> dict:
    """PoC vessel-hold facts from indago fixtures (no sibling-repo path)."""
    graph = build_maritime_cyber_graph(["vessel-hold"])
    result = evaluate_port_clearance(
        "vessel-hold",
        port_call_id="port-call-demo-sgsin",
        graph_result=graph,
    )
    assert result.outcome == "hold"
    return result.facts


def test_build_deterministic_narrative_mentions_hold_and_rules(hold_facts: dict) -> None:
    text = build_deterministic_narrative(hold_facts)
    assert "HOLD" in text
    assert "vessel-hold" in text
    assert "SG-CC-001" in text
    assert "CVE-2021-44228" in text
    assert "non-authoritative" in text.lower()


def test_validate_rejects_invented_cve(hold_facts: dict) -> None:
    bad = build_deterministic_narrative(hold_facts) + "\n\nAlso see CVE-1999-0001."
    with pytest.raises(NarrativeGuardrailError, match="not in facts"):
        validate_narrative_guardrails(bad, hold_facts)


def test_validate_rejects_contradictory_pass_on_hold(hold_facts: dict) -> None:
    bad = (
        "The rule engine recorded clearance outcome HOLD for vessel vessel-hold. "
        "Recommended clearance outcome pass for berth entry."
    )
    with pytest.raises(NarrativeGuardrailError, match="contradicts"):
        validate_narrative_guardrails(bad, hold_facts)


def test_generate_operator_explanation_round_trip(hold_facts: dict) -> None:
    text = generate_operator_explanation(hold_facts, mode="template")
    validate_narrative_guardrails(text, hold_facts)


def test_write_operator_explanation_artifacts(tmp_path: Path, hold_facts: dict) -> None:
    facts_path = tmp_path / "vessel-hold_facts.json"
    facts_path.write_text(json.dumps(hold_facts, indent=2), encoding="utf-8")
    paths = write_operator_explanation_artifacts(facts_path, prefix="vessel-hold_port-call-demo-sgsin")
    assert paths["text"].is_file()
    assert paths["meta"].is_file()
    meta = json.loads(paths["meta"].read_text(encoding="utf-8"))
    assert meta["source"] == "template"
    assert meta["non_authoritative"] is True
    assert meta["outcome"] == "hold"
