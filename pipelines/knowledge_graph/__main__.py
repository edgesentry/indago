"""CLI: query sanctions paths and export graph Parquet (indago#154).

Usage:
    uv run python -m pipelines.knowledge_graph --db data/processed/ais/singapore.duckdb --query 111111111
    uv run python -m pipelines.knowledge_graph --db ... --export --region singapore
"""

from __future__ import annotations

import argparse
import json
import os

from pipelines.knowledge_graph.core import KnowledgeGraph
from pipelines.knowledge_graph.export import default_score_dir, export_graph_artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description="KnowledgeGraph query and export")
    parser.add_argument("--db", default=os.getenv("DB_PATH", "data/processed/mpol.duckdb"))
    parser.add_argument("--query", metavar="MMSI", help="Print sanctions multi-hop path for one vessel")
    parser.add_argument("--export", action="store_true", help="Write graph Parquet artifacts")
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument("--region", type=str, default=None)
    args = parser.parse_args()

    kg = KnowledgeGraph.from_db_path(args.db)

    if args.query:
        path = kg.query_sanctions_path(args.query)
        if path is None:
            print(f"No graph coverage for MMSI {args.query}")
            raise SystemExit(1)
        print(path.summary)
        print()
        print(json.dumps(path.to_dict(), indent=2))
        return

    if args.export:
        out_dir = args.output_dir or str(default_score_dir())
        paths = export_graph_artifacts(args.db, out_dir, region=args.region)
        for name, p in paths.items():
            print(f"  {name}: {p}")
        return

    parser.error("Specify --query MMSI or --export")


if __name__ == "__main__":
    main()
