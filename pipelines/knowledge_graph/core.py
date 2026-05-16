"""
KnowledgeGraph — query API over Lance ownership graph tables (indago#154).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import polars as pl

from pipelines.features.graph_store import ALL_SCHEMAS, NODE_SCHEMAS, load_tables
from pipelines.features.ownership_graph import (
    MAX_HOPS,
    _build_vessel_ownership_chain,
    _chain_export_mmsis,
    _compute_sanctions_distance,
)


@dataclass(frozen=True)
class SanctionsPath:
    """Human- and machine-readable sanctions exposure path for one vessel."""

    mmsi: str
    sanctions_distance: int
    hops: list[dict[str, Any]]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "mmsi": self.mmsi,
            "sanctions_distance": self.sanctions_distance,
            "hops": self.hops,
            "summary": self.summary,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class KnowledgeGraph:
    """Read-only knowledge graph over maritime ownership / sanctions Lance tables."""

    def __init__(self, tables: dict[str, Any]) -> None:
        self._tables = tables

    @classmethod
    def from_db_path(cls, db_path: str) -> KnowledgeGraph:
        return cls(load_tables(db_path))

    def query_sanctions_path(self, mmsi: str) -> SanctionsPath | None:
        """Return multi-hop sanctions path for one MMSI (C1 demo / analyst brief)."""
        mmsis = set(_chain_export_mmsis(self._tables))
        if mmsi not in mmsis:
            return None

        dist_df = _compute_sanctions_distance(self._tables)
        row = dist_df.filter(pl.col("mmsi") == mmsi)
        distance = int(row["sanctions_distance"][0]) if len(row) else MAX_HOPS

        hops = _build_vessel_ownership_chain(mmsi, self._tables)
        summary = _path_summary(mmsi, distance, hops)
        return SanctionsPath(
            mmsi=mmsi,
            sanctions_distance=distance,
            hops=hops,
            summary=summary,
        )

    def query_sanctions_paths(
        self,
        mmsis: list[str] | None = None,
        *,
        max_distance: int = 3,
    ) -> list[SanctionsPath]:
        """Batch sanctions paths; default all vessels with graph coverage."""
        targets = mmsis if mmsis is not None else _chain_export_mmsis(self._tables)
        out: list[SanctionsPath] = []
        for mmsi in targets:
            path = self.query_sanctions_path(mmsi)
            if path is None:
                continue
            if path.sanctions_distance <= max_distance:
                out.append(path)
        return out

    def nodes_frame(self) -> pl.DataFrame:
        """Normalized node table for Parquet export (R2 / arktrace)."""
        rows: list[dict[str, Any]] = []
        for node_type in NODE_SCHEMAS:
            table = self._tables.get(node_type)
            if table is None or len(table) == 0:
                continue
            for rec in pl.from_arrow(table).to_dicts():
                node_id = _node_id(node_type, rec)
                rows.append(
                    {
                        "node_id": node_id,
                        "node_type": node_type,
                        "name": _node_name(node_type, rec),
                        "country": str(rec.get("country") or rec.get("code") or ""),
                        "mmsi": str(rec.get("mmsi") or ""),
                        "imo": str(rec.get("imo") or ""),
                    }
                )
        if not rows:
            return pl.DataFrame(
                schema={
                    "node_id": pl.Utf8,
                    "node_type": pl.Utf8,
                    "name": pl.Utf8,
                    "country": pl.Utf8,
                    "mmsi": pl.Utf8,
                    "imo": pl.Utf8,
                }
            )
        return pl.DataFrame(rows)

    def edges_frame(self) -> pl.DataFrame:
        """Normalized edge table for Parquet export."""
        rel_types = [k for k in ALL_SCHEMAS if k not in NODE_SCHEMAS]
        rows: list[dict[str, Any]] = []
        for rel in rel_types:
            table = self._tables.get(rel)
            if table is None or len(table) == 0:
                continue
            for rec in pl.from_arrow(table).to_dicts():
                rows.append(
                    {
                        "src_id": str(rec.get("src_id") or ""),
                        "dst_id": str(rec.get("dst_id") or ""),
                        "rel_type": rel,
                        "list": str(rec.get("list") or ""),
                        "date": str(rec.get("date") or ""),
                        "since": str(rec.get("since") or ""),
                        "until": str(rec.get("until") or ""),
                    }
                )
        if not rows:
            return pl.DataFrame(
                schema={
                    "src_id": pl.Utf8,
                    "dst_id": pl.Utf8,
                    "rel_type": pl.Utf8,
                    "list": pl.Utf8,
                    "date": pl.Utf8,
                    "since": pl.Utf8,
                    "until": pl.Utf8,
                }
            )
        return pl.DataFrame(rows)

    def analyst_paths_frame(self) -> pl.DataFrame:
        """One row per MMSI: sanctions_distance + JSON path + text summary."""
        paths = self.query_sanctions_paths()
        if not paths:
            return pl.DataFrame(
                schema={
                    "mmsi": pl.Utf8,
                    "sanctions_distance": pl.Int32,
                    "ownership_chain": pl.Utf8,
                    "path_summary": pl.Utf8,
                    "hop_count": pl.Int32,
                }
            )
        return pl.DataFrame(
            {
                "mmsi": [p.mmsi for p in paths],
                "sanctions_distance": [p.sanctions_distance for p in paths],
                "ownership_chain": [json.dumps(p.hops) for p in paths],
                "path_summary": [p.summary for p in paths],
                "hop_count": [len(p.hops) for p in paths],
            }
        )


def _node_id(node_type: str, rec: dict[str, Any]) -> str:
    if node_type == "Vessel":
        return f"vessel:{rec.get('mmsi')}"
    if node_type == "Company":
        return f"company:{rec.get('id')}"
    if node_type == "Country":
        return f"country:{rec.get('code')}"
    if node_type == "Address":
        return f"address:{rec.get('address_id')}"
    if node_type == "VesselName":
        return f"name:{rec.get('name')}"
    if node_type == "SanctionsRegime":
        return f"regime:{rec.get('name')}"
    if node_type == "Port":
        return f"port:{rec.get('code')}"
    if node_type == "SanctionEntry":
        return f"sanction:{rec.get('entry_id')}"
    return f"{node_type.lower()}:{rec}"


def _node_name(node_type: str, rec: dict[str, Any]) -> str:
    if node_type == "Vessel":
        return str(rec.get("name") or rec.get("mmsi") or "")
    if node_type == "Company":
        return str(rec.get("name") or rec.get("id") or "")
    if node_type == "Country":
        return str(rec.get("code") or "")
    if node_type == "SanctionsRegime":
        return str(rec.get("name") or "")
    if node_type == "Port":
        return str(rec.get("name") or rec.get("code") or "")
    if node_type == "SanctionEntry":
        return str(rec.get("list") or rec.get("entry_id") or "")
    return str(rec.get("name") or "")


def _path_summary(mmsi: str, distance: int, hops: list[dict[str, Any]]) -> str:
    if not hops:
        return f"MMSI {mmsi}: no ownership graph path"
    parts: list[str] = []
    for hop in hops:
        kind = hop.get("kind", "?")
        name = hop.get("name", "?")
        rel = hop.get("relation", "")
        sanc = " [SANCTIONED]" if hop.get("sanctioned") else ""
        parts.append(f"{kind}:{name}" + (f" ({rel})" if rel else "") + sanc)
    chain = " → ".join(parts)
    if distance == MAX_HOPS:
        return f"MMSI {mmsi}: no sanctions linkage ({chain})"
    return f"MMSI {mmsi}: sanctions_distance={distance} — {chain}"
