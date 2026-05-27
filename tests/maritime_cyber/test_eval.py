"""W3 — port clearance evaluation, facts.json, decision hash."""

import json
from pathlib import Path

from pipelines.maritime_cyber.eval import (
    affected_vessels,
    evaluate_port_clearance,
    write_evaluation_artifacts,
)
from pipelines.maritime_cyber.graph import build_maritime_cyber_graph

CVE_LOG4SHELL = "CVE-2021-44228"


def test_vessel_hold_is_hold() -> None:
    graph = build_maritime_cyber_graph(["vessel-hold"])
    result = evaluate_port_clearance("vessel-hold", graph_result=graph)
    assert result.outcome == "hold"
    assert len(result.rules_fired) >= 1
    rule_ids = {h.rule_id for h in result.rules_fired}
    assert "SG-CC-001" in rule_ids or "SG-CC-007" in rule_ids


def test_vessel_clean_is_pass() -> None:
    graph = build_maritime_cyber_graph(["vessel-clean"])
    result = evaluate_port_clearance("vessel-clean", graph_result=graph)
    assert result.outcome == "pass"
    assert result.rules_fired == ()


def test_decision_hash_reproducible() -> None:
    graph = build_maritime_cyber_graph(["vessel-hold"])
    a = evaluate_port_clearance("vessel-hold", port_call_id="pc-1", graph_result=graph)
    b = evaluate_port_clearance("vessel-hold", port_call_id="pc-1", graph_result=graph)
    assert a.decision_hash == b.decision_hash
    assert len(a.decision_hash) == 64


def test_facts_json_written(tmp_path: Path) -> None:
    graph = build_maritime_cyber_graph(["vessel-hold"])
    result = evaluate_port_clearance("vessel-hold", graph_result=graph)
    paths = write_evaluation_artifacts(result, tmp_path)
    facts = json.loads(paths["facts"].read_text(encoding="utf-8"))
    assert facts["outcome"] == "hold"
    assert "disclaimer" in facts
    assert facts["decision_hash"] == result.decision_hash


def test_uc2_affected_vessels_api() -> None:
    assert affected_vessels(CVE_LOG4SHELL) == ["vessel-hold"]


def test_hold_and_clean_differ() -> None:
    hold = evaluate_port_clearance(
        "vessel-hold",
        graph_result=build_maritime_cyber_graph(["vessel-hold"]),
    )
    clean = evaluate_port_clearance(
        "vessel-clean",
        graph_result=build_maritime_cyber_graph(["vessel-clean"]),
    )
    assert hold.outcome != clean.outcome
