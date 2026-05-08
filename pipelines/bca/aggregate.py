"""BCA Green Mark aggregation pipeline.

Reads clarus audit_chain Parquet from clarus-dev-public-raw, aggregates
EUI / COP / LPD sensor readings per outlet, and writes bca_outlet_features.parquet
to documaris-dev-public-analytics.

Data flow:
    clarus-dev-public-raw / live/{site_id}/audit_chain/*.parquet
        → aggregate()
        → documaris-dev-public-analytics / bca/bca_outlet_features.parquet
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

CLARUS_RAW_BUCKET = "clarus-dev-public-raw"
DOCUMARIS_ANALYTICS_BUCKET = "documaris-dev-public-analytics"
OUTPUT_KEY = "bca/bca_outlet_features.parquet"

# Maps clarus rule_id → output column name in bca_outlet_features
RULE_TO_COLUMN: dict[str, str] = {
    "EUI_PLATINUM_EXCEEDED": "eui_kwh_m2",
    "CHILLER_COP_EXCEEDED":  "chiller_cop",
    "LPD_PLATINUM_EXCEEDED": "lpd_w_m2",
}

# Default value when a metric has no data yet
_METRIC_DEFAULT = 0.0

_CF_ENDPOINT = "https://b8a0b09feb89390fb6e8cf4ef9294f48.r2.cloudflarestorage.com"

# Clarus analytics app URL — exposes /api/live-index (key listing) and
# /data/raw/{key} (Parquet download) without requiring R2 credentials.
# Override with CLARUS_ANALYTICS_URL env var once main branch is redeployed.
_CLARUS_ANALYTICS_URL = os.getenv(
    "CLARUS_ANALYTICS_URL",
    "https://feat-sg-bca-greenmark.clarus-d5d.pages.dev",
)


# ── R2 read helpers (via clarus analytics CF Pages — no credentials needed) ───

def list_audit_chain_keys() -> list[str]:
    """List audit_chain Parquet keys via the clarus live-index API.

    Calls /api/live-index on the clarus analytics deployment, which uses an
    R2 binding server-side. No client credentials required.
    """
    import httpx

    url = f"{_CLARUS_ANALYTICS_URL}/api/live-index"
    logger.debug("GET %s", url)
    resp = httpx.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    # "alerts" field = audit_chain Parquet keys
    return sorted(data.get("alerts", []))


def read_audit_chain(keys: list[str]) -> pl.DataFrame:
    """Download and concatenate audit_chain Parquet files via clarus /data/raw/."""
    import io
    import httpx

    if not keys:
        return pl.DataFrame()

    frames: list[pl.DataFrame] = []
    for key in keys:
        url = f"{_CLARUS_ANALYTICS_URL}/data/raw/{key}"
        try:
            resp = httpx.get(url, timeout=15)
            resp.raise_for_status()
            df = pl.read_parquet(io.BytesIO(resp.content))
            frames.append(df)
        except Exception as exc:
            logger.warning("Failed to read %s: %s", key, exc)

    if not frames:
        return pl.DataFrame()
    return pl.concat(frames, how="diagonal_relaxed")


# ── R2 write helper (wrangler — same approach as clarus edge daemon) ───────────

def _wrangler_put(bucket: str, key: str, src: str) -> None:
    import subprocess

    result = subprocess.run(
        [
            "wrangler", "r2", "object", "put", f"{bucket}/{key}",
            "--file", src, "--content-type", "application/octet-stream", "--remote",
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"wrangler r2 object put failed for {key}: {result.stderr.strip()}")


# ── Aggregation ────────────────────────────────────────────────────────────────

def derive_operator_id(site_id: str) -> str:
    """Extract operator prefix from site_id.

    'MCH-OUTLET-042' → 'MCH'
    'ACM-001'        → 'ACM'
    """
    return site_id.split("-")[0]


def compute_score(alert_count: int) -> float:
    """Compliance score 0–100. Each alert costs 5 points, minimum 0."""
    return max(0.0, 100.0 - alert_count * 5.0)


def aggregate(df: pl.DataFrame) -> pl.DataFrame:
    """Aggregate audit_chain events into one row per outlet.

    Input columns expected (from clarus audit_chain Parquet):
        timestamp_ms, site_id, rule_id, measured_value, threshold,
        severity, evidence_quality

    Output columns:
        outlet_id, operator_id, eui_kwh_m2, chiller_cop, lpd_w_m2,
        alert_count, score, period_start, period_end
    """
    if df.is_empty():
        return pl.DataFrame(schema={
            "outlet_id":   pl.Utf8,
            "operator_id": pl.Utf8,
            "eui_kwh_m2":  pl.Float64,
            "chiller_cop": pl.Float64,
            "lpd_w_m2":    pl.Float64,
            "alert_count": pl.Int32,
            "score":       pl.Float64,
            "period_start": pl.Int64,
            "period_end":   pl.Int64,
        })

    bca_rules = list(RULE_TO_COLUMN.keys())
    bca = df.filter(pl.col("rule_id").is_in(bca_rules))

    if bca.is_empty():
        return pl.DataFrame(schema={
            "outlet_id":   pl.Utf8,
            "operator_id": pl.Utf8,
            "eui_kwh_m2":  pl.Float64,
            "chiller_cop": pl.Float64,
            "lpd_w_m2":    pl.Float64,
            "alert_count": pl.Int32,
            "score":       pl.Float64,
            "period_start": pl.Int64,
            "period_end":   pl.Int64,
        })

    # Period bounds per site
    period = bca.group_by("site_id").agg(
        pl.col("timestamp_ms").min().alias("period_start"),
        pl.col("timestamp_ms").max().alias("period_end"),
        pl.len().alias("alert_count"),
    )

    # Latest measured_value per (site_id, rule_id)
    latest = (
        bca.sort("timestamp_ms", descending=True)
        .group_by(["site_id", "rule_id"])
        .first()
        .select(["site_id", "rule_id", "measured_value"])
    )

    # Pivot: one column per rule_id value (columns named by rule_id)
    pivoted = latest.pivot(
        on="rule_id",
        index="site_id",
        values="measured_value",
        aggregate_function="first",
    )

    # Rename rule_id columns → metric column names, then fill any missing metrics
    rename_map = {rule: col for rule, col in RULE_TO_COLUMN.items() if rule in pivoted.columns}
    if rename_map:
        pivoted = pivoted.rename(rename_map)
    for col in RULE_TO_COLUMN.values():
        if col not in pivoted.columns:
            pivoted = pivoted.with_columns(pl.lit(_METRIC_DEFAULT).cast(pl.Float64).alias(col))

    # Join period info
    result = pivoted.join(period, on="site_id", how="left")

    # Add derived columns
    result = result.with_columns([
        pl.col("site_id").alias("outlet_id"),
        pl.col("site_id").map_elements(derive_operator_id, return_dtype=pl.Utf8).alias("operator_id"),
        pl.col("alert_count").cast(pl.Int32),
        pl.col("eui_kwh_m2").cast(pl.Float64).fill_null(_METRIC_DEFAULT),
        pl.col("chiller_cop").cast(pl.Float64).fill_null(_METRIC_DEFAULT),
        pl.col("lpd_w_m2").cast(pl.Float64).fill_null(_METRIC_DEFAULT),
    ]).with_columns(
        pl.col("alert_count").map_elements(compute_score, return_dtype=pl.Float64).alias("score"),
    ).select([
        "outlet_id", "operator_id",
        "eui_kwh_m2", "chiller_cop", "lpd_w_m2",
        "alert_count", "score",
        "period_start", "period_end",
    ])

    return result


def write_features(df: pl.DataFrame, bucket: str = DOCUMARIS_ANALYTICS_BUCKET) -> None:
    """Write aggregated features to documaris-dev-public-analytics R2 via wrangler."""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        tmp = f.name
    try:
        df.write_parquet(tmp)
        _wrangler_put(bucket, OUTPUT_KEY, tmp)
        logger.info("Wrote %d outlet(s) → %s/%s", len(df), bucket, OUTPUT_KEY)
    finally:
        os.unlink(tmp)


# ── Entry point ────────────────────────────────────────────────────────────────

def run(dry_run: bool = False) -> pl.DataFrame:
    """Full pipeline: read clarus → aggregate → write documaris.

    Args:
        dry_run: If True, skip the R2 write and return the DataFrame only.

    Returns:
        Aggregated bca_outlet_features DataFrame.
    """
    logger.info("Listing audit_chain keys via %s…", _CLARUS_ANALYTICS_URL)
    keys = list_audit_chain_keys()
    logger.info("Found %d audit_chain file(s)", len(keys))

    if not keys:
        logger.warning("No audit_chain data found — nothing to aggregate")
        return pl.DataFrame()

    logger.info("Reading %d file(s)…", len(keys))
    raw = read_audit_chain(keys)
    logger.info("Loaded %d event(s) total", len(raw))

    features = aggregate(raw)
    logger.info("Aggregated %d outlet(s)", len(features))

    if not dry_run:
        write_features(features)
    else:
        logger.info("Dry run — skipping R2 write")

    return features
