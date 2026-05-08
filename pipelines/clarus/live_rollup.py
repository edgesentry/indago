"""clarus live rollup pipeline.

Reads all raw Parquet files from clarus-dev-public-raw and merges them into
two single files per site, so /admin/live loads one file per table instead of N.

Input  (via clarus analytics /api/live-index):
  live/{site_id}/heartbeats/{ts}.parquet   — one row per heartbeat cycle
  live/{site_id}/audit_chain/{ts}.parquet  — one row per alert event

Output (written to clarus-dev-public-raw via wrangler):
  rollup/{site_id}/heartbeats.parquet
  rollup/{site_id}/alerts.parquet
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

CLARUS_RAW_BUCKET = "clarus-dev-public-raw"

_CLARUS_ANALYTICS_URL = os.getenv(
    "CLARUS_ANALYTICS_URL",
    "https://feat-sg-bca-greenmark.clarus-d5d.pages.dev",
)


# ── Fetch helpers (same pattern as bca/aggregate.py) ──────────────────────────

def _fetch_live_index() -> dict:
    import httpx
    url = f"{_CLARUS_ANALYTICS_URL}/api/live-index?all=1"
    logger.debug("GET %s", url)
    resp = httpx.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _fetch_parquet(key: str) -> pl.DataFrame | None:
    import io
    import httpx
    url = f"{_CLARUS_ANALYTICS_URL}/data/raw/{key}"
    try:
        resp = httpx.get(url, timeout=15)
        resp.raise_for_status()
        return pl.read_parquet(io.BytesIO(resp.content))
    except Exception as exc:
        logger.warning("Failed to read %s: %s", key, exc)
        return None


def _wrangler_put(bucket: str, key: str, src: str) -> None:
    import subprocess
    result = subprocess.run(
        ["wrangler", "r2", "object", "put", f"{bucket}/{key}",
         "--file", src, "--content-type", "application/octet-stream", "--remote"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"wrangler put failed for {key}: {result.stderr.strip()}")


# ── Core logic ─────────────────────────────────────────────────────────────────

def _load_keys_by_site(keys: list[str]) -> dict[str, list[str]]:
    """Group keys by site_id: live/{site_id}/{table}/{ts}.parquet → {site_id: [keys]}"""
    by_site: dict[str, list[str]] = {}
    for k in keys:
        parts = k.split("/")
        if len(parts) < 4:
            continue
        site = parts[1]
        by_site.setdefault(site, []).append(k)
    return by_site


def merge_table(keys: list[str], days: int) -> pl.DataFrame:
    """Download and merge Parquet files, filtering to the past `days` days."""
    frames = [df for k in keys if (df := _fetch_parquet(k)) is not None]
    if not frames:
        return pl.DataFrame()
    merged = pl.concat(frames, how="diagonal_relaxed")
    if days > 0 and "timestamp_ms" in merged.columns:
        cutoff = int((time.time() - days * 86_400) * 1_000)
        merged = merged.filter(pl.col("timestamp_ms") >= cutoff)
    return merged.sort("timestamp_ms")


def write_rollup(df: pl.DataFrame, bucket: str, key: str) -> None:
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        tmp = f.name
    try:
        df.write_parquet(tmp)
        _wrangler_put(bucket, key, tmp)
        logger.info("Wrote %d rows → %s/%s", len(df), bucket, key)
    finally:
        os.unlink(tmp)


# ── Entry point ────────────────────────────────────────────────────────────────

def run(dry_run: bool = False, days: int = 90) -> dict[str, int]:
    """Merge raw Parquet files into per-site rollup files.

    Returns:
        dict mapping "{site_id}/{table}" → row count written.
    """
    logger.info("Fetching live index from %s…", _CLARUS_ANALYTICS_URL)
    index = _fetch_live_index()

    hb_by_site    = _load_keys_by_site(index.get("heartbeats", []))
    alert_by_site = _load_keys_by_site(index.get("alerts", []))
    all_sites     = sorted(set(hb_by_site) | set(alert_by_site))
    logger.info("Sites: %s", all_sites)

    results: dict[str, int] = {}

    for site in all_sites:
        for table, keys in [("heartbeats", hb_by_site.get(site, [])),
                             ("alerts",     alert_by_site.get(site, []))]:
            if not keys:
                logger.info("  %s/%s: no files", site, table)
                continue

            logger.info("  %s/%s: merging %d file(s)…", site, table, len(keys))
            df = merge_table(keys, days)
            logger.info("  %s/%s: %d rows after %d-day filter", site, table, len(df), days)

            if df.is_empty():
                continue

            out_key = f"rollup/{site}/{table}.parquet"
            results[f"{site}/{table}"] = len(df)

            if dry_run:
                logger.info("  [dry-run] would write → %s/%s", CLARUS_RAW_BUCKET, out_key)
            else:
                write_rollup(df, CLARUS_RAW_BUCKET, out_key)

    return results
