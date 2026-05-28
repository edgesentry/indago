# Port Cyber Clearance (Cap Vista) — moved to catena

**Canonical implementation:** [edgesentry/catena](https://github.com/edgesentry/catena)

Port Cyber pipeline, agents, fixtures, tests, and W5 UI contract were removed
from **indago** per [indago#201](https://github.com/edgesentry/indago/issues/201).
Use **catena** for all new work.

| Topic | Location |
|-------|----------|
| Migration tracker | [catena#1](https://github.com/edgesentry/catena/issues/1) |
| Decommission checklist | [catena DECOMMISSION.md](https://github.com/edgesentry/catena/blob/main/docs/DECOMMISSION.md) |
| Operating model | [system-overview](https://github.com/edgesentry/edgesentry-commercial/blob/main/docs/programs/20260630-capvista-products/analysis/system-overview.md) |
| Program / submission docs | [edgesentry-commercial](https://github.com/edgesentry/edgesentry-commercial/tree/main/docs/programs/20260630-capvista-products) |

## Run (catena + edgesentry-rs)

```bash
git clone https://github.com/edgesentry/catena.git && cd catena
git clone https://github.com/edgesentry/edgesentry-rs.git ../edgesentry-rs
make test-all
uv run python -m agents.port_clearance.run_clearance vessel-hold
```

Historical indago PRs (W0–D5) remain in git history for audit traceability.
