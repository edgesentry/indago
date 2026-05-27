# `pipelines/maritime_cyber` — graph + evaluation

| Module | Workstream | Role |
|--------|------------|------|
| `graph.py` | **W2** | SBOM + CVE + `asset_map` → NetworkX + Parquet |
| `eval.py` | **W3** | Rule pack → pass/hold, `facts.json`, `decision_hash`, UC2 helpers |
| `audit_refs.py` | **D2** | `bom_baseline_ref`, `cve_snapshot_ref`, integrated snapshot fingerprint |
| `rules.py` | **W0** | Load `sg-cyber-clearance-v0.yaml` |

**CLIs (repo root):**

```bash
uv run python -m pipelines.maritime_cyber_graph vessel-hold vessel-clean
uv run python -m pipelines.port_clearance_eval vessel-hold --port-call-id port-call-demo-sgsin
uv run python -m pipelines.port_clearance_eval affected-vessels CVE-2021-44228
```

**D4 export** lives in sibling module `pipelines/export_vessel_graph.py` (not this package).

Full program map: [docs/ref-maritime-cyber-capvista.md](../../docs/ref-maritime-cyber-capvista.md).
