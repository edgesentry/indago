# Equasis ownership seed (indago#169)

Curated vessel → company links for `vessel_registry --equasis-csv`. Company names are resolved against `sanctions_entities` (OpenSanctions / OFAC load). Use names that appear on [OpenSanctions](https://www.opensanctions.org/) or in the SDN list — partial matches work (e.g. `Harry Victor Ship Management` → full OFAC legal name).

**Do not bulk-scrape Equasis.org.** Add rows from manual Equasis lookup, OFAC press releases, or licensed data only.

## Files

| File | Role |
|------|------|
| `ownership_seed.csv` | Human-edited seed (this directory, tracked in git) |
| `data/processed/equasis/ownership_chains.csv` | Built locally by the pipeline (gitignored) |
| R2 `maridb-public/equasis/ownership_chains.csv` | Published artifact (CI pull/push) |

## When to update

| Trigger | Action |
|---------|--------|
| Demo / Cap Vista case-study prep | PR with new or corrected seed rows, merge before `data-publish` |
| New OFAC round on demo MMSIs | Update `manager_name` / `owner_name`, re-publish |
| Routine | About every 2 weeks, or ad hoc — not daily |

## Add or edit a row

1. Look up the vessel on Equasis (or OFAC SDN entry for the operator).
2. Add one CSV line: `mmsi`, `imo`, `vessel_name`, optional `owner_name`, `manager_name`, `parent_owner_name`.
3. Confirm the company string resolves on OpenSanctions (sanctioned company, not PSC-only records).
4. Open a PR; after merge, run **Actions → data-publish** (`workflow_dispatch`) or wait for the weekly schedule.
5. Verify (pick MMSI from output — do not assume a fixed demo vessel):

```bash
uv run python -m pipelines.ingest.equasis_ownership --db data/processed/ais/singapore.duckdb
uv run python .agents/skills/indago-inspect-watchlist/scripts/inspect_watchlist.py \
  --min-chain-hops 2 --limit 20
```

## Seed rows

Curated rows live in **`ownership_seed.csv`** in this directory. Row count and MMSI list change over time — read the CSV and `tests/test_equasis_ownership.py` (`EXPECTED_SEED_MMSIS`) rather than duplicating identifiers in docs.

`parent_owner_name` is optional; when set and resolved, `vessel_registry` emits `CONTROLLED_BY` for a third graph hop.
