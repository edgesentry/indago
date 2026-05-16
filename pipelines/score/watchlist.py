"""Write candidate watchlist parquet output."""

from __future__ import annotations

import argparse
import os
from datetime import date, timezone

import polars as pl
from dotenv import load_dotenv

from pipelines.score.composite import DEFAULT_DB_PATH, compute_composite_scores
from pipelines.storage.config import output_uri
from pipelines.storage.config import read_parquet as read_parquet_uri
from pipelines.storage.config import write_parquet as write_parquet_uri

load_dotenv()

DEFAULT_OUTPUT_PATH = os.getenv("WATCHLIST_OUTPUT_PATH") or output_uri(
    "candidate_watchlist.parquet"
)


def _merge_first_flagged_at(
    new_df: pl.DataFrame,
    existing_path: str,
) -> pl.DataFrame:
    """Preserve first_flagged_at from the previous watchlist for vessels already tracked.

    For vessels appearing for the first time, sets first_flagged_at = today (UTC).
    For vessels already in the existing watchlist, keeps their original first_flagged_at.
    This gives a stable detection date that does not shift as last_seen advances,
    fixing the lead time calculation in validate_lead_time_ofac.py.
    """
    today = date.today().isoformat()

    try:
        existing = read_parquet_uri(existing_path)
    except Exception:
        existing = None

    if existing is not None and "first_flagged_at" in existing.columns:
        prior = existing.select(["mmsi", "first_flagged_at"])
        merged = new_df.join(prior, on="mmsi", how="left")
        return merged.with_columns(
            pl.when(pl.col("first_flagged_at").is_null())
            .then(pl.lit(today))
            .otherwise(pl.col("first_flagged_at"))
            .alias("first_flagged_at")
        )

    return new_df.with_columns(pl.lit(today).alias("first_flagged_at"))


def build_candidate_watchlist(
    db_path: str = DEFAULT_DB_PATH,
    existing_path: str | None = None,
) -> pl.DataFrame:
    df = compute_composite_scores(db_path)
    return _merge_first_flagged_at(df, existing_path or DEFAULT_OUTPUT_PATH)


def write_candidate_watchlist(df: pl.DataFrame, output_path: str = DEFAULT_OUTPUT_PATH) -> None:
    write_parquet_uri(df, output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build candidate watchlist parquet")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    watchlist = build_candidate_watchlist(args.db, existing_path=args.output)
    write_candidate_watchlist(watchlist, args.output)
    print(f"Watchlist rows written: {watchlist.height}")
