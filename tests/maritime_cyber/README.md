# Maritime cyber tests — Cap Vista PoC

```bash
uv run pytest tests/maritime_cyber/ -q
```

| Module | Workstream / demo |
|--------|-------------------|
| `test_graph.py` | W2 — graph build, CVE edges |
| `test_rule_pack.py` | W0/W3 — rule pack load |
| `test_eval.py` | W3 — pass/hold, `decision_hash`, UC2 |
| `test_audit_refs.py` | D2 — G11/G12 refs, drift fingerprint |
| `test_run_clearance.py` | W6, D1 — E2E + hold-to-pass scenario |
| `test_worm_store.py` | D3 — mock WORM publish/verify |
| `test_export_vessel_graph.py` | D4 — JSON/HTML export |
| `test_fleet_demo.py` | W8 — fleet-demo fixtures, fleet eval + golden `decision_hash` |
| `test_audit_integration.py` | W4 — `eds` sign/verify (skipped if no binary) |

Program context: [docs/ref-maritime-cyber-capvista.md](../../docs/ref-maritime-cyber-capvista.md).
