# Profile: `maritime_cyber` (Port Cyber Clearance PoC)

Cap Vista 6/30 — Singapore port cyber clearance on synthetic fixtures.

| Item | Path |
|------|------|
| Manifest | [manifest.yaml](manifest.yaml) |
| Ontology | [ontology.yaml](ontology.yaml) |
| Rule pack | [../../rules/sg-cyber-clearance-v0.yaml](../../rules/sg-cyber-clearance-v0.yaml) |
| Fixtures | [../../fixtures/README.md](../../fixtures/README.md) |

## Workstreams (this profile)

| ID | Status | indago component |
|----|--------|------------------|
| W0 | Done | Rule pack + commercial requirements matrix |
| W1 | Done | Fixtures + this manifest |
| W2 | Done | `pipelines/maritime_cyber/graph.py` |
| W3 | Done | `pipelines/maritime_cyber/eval.py` |
| W6 | Done | `agents/port_clearance/run_clearance.py` |
| D1–D4 | Done | Scenario, audit refs, WORM, `export_vessel_graph` |

**W4/W5** — sibling repos (`edgesentry-rs`, `documaris`). **W7** — submission docs in `edgesentry-commercial`.

Full status and commands: [docs/ref-maritime-cyber-capvista.md](../../docs/ref-maritime-cyber-capvista.md).
