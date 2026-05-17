---
name: indago-interpret-metrics
description: Fetch and interpret indago data-publish metrics (P@50 email, R2 snapshots, lead time). Use after data-publish CI, when explaining metric deltas, or before updating external docs.
license: Apache-2.0
compatibility: Network access to public R2 metrics mirror; optional local data/processed/ for a single run
metadata:
  repo: indago
---

## When to use this skill

- After **data-publish** CI completes (email summary).
- Before updating **commercial**, outreach, or Cap Vista docs that cite P@50, recall, or lead time.
- When a doc shows a **dated** metrics table — treat it as stale; fetch instead.

**Do not** copy live metrics from `docs/` into submissions. Run this skill (or the commands below) and interpret with [references/metrics-interpretation.md](references/metrics-interpretation.md).

## Quick fetch (latest from R2)

```bash
uv run python scripts/fetch_publish_metrics.py --interpret
uv run python scripts/fetch_publish_metrics.py --days 7
uv run python scripts/fetch_publish_metrics.py --json
```

Public URLs (same data as maintainer dashboard):

```text
https://pub-e088008b61ee432b906ef710d52af28c.r2.dev/metrics/index.json
https://pub-e088008b61ee432b906ef710d52af28c.r2.dev/metrics/YYYYMMDD.json
```

## Local files after a CI run or pipeline

| File | Contents |
|------|----------|
| `data/processed/backtest_public_integration_summary.json` | Same source as email `metrics_summary` |
| `data/processed/validation_metrics.json` | Global candidate_watchlist P@50 (may differ slightly from email) |
| `data/processed/lead_time_report.json` | Pre-designation lead times |
| `data/processed/metrics_trend.json` | Previous P@50 for regression email logic |

## Interpretation checklist

1. **P@50 drop &lt; 0.02** day-over-day → noise (e.g. 0.400 → 0.396).
2. **Recall@200 &lt; 1.0** → at least one known positive fell below rank 200 — investigate region windows.
3. **skipped_regions** non-empty → partial backtest; do not quote overall metrics as full coverage.
4. **Two P@50 definitions** — email = mean of 5 regional P@50; Cap Vista docs often use global `candidate_watchlist` (fetch both; they may differ by ~0.00x).
5. **Contractual gate** ≥ 0.60 is trial/partner labels — not the daily email value.

Full guide: [references/metrics-interpretation.md](references/metrics-interpretation.md) · [docs/ref-data-publish-metrics.md](../../../docs/ref-data-publish-metrics.md)

## Analyst UI

Watchlist, SHAP, ownership chain: [arktrace.edgesentry.io](https://arktrace.edgesentry.io) — not stored in `metrics/*.json`. Inspect Parquet on R2 with **`/indago-inspect-watchlist`** (`.agents/skills/indago-inspect-watchlist/inspect_watchlist.py`).
