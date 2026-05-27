# Port Cyber Clearance — E2E orchestrator (W6)

One command runs the Cap Vista UC1 demo path:

1. Load `profiles/maritime_cyber/manifest.yaml`
2. Build graph (+ optional Parquet under `data/processed/maritime_cyber/`)
3. Evaluate pass/hold → `*_facts.json` + `*_evaluation_manifest.json`
4. Render certificate HTML (`eds document render-clearance`)
5. Seal audit chain (`eds audit sign-clearance`)
6. Publish artefacts to **mock WORM** store (G11 — append-only, content-addressed)
7. Print third-party verify instructions

## Prerequisites

- indago dependencies: `uv sync`
- **eds** with W4/W5 subcommands: `cargo build -p eds` in sibling `edgesentry-rs`, or `export EDS_BIN=...`

## Usage

```bash
cd indago

# Full E2E (hold vessel)
uv run python -m agents.port_clearance.run_clearance vessel-hold

# Pass vessel
uv run python -m agents.port_clearance.run_clearance vessel-clean

# D1 scenario: E7 -> E9 -> E10 -> re-E7 (hold, domino query, patch, pass)
uv run python -m agents.port_clearance.run_clearance vessel-hold --scenario hold-to-pass

Lifecycle beats:
- **E7** baseline clearance (`vessel-hold` → hold)
- **E9** UC2 affected-vessel query (`CVE-2021-44228` → `vessel-hold`)
- **E10** SBOM remediation (log4j-core 2.14.1 → 2.15.0)
- **re-E7** re-clearance (pass; new `decision_hash`, linked via `prior_decision_hash`)

When `eds` is available, each sealed run auto-runs `eds audit verify-clearance` after `sign-clearance`.

# Eval + artefacts only (no eds)
uv run python -m agents.port_clearance.run_clearance vessel-hold --skip-render --skip-seal

# Skip immutable publish (G11 demo off)
uv run python -m agents.port_clearance.run_clearance vessel-hold --skip-worm

# Machine-readable summary
uv run python -m agents.port_clearance.run_clearance vessel-hold --json
```

Outputs default to `data/processed/maritime_cyber/clearance_runs/<vessel_key>/`.

## Immutable retention (G11 / D3)

After each run, artefacts are copied to a **mock WORM** directory (append-only; `chmod 444` on objects):

- `*_integrated_snapshot.json`
- `*_evaluation_manifest.json`
- `*_clearance_chain.json` (when sealed)

Publish record: `*_worm_publish.json` (object keys + SHA-256 + `published_at`).

Default store: `data/processed/maritime_cyber/worm_store/clearance/`  
Override: `export CLEARANCE_WORM_ROOT=/path/to/worm`

### Third-party retention verify

```bash
uv run python -m agents.port_clearance.verify_retention \
  data/processed/maritime_cyber/clearance_runs/vessel-hold/vessel-hold_port-call-demo-sgsin_worm_publish.json
```

Steps performed: fetch each WORM object → verify SHA-256 → `assert_manifest_audit_refs` on stored manifest.

Production pilots may set `CLEARANCE_WORM_URI` (future); **Cap Vista PoC does not require R2 upload**.

## Related

- W3: `pipelines/port_clearance_eval.py`
- W4: `edgesentry-rs/docs/port-cyber-clearance-audit.md`
- W5: `documaris/dist/*_port-cyber-clearance.html`
