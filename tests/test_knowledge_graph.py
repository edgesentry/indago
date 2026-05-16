"""Tests for pipelines.knowledge_graph (indago#154)."""

from pipelines.knowledge_graph.core import KnowledgeGraph
from pipelines.knowledge_graph.export import export_graph_artifacts
from tests.test_ownership_graph import _make_chain_tables


def test_query_sanctions_multi_hop_path():
    """C1 acceptance: vessel → operator → parent → sanction listing."""
    tables = _make_chain_tables()
    kg = KnowledgeGraph(tables)
    path = kg.query_sanctions_path("111111111")
    assert path is not None
    assert path.sanctions_distance == 2  # operator → sanctioned parent (CONTROLLED_BY)
    assert len(path.hops) >= 4
    assert path.hops[0]["kind"] == "vessel"
    assert any(h["kind"] == "sanction" for h in path.hops)
    assert "sanctions_distance=2" in path.summary
    assert "Seawind" in path.summary or "Oceanic" in path.summary


def test_export_graph_artifacts_writes_parquet(tmp_path):
    tables = _make_chain_tables()
    # Write minimal Lance dir via mock: use from_db_path only if we skip Lance;
    # export uses KnowledgeGraph.from_db_path which needs Lance on disk.
    # Build in-memory by patching load_tables.
    from unittest.mock import patch

    with patch(
        "pipelines.knowledge_graph.export.KnowledgeGraph.from_db_path",
        return_value=KnowledgeGraph(tables),
    ):
        paths = export_graph_artifacts("dummy.duckdb", tmp_path, region="test")
    assert paths["ownership_graph"].exists()
    assert paths["analyst_paths"].exists()

    import polars as pl

    graph = pl.read_parquet(paths["ownership_graph"])
    assert "record_type" in graph.columns
    assert set(graph["record_type"].unique().to_list()) <= {"node", "edge", "path"}

    paths_df = pl.read_parquet(paths["analyst_paths"])
    assert "111111111" in paths_df["mmsi"].to_list()
    assert paths_df.filter(pl.col("mmsi") == "111111111")["hop_count"][0] >= 3


def test_nodes_and_edges_frames():
    tables = _make_chain_tables()
    kg = KnowledgeGraph(tables)
    nodes = kg.nodes_frame()
    edges = kg.edges_frame()
    assert len(nodes) >= 2
    assert "Vessel" in nodes["node_type"].to_list()
    assert "OWNED_BY" in edges["rel_type"].to_list() or "MANAGED_BY" in edges["rel_type"].to_list()
