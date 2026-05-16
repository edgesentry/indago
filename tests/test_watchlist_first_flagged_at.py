"""Tests for _merge_first_flagged_at in pipelines/score/watchlist.py (indago#141)."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from pipelines.score.watchlist import _merge_first_flagged_at


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_new_df(mmsis: list[str]) -> pl.DataFrame:
    return pl.DataFrame({"mmsi": mmsis, "confidence": [0.5] * len(mmsis)})


def _make_existing(tmp_path, rows: list[dict]) -> str:
    p = tmp_path / "watchlist.parquet"
    pl.DataFrame(rows).write_parquet(p)
    return str(p)


# ---------------------------------------------------------------------------
# No existing watchlist
# ---------------------------------------------------------------------------


def test_new_vessels_get_today_when_no_existing_file(tmp_path):
    df = _make_new_df(["111111111"])
    result = _merge_first_flagged_at(df, str(tmp_path / "missing.parquet"))
    assert "first_flagged_at" in result.columns
    assert result["first_flagged_at"][0] == date.today().isoformat()


def test_all_new_vessels_get_today(tmp_path):
    df = _make_new_df(["aaa", "bbb", "ccc"])
    result = _merge_first_flagged_at(df, str(tmp_path / "missing.parquet"))
    today = date.today().isoformat()
    assert all(v == today for v in result["first_flagged_at"].to_list())


# ---------------------------------------------------------------------------
# Existing watchlist without first_flagged_at column
# ---------------------------------------------------------------------------


def test_legacy_existing_without_column_gets_today(tmp_path):
    """If existing parquet has no first_flagged_at column, treat as cold start."""
    existing_path = _make_existing(tmp_path, [{"mmsi": "aaa", "confidence": 0.4}])
    df = _make_new_df(["aaa"])
    result = _merge_first_flagged_at(df, existing_path)
    assert result["first_flagged_at"][0] == date.today().isoformat()


# ---------------------------------------------------------------------------
# Existing watchlist with first_flagged_at column
# ---------------------------------------------------------------------------


def test_existing_vessels_preserve_first_flagged_at(tmp_path):
    """Vessels already in the watchlist keep their original first_flagged_at."""
    original_date = "2026-03-15"
    existing_path = _make_existing(tmp_path, [
        {"mmsi": "111111111", "confidence": 0.5, "first_flagged_at": original_date},
    ])
    df = _make_new_df(["111111111"])
    result = _merge_first_flagged_at(df, existing_path)
    row = result.filter(pl.col("mmsi") == "111111111").row(0, named=True)
    assert row["first_flagged_at"] == original_date


def test_new_vessels_get_today_alongside_existing(tmp_path):
    """New vessels get today; existing vessels keep their original date."""
    original_date = "2026-01-10"
    existing_path = _make_existing(tmp_path, [
        {"mmsi": "existing_vessel", "confidence": 0.5, "first_flagged_at": original_date},
    ])
    df = _make_new_df(["existing_vessel", "new_vessel"])
    result = _merge_first_flagged_at(df, existing_path)

    existing_row = result.filter(pl.col("mmsi") == "existing_vessel").row(0, named=True)
    new_row = result.filter(pl.col("mmsi") == "new_vessel").row(0, named=True)

    assert existing_row["first_flagged_at"] == original_date
    assert new_row["first_flagged_at"] == date.today().isoformat()


def test_idempotent_across_two_runs(tmp_path):
    """Running twice with the same vessel must not change first_flagged_at."""
    existing_path = _make_existing(tmp_path, [
        {"mmsi": "aaa", "confidence": 0.5, "first_flagged_at": "2026-02-01"},
    ])
    df = _make_new_df(["aaa"])
    result1 = _merge_first_flagged_at(df, existing_path)
    # Simulate writing result1 back and running again
    result1.write_parquet(existing_path)
    result2 = _merge_first_flagged_at(df, existing_path)

    assert result2.filter(pl.col("mmsi") == "aaa")["first_flagged_at"][0] == "2026-02-01"


def test_multiple_existing_vessels_all_preserved(tmp_path):
    original_dates = {
        "vessel_a": "2026-01-05",
        "vessel_b": "2026-02-20",
        "vessel_c": "2026-03-30",
    }
    existing_path = _make_existing(tmp_path, [
        {"mmsi": mmsi, "confidence": 0.5, "first_flagged_at": d}
        for mmsi, d in original_dates.items()
    ])
    df = _make_new_df(list(original_dates.keys()))
    result = _merge_first_flagged_at(df, existing_path)
    for mmsi, expected_date in original_dates.items():
        row = result.filter(pl.col("mmsi") == mmsi).row(0, named=True)
        assert row["first_flagged_at"] == expected_date, f"{mmsi} date drifted"


def test_output_row_count_matches_input(tmp_path):
    existing_path = _make_existing(tmp_path, [
        {"mmsi": "aaa", "confidence": 0.5, "first_flagged_at": "2026-01-01"},
    ])
    df = _make_new_df(["aaa", "bbb", "ccc"])
    result = _merge_first_flagged_at(df, existing_path)
    assert result.height == 3
