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
5. Verify:

```bash
uv run python -m pipelines.ingest.equasis_ownership --db data/processed/ais/singapore.duckdb
uv run python .agents/skills/indago-inspect-watchlist/scripts/inspect_watchlist.py \
  --sanctions-distance 1 2 --min-chain-hops 2
```

## Seed coverage (2026-05)

| MMSI | Vessel | `manager_name` / `owner_name` | Notes |
|------|--------|-------------------------------|--------|
| 314189000 | Bangus | Costin Shipping Limited (owner) | C1 case study; OFAC 2026-04-24 |
| 352179000 | Horae | Fleet Tanqo Private Limited | C1 |
| 352001906 | Anaya | Fleet Tanqo Private Limited | C1 |
| 352002243 | Anika | Anika Lines Inc. | C1 |
| 352001849 | Bellaris | Nardie International S.A. | C1 |
| 352001907 | Versa | Fleet Tanqo Private Limited | C1 |
| 312171000 | ANHONA | Harry Victor Ship Management | Manager hop demo |
| 457133000 | PIONEER 92 | Logos Marine Pte. Ltd. | Arktrace test case |
| 273449240 | DOBRYNYA | Rosnefteflot | Direct sanction + operator |
| 273312060 | SCF ENTERPRISE | Sovcomflot | Direct sanction + operator |

`parent_owner_name` is optional; when set and resolved, `vessel_registry` emits `CONTROLLED_BY` for a third graph hop.
