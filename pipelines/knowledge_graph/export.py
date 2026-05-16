"""
Export knowledge graph artifacts for R2 / analyst briefs (indago#154).
"""

from __future__ import annotations

import os
from pathlib import Path

import polars as pl

from pipelines.knowledge_graph.core import KnowledgeGraph


def export_graph_artifacts(
    db_path: str,
    output_dir: str | Path,
    *,
    region: str | None = None,
) -> dict[str, Path]:
    """Write nodes, edges, analyst paths, and unified graph Parquet files.

    Returns dict of artifact name → local path.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    prefix = f"{region}_" if region else ""
    kg = KnowledgeGraph.from_db_path(db_path)

    nodes = kg.nodes_frame()
    edges = kg.edges_frame()
    paths = kg.analyst_paths_frame()

    nodes_path = out / f"{prefix}graph_nodes.parquet"
    edges_path = out / f"{prefix}graph_edges.parquet"
    paths_path = out / f"{prefix}analyst_paths.parquet"
    graph_path = out / f"{prefix}ownership_graph.parquet"

    nodes.write_parquet(nodes_path)
    edges.write_parquet(edges_path)
    paths.write_parquet(paths_path)

    # Unified long-form graph for #119 / arktrace consumers
    _write_unified_graph(nodes, edges, paths, graph_path)

    return {
        "nodes": nodes_path,
        "edges": edges_path,
        "analyst_paths": paths_path,
        "ownership_graph": graph_path,
    }


def _write_unified_graph(
    nodes: pl.DataFrame,
    edges: pl.DataFrame,
    paths: pl.DataFrame,
    graph_path: Path,
) -> None:
    """Single Parquet with record_type discriminator (node | edge | path)."""
    parts: list[pl.DataFrame] = []
    if len(nodes):
        parts.append(
            nodes.with_columns(pl.lit("node").alias("record_type")).select(
                [
                    "record_type",
                    "node_id",
                    "node_type",
                    "name",
                    "country",
                    "mmsi",
                    "imo",
                    pl.lit(None).cast(pl.Utf8).alias("src_id"),
                    pl.lit(None).cast(pl.Utf8).alias("dst_id"),
                    pl.lit(None).cast(pl.Utf8).alias("rel_type"),
                    pl.lit(None).cast(pl.Int32).alias("sanctions_distance"),
                    pl.lit(None).cast(pl.Utf8).alias("path_summary"),
                ]
            )
        )
    if len(edges):
        parts.append(
            edges.with_columns(pl.lit("edge").alias("record_type")).select(
                [
                    "record_type",
                    pl.lit(None).cast(pl.Utf8).alias("node_id"),
                    pl.lit(None).cast(pl.Utf8).alias("node_type"),
                    pl.lit(None).cast(pl.Utf8).alias("name"),
                    pl.lit(None).cast(pl.Utf8).alias("country"),
                    pl.lit(None).cast(pl.Utf8).alias("mmsi"),
                    pl.lit(None).cast(pl.Utf8).alias("imo"),
                    "src_id",
                    "dst_id",
                    "rel_type",
                    pl.lit(None).cast(pl.Int32).alias("sanctions_distance"),
                    pl.lit(None).cast(pl.Utf8).alias("path_summary"),
                ]
            )
        )
    if len(paths):
        parts.append(
            paths.with_columns(pl.lit("path").alias("record_type")).select(
                [
                    "record_type",
                    pl.lit(None).cast(pl.Utf8).alias("node_id"),
                    pl.lit(None).cast(pl.Utf8).alias("node_type"),
                    pl.lit(None).cast(pl.Utf8).alias("name"),
                    pl.lit(None).cast(pl.Utf8).alias("country"),
                    "mmsi",
                    pl.lit(None).cast(pl.Utf8).alias("imo"),
                    pl.lit(None).cast(pl.Utf8).alias("src_id"),
                    pl.lit(None).cast(pl.Utf8).alias("dst_id"),
                    pl.lit(None).cast(pl.Utf8).alias("rel_type"),
                    "sanctions_distance",
                    "path_summary",
                ]
            )
        )

    if not parts:
        pl.DataFrame(
            schema={
                "record_type": pl.Utf8,
                "node_id": pl.Utf8,
                "mmsi": pl.Utf8,
                "rel_type": pl.Utf8,
                "sanctions_distance": pl.Int32,
                "path_summary": pl.Utf8,
            }
        ).write_parquet(graph_path)
        return

    pl.concat(parts, how="diagonal_relaxed").write_parquet(graph_path)


def default_score_dir() -> Path:
    data = os.getenv("MARIDB_DATA_DIR") or os.getenv("DATA_DIR")
    if data:
        return Path(data) / "score"
    return Path.home() / ".maridb" / "data" / "processed" / "score"
