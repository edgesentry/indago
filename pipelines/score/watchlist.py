"""Write candidate watchlist parquet output."""

from __future__ import annotations

import argparse
import os
from datetime import date

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

# Authoritative first-detection dates for vessels whose first_flagged_at was
# incorrectly initialised to the bootstrap date (2026-05-16) because the field
# did not exist when they first entered the watchlist.
# Values are detection_window_start from the static snapshot of 2026-05-06,
# derived as: designation_date - lead_days (indago#141).
_FIRST_FLAGGED_OVERRIDES: dict[str, str] = {
    "314189000": "2026-03-21",  # Bangus  — OFAC 2026-04-24, lead 34d
    "352179000": "2026-03-17",  # Horae   — OFAC+EU 2026-04-15, lead 29d
    "352001906": "2026-03-17",  # Anaya   — OFAC+EU 2026-04-15, lead 29d
    "352002243": "2026-03-23",  # Anika   — OFAC+EU 2026-04-15, lead 23d
    "352001849": "2026-03-24",  # Bellaris — OFAC+EU 2026-04-15, lead 22d
    "352001907": "2026-03-24",  # Versa   — OFAC+EU 2026-04-15, lead 22d
}

# Any first_flagged_at on or after this date was set during the bootstrap run
# and should be replaced with the override value if one exists.
_BOOTSTRAP_DATE = "2026-05-16"


def _apply_overrides(df: pl.DataFrame) -> pl.DataFrame:
    """Replace bootstrap-era first_flagged_at with known correct detection dates."""
    if "first_flagged_at" not in df.columns or not _FIRST_FLAGGED_OVERRIDES:
        return df
    return df.with_columns(
        pl.struct(["mmsi", "first_flagged_at"]).map_elements(
            lambda r: (
                _FIRST_FLAGGED_OVERRIDES[r["mmsi"]]
                if r["mmsi"] in _FIRST_FLAGGED_OVERRIDES
                and (r["first_flagged_at"] or "") >= _BOOTSTRAP_DATE
                else r["first_flagged_at"]
            ),
            return_dtype=pl.Utf8,
        ).alias("first_flagged_at")
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
        result = merged.with_columns(
            pl.when(pl.col("first_flagged_at").is_null())
            .then(pl.lit(today))
            .otherwise(pl.col("first_flagged_at"))
            .alias("first_flagged_at")
        )
        return _apply_overrides(result)

    return _apply_overrides(new_df.with_columns(pl.lit(today).alias("first_flagged_at")))


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


if __name__ == "__main__":
    main()
