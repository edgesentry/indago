# Knowledge graph layer (indago#154)

## Overview

`pipelines.knowledge_graph` wraps Lance ownership graph datasets with:

- **Query API** — sanctions multi-hop paths per MMSI (`KnowledgeGraph.query_sanctions_path`)
- **Export API** — Parquet artifacts for R2 and analyst briefs (`export_graph_artifacts`)

Detection logic remains in `pipelines.features.ownership_graph`; arktrace is visualization-only.

Graph storage uses **`lance`** columnar datasets (`graph_store.py`), not the PyPI **`lance-graph`** package (removed as unused direct dependency).

## CLI

```bash
# C1 demo: print sanctions path for one vessel
uv run python -m pipelines.knowledge_graph \
  --db data/processed/ais/singapore.duckdb \
  --query 111111111

# Export Parquet (also runs at end of pipeline features step)
uv run python -m pipelines.knowledge_graph \
  --db data/processed/ais/singapore.duckdb \
  --export --region singapore
```

## Artifacts (`data/processed/score/`)

| File | Contents |
|------|----------|
| `{region}_graph_nodes.parquet` | Normalized nodes (Vessel, Company, …) |
| `{region}_graph_edges.parquet` | Relationships (OWNED_BY, SANCTIONED_BY, …) |
| `{region}_analyst_paths.parquet` | Per-MMSI path JSON + text summary |
| `{region}_ownership_graph.parquet` | Unified node \| edge \| path records (#119) |

Uploaded by `scripts/sync_r2.py push-arktrace` to `arktrace-public/score/{region}_ownership_graph.parquet`.

## Entity model

| Node | Source |
|------|--------|
| Vessel, Company, Country, … | `vessel_registry` + `sanctions` ingest |
| Port, SanctionEntry | Schema reserved (#154); populated when ingest extends |
| PORT_CALL, AIS_GAP edges | Schema reserved for future AIS / port ingest |

## Related

- [ref-pipeline.md](ref-pipeline.md) — pipeline orchestration
- [ref-r2-buckets.md](ref-r2-buckets.md) — `ownership/graph.parquet` layout
