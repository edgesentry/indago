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

## Demo vessel search (do not hardcode MMSI in docs)

**Multi-hop ownership (ideal for C1 video shot 3):**

```bash
uv run python .agents/skills/indago-inspect-watchlist/scripts/inspect_watchlist.py \
  --min-chain-hops 2 --limit 20
```

After Equasis seed in CI, many designated vessels show `sanctions_distance = 0` with `chain_hops >= 2` (vessel → operator → listing). The script’s `Demo-ready (distance 1–2, chain_hops >= 2)` filter may be zero — use `--min-chain-hops 2` instead.

When no multi-hop rows exist, use Feature attribution (SHAP) or expand `config/equasis/ownership_seed.csv`.

**Single vessel deep-dive:**

```bash
uv run python .agents/skills/indago-inspect-watchlist/scripts/inspect_watchlist.py --mmsi <MMSI>
```

## Manual curl (no Python)

```bash
curl -fsSL -o /tmp/singapore_watchlist.parquet \
  https://arktrace-public.edgesentry.io/score/singapore_watchlist.parquet
```

Regions published by data-publish: `singapore`, `japansea`, `europe`, `blacksea`, `middleeast`.

## Local after pipeline

```bash
uv run python .agents/skills/indago-inspect-watchlist/scripts/inspect_watchlist.py --source local
```

Prefer `data/processed/score/*_watchlist.parquet` over stale flat copies at `data/processed/` root.

## arktrace UI cross-check

1. Sync on [arktrace.edgesentry.io](https://arktrace.edgesentry.io)
2. Open MMSI from script output
3. Ownership chain subtitle must match `sanctions_distance` from Parquet

## Ownership graph (indago#169)

CI builds `data/processed/equasis/ownership_chains.csv` from `config/equasis/ownership_seed.csv` after sanctions ingest, then passes it to `vessel_registry --equasis-csv`.

```bash
uv run python -m pipelines.ingest.equasis_ownership --db data/processed/ais/singapore.duckdb
uv run python scripts/sync_r2.py pull-equasis-ownership   # optional R2 cache
```

If `Demo-ready: 0`, expand the seed CSV with MMSI + `manager_name` / `owner_name` matching `sanctions_entities` company names.
