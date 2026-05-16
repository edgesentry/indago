# Metrics interpretation quick reference

**Source of truth for live values:** `fetch_publish_metrics.py` / R2 `metrics/*.json` — not markdown tables in `docs/` or commercial submission files.

## Regression rules

| Rule | Threshold |
|------|-----------|
| Email regression banner | P@50 down **> 0.02** vs previous snapshot |
| CI integration floor | Combined watchlist P@50 **≥ 0.25** |
| Cap Vista contractual gate | Partner validation P@50 **≥ 0.60** (not daily email) |
| Demonstrated CI ceiling | Multi-region **≥ 0.68** (regression gate in docs) |

## Email field → code

| Email | Source script | Field |
|-------|--------------|-------|
| Precision@50 + CI | `run_public_backtest_batch.py` → `summary.precision_at_50` | mean + CI across 5 regions |
| Recall@200 | same | `recall_at_200.mean` |
| Known positives | same | `total_known_cases` |
| Pre-designation / lead | `validate_lead_time_ofac.py` | `lead_time_report.json` |
| Per-region table | backtest `region_summary` | matched / recall in watchlist |

## Common misreadings

| Observation | Wrong conclusion | Correct read |
|-------------|------------------|--------------|
| P@50 0.396 vs 0.400 in docs | Model broke | Same band; ~1 top-50 slot; check CI |
| Lead median 14 → 22 in one day | Ranking worse | Cohort of pre-designation cases changed |
| ownership_chain deploy | P@50 must drop | Column add rarely moves rank much; check Recall@200 |
| Singapore-only P@50 = 0.06 | Model useless | Structural ceiling with 3 labels; use AUROC |

## Commands

```bash
# Public trend
uv run python scripts/fetch_publish_metrics.py --days 7 --interpret

# Reproduce email inputs locally (after data-publish artifacts downloaded)
cat data/processed/backtest_public_integration_summary.json | jq '.metrics_summary'
cat data/processed/lead_time_report.json | jq '{pre_designation_count, median_lead_days, mean_lead_days}'

# Global watchlist metric (marketing / Cap Vista)
cat data/processed/validation_metrics.json
```
