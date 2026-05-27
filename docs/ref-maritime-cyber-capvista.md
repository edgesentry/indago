# Port Cyber Clearance — Cap Vista 6/30 (indago)

**Program:** [edgesentry-commercial — 20260630-capvista-products](https://github.com/edgesentry/edgesentry-commercial/tree/main/docs/programs/20260630-capvista-products/analysis)  
**Gates:** [mvp-build-checklist.md](https://github.com/edgesentry/edgesentry-commercial/blob/main/docs/programs/20260630-capvista-products/analysis/mvp-build-checklist.md) (G1–G12)  
**Status (2026-05-27):** indago workstreams **W0–W6** and demo track **D1–D4** are **done**. **W7** (submission artefacts) lives in `edgesentry-commercial`, not this repo.

---

## Workstream status (W0–W7)

| ID | Workstream | Primary repo | Status | indago / sibling paths |
|----|------------|--------------|--------|-------------------------|
| **W0** | Regulatory → rule pack + schema | commercial + indago | **Done** | `rules/sg-cyber-clearance-v0.yaml` · [requirements matrix](https://github.com/edgesentry/edgesentry-commercial/blob/main/docs/programs/20260630-capvista-products/analysis/regulatory-requirements-matrix.md) |
| **W1** | Fixtures + profile | indago | **Done** | `fixtures/` · `profiles/maritime_cyber/` |
| **W2** | Graph ingest + Parquet | indago | **Done** | `pipelines/maritime_cyber/graph.py` · `pipelines/maritime_cyber_graph.py` |
| **W3** | `port_clearance_eval` + UC2 | indago | **Done** | `pipelines/maritime_cyber/eval.py` · `pipelines/port_clearance_eval.py` |
| **W4** | Audit seal + verify | edgesentry-rs | **Done** | `eds audit sign-clearance` / `verify-clearance` — [port-cyber-clearance-audit.md](https://github.com/edgesentry/edgesentry-rs/blob/main/docs/port-cyber-clearance-audit.md) |
| **W5** | Clearance PDF/HTML | documaris | **Done** | `documaris/templates/port-cyber-clearance.md` · `documaris/dist/*_port-cyber-clearance.html` |
| **W6** | E2E orchestration | indago | **Done** | `agents/port_clearance/run_clearance.py` |
| **W7** | Submission (video, deck, portal) | edgesentry-commercial | **Open** | G8–G12, L1–L4 — [issue #153](https://github.com/edgesentry/edgesentry-commercial/issues/153) |

**Post-MVP (not portal blockers):** W8 fixture generator · W9 fleet graph viz (Cytoscape / arktrace S1). Minimal path export is covered by **D4** (`export_vessel_graph`).

---

## Demo track (D1–D4)

Runnable demo before deck/video; all implemented in indago unless noted.

| Track | Goal | Status | Entry point |
|-------|------|--------|-------------|
| **D1** | E7 → E9 → E10 → re-E7 (hold → patch → pass) | **Done** | `uv run python -m agents.port_clearance.run_clearance vessel-hold --scenario hold-to-pass` |
| **D2** | G11/G12 — `bom_baseline_ref`, `cve_snapshot_ref`, drift, `impacted_paths[]` | **Done** | `pipelines/maritime_cyber/audit_refs.py` · manifest/facts · [indago#192](https://github.com/edgesentry/indago/pull/192) |
| **D3** | Mock WORM publish + third-party retention verify | **Done** | `agents/port_clearance/worm_store.py` · `verify_retention.py` · [indago#193](https://github.com/edgesentry/indago/pull/193) |
| **D4** | Impacted-path JSON + HTML (explainability) | **Done** | `pipelines/export_vessel_graph.py` · wired in `run_clearance` · [indago#194](https://github.com/edgesentry/indago/pull/194) |
| **D4-3** | Deck frame from generated HTML | **Open** | [commercial#163](https://github.com/edgesentry/edgesentry-commercial/issues/163) (W7) |
| **D5** | Optional AI narrative (facts in, no pass/hold out) | **Open** | documaris + prompt guardrails |

---

## Quick start (W6 + D1 + D4)

```bash
cd indago
uv sync
export EDS_BIN=../edgesentry-rs/target/debug/eds   # optional for W4/W5 render+seal

# Single-vessel UC1 (W3 + W6 + D3 + D4)
uv run python -m agents.port_clearance.run_clearance vessel-hold

# Full lifecycle demo (D1)
uv run python -m agents.port_clearance.run_clearance vessel-hold --scenario hold-to-pass

# Eval only (no eds, no WORM, no graph export)
uv run python -m agents.port_clearance.run_clearance vessel-hold --skip-render --skip-seal --skip-worm --skip-graph-export

# D4 standalone → documaris + commercial submission snapshots (sibling repos)
uv run python -m pipelines.export_vessel_graph vessel-hold \
  --copy-to-documaris-dist \
  --copy-to-capvista-submission

# D3 retention verify
uv run python -m agents.port_clearance.verify_retention \
  data/processed/maritime_cyber/clearance_runs/vessel-hold/vessel-hold_port-call-demo-sgsin_worm_publish.json
```

**Outputs:** `data/processed/maritime_cyber/clearance_runs/<vessel_key>/` — facts, manifest, integrated snapshot, optional chain/HTML, WORM publish record, impacted-path JSON/HTML.

---

## Repository map (indago)

```text
profiles/maritime_cyber/
  manifest.yaml          # W1 — fixture paths, pipeline IDs
  ontology.yaml
fixtures/
  README.md              # W1 — synthetic disclosure + three vessels
  asset_map.yaml
  cve/snapshot-2026-05-26.json
  sbom/{vessel-hold,vessel-clean,vessel-thread}.json
rules/
  sg-cyber-clearance-v0.yaml   # W0
pipelines/
  maritime_cyber/
    graph.py             # W2
    eval.py              # W3
    audit_refs.py        # D2
    rules.py
  maritime_cyber_graph.py
  port_clearance_eval.py
  export_vessel_graph.py # D4
agents/port_clearance/
  run_clearance.py       # W6 (+ D1, D3, D4 hooks)
  worm_store.py          # D3
  verify_retention.py    # D3
  README.md
tests/maritime_cyber/    # CI for W2–W3, D1–D4
```

---

## Tests

```bash
uv run pytest tests/maritime_cyber/ -q
```

| Test module | Covers |
|-------------|--------|
| `test_graph.py` | W2 |
| `test_eval.py`, `test_rule_pack.py` | W3 |
| `test_audit_refs.py` | D2 |
| `test_run_clearance.py` | W6, D1 |
| `test_worm_store.py` | D3 |
| `test_export_vessel_graph.py` | D4 |
| `test_audit_integration.py` | W4 (when `eds` on PATH) |

---

## Lifecycle events (demo script)

| Event | Demo beat | indago / tool |
|-------|-----------|---------------|
| **E7** | Port cyber clearance (hold/pass) | `run_clearance` |
| **E9** | CVE domino / affected vessels | `port_clearance_eval affected-vessels` or D1 scenario artifact |
| **E10** | SBOM remediation | Patched SBOM under scenario dir; re-E7 |
| **re-E7** | Re-clearance after patch | Second `run_clearance` with `prior_decision_hash` |

See [lifecycle-events.md](https://github.com/edgesentry/edgesentry-commercial/blob/main/docs/programs/20260630-capvista-products/analysis/lifecycle-events.md) in commercial repo.

---

## Related docs

| Doc | Repo |
|-----|------|
| [agents/port_clearance/README.md](https://github.com/edgesentry/indago/blob/main/agents/port_clearance/README.md) | indago — operator commands |
| [fixtures/README.md](https://github.com/edgesentry/indago/blob/main/fixtures/README.md) | indago — W1 fixtures |
| [profiles/maritime_cyber/README.md](https://github.com/edgesentry/indago/blob/main/profiles/maritime_cyber/README.md) | indago — profile entry |
| [implementation-plan.md](https://github.com/edgesentry/edgesentry-commercial/blob/main/docs/programs/20260630-capvista-products/analysis/implementation-plan.md) | commercial |
| [completed-tasks.md](https://github.com/edgesentry/edgesentry-commercial/blob/main/docs/programs/20260630-capvista-products/analysis/completed-tasks.md) | commercial |
| [VALIDATION.md](https://github.com/edgesentry/edgesentry-commercial/blob/main/docs/programs/20260630-capvista-products/analysis/VALIDATION.md) | commercial — G11 WORM policy |
