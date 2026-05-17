---
name: indago-inspect-watchlist
description: Download and inspect the latest regional watchlists on R2 (arktrace-public or maridb-public). Use when finding demo MMSIs, checking sanctions_distance and ownership_chain, or verifying data-publish output before arktrace smoke tests.
license: Apache-2.0
compatibility: Requires Python >=3.12 and uv; network for public R2 URLs
metadata:
  repo: indago
---

## When to use this skill

- After **data-publish** — confirm watchlists landed on R2 and columns look right.
- Before **arktrace** demo / Cap Vista video — find MMSIs with `sanctions_distance` 1–2 and multi-hop `ownership_chain`.
- When a vessel shows only one Ownership chain row in the UI — inspect Parquet, not guess.

**Related:** `/indago-interpret-metrics` (P@50 / recall) · `/indago-sync-r2` (upload) · `/indago-run-osint` (analyst report).

## Quick inspect (latest on arktrace-public, no credentials)

```bash
uv run python scripts/inspect_watchlist.py
uv run python scripts/inspect_watchlist.py --mmsi 352001906
uv run python scripts/inspect_watchlist.py --sanctions-distance 1 2 --min-chain-hops 2
uv run python scripts/inspect_watchlist.py --json --limit 50
```

Cache downloads for repeat runs:

```bash
uv run python scripts/inspect_watchlist.py --cache-dir /tmp/arktrace-wl
```

## Pull maridb-public zip (CI backtest bundle)

Same watchlists as CI `pull-watchlists` (may differ in layout from arktrace-public `score/`):

```bash
uv run python scripts/inspect_watchlist.py --pull --source local --data-dir data/processed
```

## Where watchlists live on R2

| Bucket | Object | Consumer |
|--------|--------|----------|
| **arktrace-public** | `score/{region}_watchlist.parquet` + `ducklake_manifest.json` | [arktrace.edgesentry.io](https://arktrace.edgesentry.io) OPFS sync |
| **maridb-public** | `watchlists.zip` | CI backtest (`pull-watchlists`) |

Manifest (file list + sizes):

```text
https://arktrace-public.edgesentry.io/ducklake_manifest.json
```

## Interpretation

| `sanctions_distance` | Typical `ownership_chain` on current CI |
|----------------------|----------------------------------------|
| 0 | Vessel node only (direct SDN) |
| 1–2 | Needs Equasis `OWNED_BY` in graph — often **0 rows** on publish today |
| 99 | No graph link; behavioural / anomaly score |

Full checklist: [references/watchlist-inspection.md](references/watchlist-inspection.md)
