# Data Publish Metrics — Interpretation Guide

How to read the **indago data publish** email, R2 daily snapshots, and local backtest artifacts after `data-publish.yml` runs. Metric *definitions* live in [ref-evaluation-metrics.md](ref-evaluation-metrics.md); this doc explains *what each published number means* and when to worry.

---

## Where metrics come from

| Source | Path / trigger | Audience |
|--------|----------------|----------|
| **Email** | `scripts/notify_metrics.py` after CI | Maintainers (`NOTIFY_EMAIL`) |
| **R2 snapshots** | `scripts/push_metrics_snapshot.py` → `maridb-public/metrics/YYYYMMDD.json` | Dashboard, agents, trend scripts |
| **Local (CI artifact)** | `data/processed/backtest_public_integration_summary.json` | Debugging a single run |
| **Local (AIS validate)** | `data/processed/validation_metrics.json` | Single-corpus quick check |
| **Lead time** | `data/processed/lead_time_report.json` | Pre-designation case studies |

Public read (no credentials):

```text
https://pub-e088008b61ee432b906ef710d52af28c.r2.dev/metrics/index.json
https://pub-e088008b61ee432b906ef710d52af28c.r2.dev/metrics/20260516.json
```

Fetch locally:

```bash
uv run python scripts/fetch_publish_metrics.py
uv run python scripts/fetch_publish_metrics.py --days 7 --json
```

---

## Email sections mapped to data

### Overall Metrics

| Email row | Snapshot field | Computation |
|-----------|----------------|-------------|
| **Precision@50** | `precision_at_50` + CI | **Mean** of per-region P@50 from `run_public_backtest_batch.py` windows; CI = 95% across those 5 regional values (not bootstrap on vessels) |
| **Recall@200** | `recall_at_200` | Mean regional recall@200 — fraction of known positives appearing in top 200 per region |
| **Known positives** | `known_positives` | Total labeled OFAC/EU/UN positives in the evaluation manifest (typically 99 multi-region) |
| **vs prev day** | R2 `metrics/YYYYMMDD.json` delta | Day-over-day change in stored snapshot |
| **7-day trend** | Oldest vs newest in `metrics/index.json` | Rolling comparison (up to 30 entries retained in index) |

### Lead Time — Pre-Designation Detection

From `validate_lead_time_ofac.py` on `candidate_watchlist.parquet`:

| Email row | Field | Meaning |
|-----------|-------|---------|
| **Pre-designation detections** | `pre_designation_count` | Vessels flagged **before** public OFAC/EU listing date (watchlist `first_flagged_at` vs designation) |
| **Mean / median lead time** | `mean_lead_days`, `median_lead_days` | Days between first flag and designation (positive = early warning) |
| **p25 / p75** | `p25_lead_days`, `p75_lead_days` | Spread of lead times across cases |

### Per-Region Coverage

| Email column | Backtest field | Meaning |
|--------------|----------------|---------|
| **Positives matched** | `matched_total` / `source_positive_total` | Known positives for that region found in the scored watchlist |
| **Recall in watchlist** | `source_recall_in_watchlist` | Share of regional positives that appear anywhere in the ranked list (not only top 50) |

Skipped regions (`skipped_regions`) were below `--min-watchlist-size` or missing parquet — **do not** treat their absence as zero performance.

---

## Two different “Precision@50” numbers (do not confuse)

| Metric | How computed | Typical value (May 2026) | Use for |
|--------|--------------|---------------------------|---------|
| **Email / backtest summary** | Average of **5 regional** P@50 values | ~0.37–0.40 | Daily publish email, `metrics/*.json`, trend |
| **Global `candidate_watchlist`** | Single ranked list after dedup; top-50 / labeled | ~0.40 | Cap Vista docs, `validation_metrics.json`, arktrace marketing |

A gap of **0.00x** between them is normal (≈ one vessel rank swap in top-50). Do **not** call a drop from 0.400 → 0.396 a regression unless it exceeds the rules below.

---

## When is a change a real regression?

`notify_metrics.py` flags regression only when **day-over-day P@50 drops by more than 0.02** (2 percentage points on the regional mean).

| Change | Verdict |
|--------|---------|
| 0.400 → 0.396 | **Noise** — within CI; ~1 fewer hit in top-50 |
| 0.40 → 0.37 over 7 days | **Review** — check AIS ingest, skipped regions, scoring changes |
| Recall@200 &lt; 1.0 | **Investigate** — a known positive fell below rank 200 in some region |
| Pre-designation count drops sharply | **Review** — graph/sanctions ingest or `first_flagged_at` logic |
| Skipped regions non-empty | **Action** — pipeline or watchlist too small; backtest partial |

CI also enforces `tests/test_public_data_backtest_integration.py` floor **P@50 ≥ 0.25** on multi-region combined watchlist.

Contractual / trial gates (Cap Vista): **≥ 0.60** on partner validation set — not the daily email number.

---

## Latest published snapshot (example: 2026-05-16)

Fetched from R2 after data-publish run on `main` (ownership_chain + `score/` publish path):

| Metric | 2026-05-16 | 2026-05-15 | 2026-05-11 (7d) |
|--------|------------|------------|-----------------|
| Precision@50 (mean) | **0.396** | 0.396 | 0.372 |
| CI 95% | 0.32 – 0.48 | same | 0.31 – 0.44 |
| Recall@200 | 1.000 | 1.000 | 1.000 |
| Known positives | 99 | 99 | 93 |
| Pre-designation count | 11 | 11 | 10 |
| Median lead (days) | 22 | 14 | 20 |
| Mean lead (days) | 18 | 13 | 18 |

**Interpretation:**

- **P@50 stable** day-over-day; **7-day trend up** (+0.024) — healthy.
- **Recall@200 = 1.0** — all 99 known positives still recovered in top 200 per region.
- **Lead time median rose** 14 → 22 vs prior day — often cohort mix (which cases enter the 11 pre-designation set), not necessarily worse ranking.
- Compare to **global** `candidate_watchlist` P@50 ≈ 0.40 when writing external docs.

Re-fetch before acting:

```bash
uv run python scripts/fetch_publish_metrics.py --interpret
```

---

## Maintainer dashboard

Pipeline health (gate pass/fail, skipped regions): indago dashboard (`dashboard/`) using the same `metrics/*.json` files.

Analyst-facing SHAP, ownership chain, and watchlist UI: [arktrace.edgesentry.io](https://arktrace.edgesentry.io) — not this metrics bundle.

---

## Related docs

- [ref-evaluation-metrics.md](ref-evaluation-metrics.md) — definitions and thresholds
- [ref-backtesting.md](ref-backtesting.md) — how backtest windows are built
- [ref-precision-plan.md](ref-precision-plan.md) — improving P@50
- [ref-r2-data-layout.md](ref-r2-data-layout.md) — `metrics/` prefix on `maridb-public`
