"""Attach GDELT geopolitical context to watchlist rows (indago#156).

GDELT does not alter composite scores — only enriches analyst-facing columns.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import polars as pl

from pipelines.storage.config import lance_db_uri

# Fields exported to watchlist JSON (keep parquet rows compact).
_GDELT_EXPORT_FIELDS = (
    "event_id",
    "event_date",
    "description",
    "source_url",
    "actor1_country",
    "actor2_country",
    "event_root_code",
)

_GDELT_STRUCT = pl.Struct(
    {
        "gdelt_context_json": pl.Utf8,
        "gdelt_event_count": pl.Int32,
    }
)


def _slim_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: ev[k] for k in _GDELT_EXPORT_FIELDS if k in ev} for ev in events]


def _filter_by_window(events: list[dict[str, Any]], days_window: int) -> list[dict[str, Any]]:
    if days_window <= 0 or not events:
        return events
    cutoff = (date.today() - timedelta(days=days_window)).strftime("%Y%m%d")
    return [e for e in events if str(e.get("event_date") or "") >= cutoff]


def lookup_gdelt_context(
    flag_country: str,
    vessel_name: str = "",
    *,
    lance_path: str | None = None,
    n: int = 3,
    days_window: int = 90,
    _cache: dict[tuple[str, str], list[dict[str, Any]]] | None = None,
) -> tuple[str | None, int]:
    """Return (gdelt_context_json, gdelt_event_count) for one vessel."""
    from pipelines.ingest.gdelt import query_gdelt_context

    flag = (flag_country or "").strip().upper()
    name = (vessel_name or "").strip()
    if not flag and not name:
        return None, 0

    key = (flag, name)
    cache = _cache if _cache is not None else {}
    if key not in cache:
        path = lance_path or lance_db_uri()
        try:
            raw = query_gdelt_context(flag, name, n=n, lance_path=path, days_window=days_window)
        except Exception:
            raw = []
        cache[key] = _filter_by_window(raw, days_window)

    events = _slim_events(cache[key])
    if not events:
        return None, 0
    return json.dumps(events), len(events)


def enrich_watchlist_gdelt(
    df: pl.DataFrame,
    *,
    lance_path: str | None = None,
    n: int = 3,
    days_window: int = 90,
    skip_gdelt: bool = False,
) -> pl.DataFrame:
    """Add ``gdelt_context_json`` and ``gdelt_event_count`` without changing scores."""
    if skip_gdelt or df.is_empty():
        return df.with_columns(
            pl.lit(None, dtype=pl.Utf8).alias("gdelt_context_json"),
            pl.lit(0, dtype=pl.Int32).alias("gdelt_event_count"),
        )

    drop_cols = [c for c in ("gdelt_context_json", "gdelt_event_count") if c in df.columns]
    if drop_cols:
        df = df.drop(drop_cols)

    if "flag" not in df.columns:
        df = df.with_columns(pl.lit("").alias("flag"))
    if "vessel_name" not in df.columns:
        df = df.with_columns(pl.lit("").alias("vessel_name"))

    cache: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def _row(r: dict[str, Any]) -> dict[str, Any]:
        j, c = lookup_gdelt_context(
            r.get("flag") or "",
            r.get("vessel_name") or "",
            lance_path=lance_path,
            n=n,
            days_window=days_window,
            _cache=cache,
        )
        return {"gdelt_context_json": j, "gdelt_event_count": c}

    return df.with_columns(
        pl.struct(["flag", "vessel_name"])
        .map_elements(_row, return_dtype=_GDELT_STRUCT)
        .alias("_gdelt")
    ).unnest("_gdelt")
