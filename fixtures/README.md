# Maritime cyber fixtures — Port Cyber Clearance PoC (W1)

**Status:** **W1 done** — three-vessel fleet + pinned CVE snapshot for Cap Vista G1–G2.

Program context: [docs/ref-maritime-cyber-capvista.md](../docs/ref-maritime-cyber-capvista.md).

## Disclosure (portal honesty)

> PoC uses **public CVE feeds** and **representative SBOM fixtures** with a documented **synthetic OT inventory map** (`asset_map.yaml`). Production deployment replaces fixtures with operator-signed manifests and optional OCEANS-X integration.

This matches [maritime-cyber-governance-use-cases.md](https://github.com/edgesentry/edgesentry-commercial/blob/main/docs/strategy/maritime-cyber-governance-use-cases.md) §3.

## Layout

| Path | Layer | Gate / WS |
|------|-------|-----------|
| `cve/snapshot-2026-05-26.json` | Public (pinned OSV subset — Log4Shell) | G1 · W1 |
| `sbom/vessel-hold.json` | Synthetic — critical CVE on ECDIS path | G2 · W1 |
| `sbom/vessel-clean.json` | Synthetic — no open criticals | G2 · W1 |
| `sbom/vessel-thread.json` | Synthetic — clean + signed ProcessLog (UC3) | G2 · W1 |
| `asset_map.yaml` | **Synthetic bridge** — OT ↔ firmware ↔ SBOM components | W0 schema · W1 |
| `port_calls/*.json` | Synthetic — OCEANS-X-shaped port-call events | W1 |
| `process_logs/*.json` | Synthetic — yard patch / scan records | W1 |

## Synthetic bridge (`asset_map.yaml`)

`asset_map.yaml` is **not** from a live yard or class society. It models IACS UR E27-style CBS inventory fields (`ecu_zone`, `network_zone`, `cbs_category`, `safety_function`) and links physical assets to firmware images and SBOM component references.

**Pilot path:** Replace this file with a customer-signed inventory manifest — graph and rule evaluation pipeline unchanged.

## Demo narrative (three vessels)

| Vessel key | Expected clearance | Story |
|------------|-------------------|--------|
| `vessel-hold` | **hold** | Stale Log4j-class component on ECDIS navigation path (pinned CVE) |
| `vessel-clean` | **pass** | No rule triggers on current snapshot |
| `vessel-thread` | **pass** | Clean SBOM + signed yard `ProcessLog` for UC3 timeline slide |

## Fleet-demo pack (W8)

Demo-enhanced tier (**12 vessels**, multi-asset): `fleet-demo/` — see [fleet-demo/README.md](fleet-demo/README.md).

```bash
uv run python scripts/generate_maritime_cyber_fixtures.py --seed 42 --verify
```

Profile: `profiles/maritime_cyber/fleet-demo-manifest.yaml`

## Profile and rules

- Profile manifest: `profiles/maritime_cyber/manifest.yaml`
- Rule pack: `rules/sg-cyber-clearance-v0.yaml`
- Requirements matrix: `edgesentry-commercial/.../regulatory-requirements-matrix.md`
