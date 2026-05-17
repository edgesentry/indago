# Watchlist inspection on R2

## Columns to check

| Column | Purpose |
|--------|---------|
| `mmsi`, `vessel_name`, `confidence` | Ranked list identity |
| `sanctions_distance` | 0 = direct sanction; 1–2 = operator/parent hop; 99 = no graph link |
| `ownership_chain` | JSON array for arktrace Ownership chain panel |
| `top_signals` | SHAP JSON for Feature attribution |
| `region` | Region tag inside combined files |

If `ownership_chain` column is missing, re-run scoring after indago#148 and `push-arktrace`.

## Demo MMSI search

**Multi-hop ownership (ideal for C1 video shot 3):**

```bash
uv run python scripts/inspect_watchlist.py \
  --sanctions-distance 1 2 --min-chain-hops 2 --limit 20
```

When `Demo-ready: 0`, use Feature attribution (SHAP) instead, or narrate direct sanction (distance 0, one node).

**Single vessel deep-dive:**

```bash
uv run python scripts/inspect_watchlist.py --mmsi <MMSI>
```

## Manual curl (no Python)

```bash
curl -fsSL -o /tmp/singapore_watchlist.parquet \
  https://arktrace-public.edgesentry.io/score/singapore_watchlist.parquet
```

Regions published by data-publish: `singapore`, `japansea`, `europe`, `blacksea`, `middleeast`.

## Local after pipeline

```bash
uv run python scripts/inspect_watchlist.py --source local --data-dir data/processed
```

Prefer `data/processed/score/*_watchlist.parquet` over stale flat copies at `data/processed/` root.

## arktrace UI cross-check

1. Sync on [arktrace.edgesentry.io](https://arktrace.edgesentry.io)
2. Open MMSI from script output
3. Ownership chain subtitle must match `sanctions_distance` from Parquet

## Graph data gap (why chains are short)

`vessel_registry` only adds `OWNED_BY` / `MANAGED_BY` when run with `--equasis-csv`. Weekly CI does not pass it today, so most vessels have `sanctions_distance` 0 or 99 only.

To enrich chains: Equasis CSV → `uv run python -m pipelines.ingest.vessel_registry --db <region>.duckdb --equasis-csv …` → re-score → `push-arktrace`.
