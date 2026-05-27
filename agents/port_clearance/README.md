# Port Cyber Clearance — E2E orchestrator (W6)

One command runs the Cap Vista UC1 demo path:

1. Load `profiles/maritime_cyber/manifest.yaml`
2. Build graph (+ optional Parquet under `data/processed/maritime_cyber/`)
3. Evaluate pass/hold → `*_facts.json` + `*_evaluation_manifest.json`
4. Render certificate HTML (`eds document render-clearance`)
5. Seal audit chain (`eds audit sign-clearance`)
6. Print third-party verify instructions

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

# D1 scenario: hold -> remediation -> pass (one command)
uv run python -m agents.port_clearance.run_clearance vessel-hold --scenario hold-to-pass

# Eval + artefacts only (no eds)
uv run python -m agents.port_clearance.run_clearance vessel-hold --skip-render --skip-seal

# Machine-readable summary
uv run python -m agents.port_clearance.run_clearance vessel-hold --json
```

Outputs default to `data/processed/maritime_cyber/clearance_runs/<vessel_key>/`.

## Related

- W3: `pipelines/port_clearance_eval.py`
- W4: `edgesentry-rs/docs/port-cyber-clearance-audit.md`
- W5: `documaris/dist/*_port-cyber-clearance.html`
