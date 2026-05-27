"""W2 — maritime cyber graph build, Parquet, and NetworkX traversal."""

from pathlib import Path

import networkx as nx
import polars as pl

from pipelines.maritime_cyber.graph import (
    affected_vessels_for_cve,
    build_maritime_cyber_graph,
    load_graph_from_parquet,
    parse_purl,
    to_networkx,
    write_graph_parquet,
)

CVE_LOG4SHELL = "cve:CVE-2021-44228"


def test_parse_purl_maven() -> None:
    parsed = parse_purl("pkg:maven/org.apache.logging.log4j/log4j-core@2.14.1")
    assert parsed == ("maven", "org.apache.logging.log4j:log4j-core", "2.14.1")


def test_hold_vessel_links_cve_to_ecdis_path() -> None:
    result = build_maritime_cyber_graph(["vessel-hold"])
    g = result.nx_graph
    assert CVE_LOG4SHELL in g
    assert "vessel:vessel-hold" in g
    # CVE ← component ← firmware ← asset ← vessel
    assert affected_vessels_for_cve(g, CVE_LOG4SHELL) == ["vessel-hold"]


def test_clean_vessel_has_no_log4shell_edge() -> None:
    result = build_maritime_cyber_graph(["vessel-clean"])
    g = result.nx_graph
    if CVE_LOG4SHELL in g:
        assert affected_vessels_for_cve(g, CVE_LOG4SHELL) == []


def test_three_vessel_fleet_build() -> None:
    result = build_maritime_cyber_graph()
    assert len(result.nodes) > 0
    assert len(result.edges) > 0
    vessel_nodes = result.nodes.filter(pl.col("node_type") == "Vessel")
    assert len(vessel_nodes) == 3


def test_networkx_matches_edge_table() -> None:
    result = build_maritime_cyber_graph(["vessel-hold"])
    rebuilt = to_networkx(result.nodes, result.edges)
    assert result.nx_graph.number_of_edges() == rebuilt.number_of_edges()
    assert result.nx_graph.number_of_nodes() == rebuilt.number_of_nodes()


def test_parquet_roundtrip(tmp_path: Path) -> None:
    result = build_maritime_cyber_graph()
    paths = write_graph_parquet(result, tmp_path)
    loaded = load_graph_from_parquet(paths["nodes"], paths["edges"])
    assert len(loaded.nodes) == len(result.nodes)
    assert len(loaded.edges) == len(result.edges)
    assert isinstance(loaded.nx_graph, nx.DiGraph)


def test_uc2_affected_vessels_on_full_fleet() -> None:
    result = build_maritime_cyber_graph()
    affected = affected_vessels_for_cve(result.nx_graph, CVE_LOG4SHELL)
    assert affected == ["vessel-hold"]
