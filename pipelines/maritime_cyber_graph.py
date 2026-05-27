"""CLI entrypoint for maritime cyber graph build (W2)."""

from __future__ import annotations

import argparse
from pathlib import Path

from pipelines.maritime_cyber.graph import (
    DEFAULT_OUTPUT_DIR,
    build_maritime_cyber_graph,
    write_graph_parquet,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build maritime cyber graph Parquet + manifest")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for graph_nodes.parquet and graph_edges.parquet",
    )
    parser.add_argument(
        "--vessel",
        action="append",
        dest="vessels",
        help="Vessel key (default: all in asset_map)",
    )
    args = parser.parse_args()
    result = build_maritime_cyber_graph(vessel_keys=args.vessels)
    paths = write_graph_parquet(result, args.output_dir)
    print(f"nodes={len(result.nodes)} edges={len(result.edges)}")
    for name, path in paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
