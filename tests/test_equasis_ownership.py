"""Tests for Equasis ownership CSV builder (indago#169)."""

from __future__ import annotations

import csv

import duckdb

from pipelines.ingest.equasis_ownership import build_ownership_csv
from pipelines.ingest.vessel_registry import build_graph_tables


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
