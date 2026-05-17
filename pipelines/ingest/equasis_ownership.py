"""
Build Equasis-format ownership CSV for vessel_registry (indago#169).

Resolves curated seed rows (MMSI + company names) against sanctions_entities,
optionally enriches from OpenSanctions FtM Vessel.owner links, and writes the CSV
consumed by ``vessel_registry --equasis-csv``.

Usage:
    uv run python -m pipelines.ingest.equasis_ownership --db data/processed/ais/singapore.duckdb
    uv run python -m pipelines.ingest.equasis_ownership --db ... --seed config/equasis/ownership_seed.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

import duckdb

CSV_COLUMNS = [
    "mmsi",
    "imo",
    "vessel_name",
    "owner_id",
    "owner_name",
    "owner_country",
    "owner_address_id",
    "owner_address",
    "manager_id",
    "manager_name",
    "manager_country",
    "parent_owner_id",
    "parent_owner_name",
    "parent_owner_country",
    "since",
    "until",
]

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEED = _REPO_ROOT / "config" / "equasis" / "ownership_seed.csv"
DEFAULT_OUT = _REPO_ROOT / "data" / "processed" / "equasis" / "ownership_chains.csv"
DEFAULT_JSONL = _REPO_ROOT / "data" / "raw" / "sanctions" / "opensanctions_entities.jsonl"


def _first_prop(props: dict, key: str) -> str | None:
    vals = props.get(key)
    if not vals:
        return None
    return str(vals[0]).strip() or None


def _normalize_mmsi(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = "".join(c for c in raw if c.isdigit())
    return digits if len(digits) == 9 else None


def _resolve_company_id(
    con: duckdb.DuckDBPyConnection,
    name: str,
) -> tuple[str, str, str] | None:
    """Return (entity_id, name, flag) for a sanctions company match."""
    name = name.strip()
    if not name:
        return None
    row = con.execute(
        """
        SELECT entity_id, name, COALESCE(flag, '') AS flag
        FROM sanctions_entities
        WHERE type IN ('Company', 'Organization', 'LegalEntity')
          AND lower(name) = lower(?)
        ORDER BY CASE WHEN list_source LIKE '%ofac%' THEN 0 ELSE 1 END
        LIMIT 1
        """,
        [name],
    ).fetchone()
    if row:
        return str(row[0]), str(row[1]), str(row[2])
    row = con.execute(
        """
        SELECT entity_id, name, COALESCE(flag, '') AS flag
        FROM sanctions_entities
        WHERE type IN ('Company', 'Organization', 'LegalEntity')
          AND lower(name) LIKE '%' || lower(?) || '%'
        ORDER BY length(name), CASE WHEN list_source LIKE '%ofac%' THEN 0 ELSE 1 END
        LIMIT 1
        """,
        [name],
    ).fetchone()
    if row:
        return str(row[0]), str(row[1]), str(row[2])
    return None


def _vessel_meta_row(
    con: duckdb.DuckDBPyConnection,
    mmsi: str,
) -> tuple[str, str, str]:
    row = con.execute(
        "SELECT COALESCE(imo,''), COALESCE(name,''), COALESCE(flag,'') FROM vessel_meta WHERE mmsi = ?",
        [mmsi],
    ).fetchone()
    if row:
        return str(row[0]), str(row[1]), str(row[2])
    return "", "", ""


def _rows_from_seed(
    con: duckdb.DuckDBPyConnection,
    seed_path: Path,
) -> list[dict[str, str]]:
    rows_out: list[dict[str, str]] = []
    with open(seed_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            mmsi = (row.get("mmsi") or "").strip()
            if not mmsi:
                continue
            imo_seed = (row.get("imo") or "").strip()
            name_seed = (row.get("vessel_name") or "").strip()
            imo_db, name_db, _ = _vessel_meta_row(con, mmsi)

            out: dict[str, str] = {col: "" for col in CSV_COLUMNS}
            out["mmsi"] = mmsi
            out["imo"] = imo_seed or imo_db
            out["vessel_name"] = name_seed or name_db

            owner_name = (row.get("owner_name") or "").strip()
            if owner_name:
                resolved = _resolve_company_id(con, owner_name)
                if resolved:
                    oid, oname, oflag = resolved
                    out["owner_id"] = oid
                    out["owner_name"] = oname
                    out["owner_country"] = oflag

            manager_name = (row.get("manager_name") or "").strip()
            if manager_name:
                resolved = _resolve_company_id(con, manager_name)
                if resolved:
                    mid, mname, mflag = resolved
                    out["manager_id"] = mid
                    out["manager_name"] = mname
                    out["manager_country"] = mflag

            parent_name = (row.get("parent_owner_name") or "").strip()
            if parent_name:
                resolved = _resolve_company_id(con, parent_name)
                if resolved:
                    pid, pname, pflag = resolved
                    out["parent_owner_id"] = pid
                    out["parent_owner_name"] = pname
                    out["parent_owner_country"] = pflag

            if out.get("owner_id") or out.get("manager_id"):
                rows_out.append(out)
    return rows_out


def _rows_from_opensanctions_jsonl(
    jsonl_path: Path,
    entity_index: dict[str, dict] | None = None,
) -> list[dict[str, str]]:
    """Extract Vessel.owner links from OpenSanctions FtM JSONL."""
    if not jsonl_path.is_file():
        return []

    index = entity_index or {}
    if not index:
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ent = json.loads(line)
                except json.JSONDecodeError:
                    continue
                eid = ent.get("id", "").strip()
                if not eid:
                    continue
                props = ent.get("properties") or {}
                index[eid] = {
                    "schema": ent.get("schema", ""),
                    "name": _first_prop(props, "name") or ent.get("caption", "") or eid,
                    "flag": _first_prop(props, "flag") or _first_prop(props, "country") or "",
                }

    rows_out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ent = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ent.get("schema") != "Vessel":
                continue
            props = ent.get("properties") or {}
            mmsi = _normalize_mmsi(_first_prop(props, "mmsi"))
            if not mmsi:
                continue
            owners = props.get("owner") or []
            if not owners:
                continue
            vessel_name = _first_prop(props, "name") or ent.get("caption", "") or ""
            imo_raw = _first_prop(props, "imoNumber") or ""
            imo = imo_raw[3:] if imo_raw.upper().startswith("IMO") else imo_raw

            for owner_id in owners:
                owner_id = str(owner_id).strip()
                if not owner_id:
                    continue
                key = (mmsi, owner_id)
                if key in seen:
                    continue
                seen.add(key)
                meta = index.get(owner_id, {})
                if meta.get("schema") not in ("Company", "Organization", "LegalEntity", "Person"):
                    continue
                rows_out.append(
                    {
                        "mmsi": mmsi,
                        "imo": imo,
                        "vessel_name": vessel_name,
                        "owner_id": owner_id,
                        "owner_name": meta.get("name", owner_id),
                        "owner_country": meta.get("flag", ""),
                        "owner_address_id": "",
                        "owner_address": "",
                        "manager_id": "",
                        "manager_name": "",
                        "manager_country": "",
                        "parent_owner_id": "",
                        "parent_owner_name": "",
                        "parent_owner_country": "",
                        "since": "",
                        "until": "",
                    }
                )
    return rows_out


def _merge_rows(primary: list[dict[str, str]], extra: list[dict[str, str]]) -> list[dict[str, str]]:
    """Prefer primary rows; add extra only for unseen MMSI."""
    by_mmsi = {r["mmsi"]: r for r in primary}
    for row in extra:
        mmsi = row["mmsi"]
        if mmsi not in by_mmsi:
            by_mmsi[mmsi] = row
        else:
            existing = by_mmsi[mmsi]
            for key in ("owner_id", "manager_id", "parent_owner_id"):
                if not existing.get(key) and row.get(key):
                    existing[key] = row[key]
                    if key == "owner_id":
                        existing["owner_name"] = row.get("owner_name", "")
                        existing["owner_country"] = row.get("owner_country", "")
                    if key == "manager_id":
                        existing["manager_name"] = row.get("manager_name", "")
                        existing["manager_country"] = row.get("manager_country", "")
                    if key == "parent_owner_id":
                        existing["parent_owner_name"] = row.get("parent_owner_name", "")
                        existing["parent_owner_country"] = row.get("parent_owner_country", "")
    return list(by_mmsi.values())


def build_ownership_csv(
    db_path: str,
    seed_path: Path | None = None,
    output_path: Path | None = None,
    jsonl_path: Path | None = None,
) -> int:
    """Write Equasis ownership CSV; returns row count."""
    seed = seed_path or DEFAULT_SEED
    out = output_path or DEFAULT_OUT
    jsonl = jsonl_path or DEFAULT_JSONL

    con = duckdb.connect(db_path, read_only=True)
    try:
        seed_rows = _rows_from_seed(con, seed) if seed.is_file() else []
    finally:
        con.close()

    os_rows = _rows_from_opensanctions_jsonl(jsonl) if jsonl.is_file() else []
    merged = _merge_rows(seed_rows, os_rows)

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(merged)

    return len(merged)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Equasis ownership CSV for vessel_registry")
    parser.add_argument("--db", required=True, help="DuckDB path (sanctions_entities must be loaded)")
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--jsonl", type=Path, default=DEFAULT_JSONL)
    parser.add_argument("--skip-jsonl", action="store_true", help="Do not parse OpenSanctions JSONL")
    args = parser.parse_args()

    n = build_ownership_csv(
        args.db,
        seed_path=args.seed,
        output_path=args.out,
        jsonl_path=None if args.skip_jsonl else args.jsonl,
    )
    print(f"Wrote {n} ownership rows → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
