"""Tests for Equasis ownership CSV builder (indago#169)."""

from __future__ import annotations

import csv

import duckdb

from pipelines.ingest.equasis_ownership import DEFAULT_SEED, build_ownership_csv
from pipelines.ingest.vessel_registry import build_graph_tables

SEED_HEADERS = [
    "mmsi",
    "imo",
    "vessel_name",
    "owner_name",
    "manager_name",
    "parent_owner_name",
]

# C1 case studies + Arktrace / direct-sanction demo vessels (config/equasis/README.md)
EXPECTED_SEED_MMSIS = frozenset(
    {
        "314189000",  # Bangus
        "352179000",  # Horae
        "352001906",  # Anaya
        "352002243",  # Anika
        "352001849",  # Bellaris
        "352001907",  # Versa
        "312171000",  # ANHONA
        "457133000",  # PIONEER 92
        "273449240",  # DOBRYNYA
        "273312060",  # SCF ENTERPRISE
    }
)


def _seed_sanctions(db_path: str) -> None:
    con = duckdb.connect(db_path)
    try:
        con.execute(
            """
            INSERT INTO sanctions_entities
                (entity_id, name, mmsi, imo, flag, type, list_source)
            VALUES
                ('co-harry', 'Harry Victor Ship Management and Operation L.L.C.', NULL, NULL, 'AE', 'Company', 'ofac_sdn'),
                ('co-rosneft', 'Rosnefteflot', NULL, NULL, 'RU', 'Company', 'ofac_sdn'),
                ('co-parent', 'Evil Parent Holdings', NULL, NULL, 'VG', 'Company', 'ofac_sdn')
            """
        )
        con.execute(
            """
            INSERT INTO vessel_meta (mmsi, imo, name, flag, ship_type)
            VALUES ('312171000', '9354521', 'ANHONA', 'BZ', 82)
            """
        )
    finally:
        con.close()


def test_build_ownership_csv_resolves_manager(tmp_db, tmp_path):
    _seed_sanctions(tmp_db)
    seed = tmp_path / "seed.csv"
    seed.write_text(
        "mmsi,imo,vessel_name,owner_name,manager_name,parent_owner_name\n"
        "312171000,9354521,ANHONA,,Harry Victor Ship Management,\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.csv"
    n = build_ownership_csv(tmp_db, seed_path=seed, output_path=out, jsonl_path=tmp_path / "missing.jsonl")
    assert n == 1
    rows = list(csv.DictReader(out.open()))
    assert rows[0]["mmsi"] == "312171000"
    assert rows[0]["manager_id"] == "co-harry"
    assert "Harry Victor" in rows[0]["manager_name"]


def test_build_ownership_csv_parent_and_graph(tmp_db, tmp_path):
    _seed_sanctions(tmp_db)
    seed = tmp_path / "seed.csv"
    seed.write_text(
        "mmsi,imo,vessel_name,owner_name,manager_name,parent_owner_name\n"
        "312171000,9354521,ANHONA,,Harry Victor Ship Management,Evil Parent Holdings\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.csv"
    build_ownership_csv(tmp_db, seed_path=seed, output_path=out, jsonl_path=tmp_path / "x.jsonl")
    tables = build_graph_tables(tmp_db, equasis_csv=str(out))
    assert len(tables["MANAGED_BY"]) == 1
    assert len(tables["CONTROLLED_BY"]) == 1
    cb = tables["CONTROLLED_BY"]
    assert cb["src_id"][0].as_py() == "co-harry"
    assert cb["dst_id"][0].as_py() == "co-parent"


def test_ownership_seed_csv_schema_and_coverage():
    assert DEFAULT_SEED.is_file(), f"missing committed seed: {DEFAULT_SEED}"
    with open(DEFAULT_SEED, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == SEED_HEADERS
        rows = list(reader)

    assert len(rows) == len(EXPECTED_SEED_MMSIS)
    mmsis = [row["mmsi"].strip() for row in rows]
    assert len(mmsis) == len(set(mmsis)), "duplicate MMSI in ownership_seed.csv"
    assert set(mmsis) == EXPECTED_SEED_MMSIS

    for row in rows:
        mmsi = row["mmsi"].strip()
        assert len(mmsi) == 9 and mmsi.isdigit(), mmsi
        company = (row.get("owner_name") or "").strip() or (row.get("manager_name") or "").strip()
        assert company, f"{mmsi} needs owner_name or manager_name for sanctions resolution"


def _seed_committed_seed_sanctions(db_path: str) -> None:
    """OFAC-like company names matching config/equasis/ownership_seed.csv."""
    companies = [
        ("co-costin", "Costin Shipping Limited", "CN"),
        ("co-fleet", "Fleet Tanqo Private Limited", "IN"),
        ("co-anika", "Anika Lines Inc.", "MH"),
        ("co-nardie", "Nardie International S.A.", "MH"),
        (
            "co-harry",
            "Harry Victor Ship Management and Operation L.L.C",
            "AE",
        ),
        ("co-logos", "Logos Marine Pte. Ltd.", "SG"),
        ("co-rosmorport", "FSUE Rosmorport Far Eastern Basin Branch", "RU"),
        ("co-scf", "Joint Stock Company Sovcomflot", "RU"),
    ]
    con = duckdb.connect(db_path)
    try:
        for entity_id, name, flag in companies:
            con.execute(
                """
                INSERT INTO sanctions_entities
                    (entity_id, name, mmsi, imo, flag, type, list_source)
                VALUES (?, ?, NULL, NULL, ?, 'Company', 'ofac_sdn')
                """,
                [entity_id, name, flag],
            )
    finally:
        con.close()


COMMITTED_SEED_RESOLUTIONS: dict[str, tuple[str, str]] = {
    "314189000": ("owner_id", "co-costin"),
    "352179000": ("manager_id", "co-fleet"),
    "352001906": ("manager_id", "co-fleet"),
    "352002243": ("manager_id", "co-anika"),
    "352001849": ("manager_id", "co-nardie"),
    "352001907": ("manager_id", "co-fleet"),
    "312171000": ("manager_id", "co-harry"),
    "457133000": ("manager_id", "co-logos"),
    "273449240": ("manager_id", "co-rosmorport"),
    "273312060": ("manager_id", "co-scf"),
}


def test_build_ownership_csv_committed_seed_resolves(tmp_db, tmp_path):
    _seed_committed_seed_sanctions(tmp_db)
    out = tmp_path / "out.csv"
    n = build_ownership_csv(
        tmp_db,
        seed_path=DEFAULT_SEED,
        output_path=out,
        jsonl_path=tmp_path / "missing.jsonl",
    )
    assert n == len(EXPECTED_SEED_MMSIS)
    rows = {r["mmsi"]: r for r in csv.DictReader(out.open())}
    assert set(rows) == EXPECTED_SEED_MMSIS
    for mmsi, (id_field, entity_id) in COMMITTED_SEED_RESOLUTIONS.items():
        assert rows[mmsi][id_field] == entity_id, mmsi
