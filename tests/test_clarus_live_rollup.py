"""Unit tests for pipelines/clarus/live_rollup.py — no R2 access."""

from __future__ import annotations

import time

import polars as pl
import pytest

from pipelines.clarus.live_rollup import _load_keys_by_site, merge_table


# ── _load_keys_by_site ────────────────────────────────────────────────────────

def test_groups_heartbeat_keys_by_site():
    keys = [
        "live/MCH-OUTLET-042/heartbeats/1000.parquet",
        "live/MCH-OUTLET-042/heartbeats/2000.parquet",
        "live/ACM-OUTLET-001/heartbeats/1500.parquet",
    ]
    result = _load_keys_by_site(keys)
    assert set(result.keys()) == {"MCH-OUTLET-042", "ACM-OUTLET-001"}
    assert len(result["MCH-OUTLET-042"]) == 2
    assert len(result["ACM-OUTLET-001"]) == 1


def test_groups_alert_keys_by_site():
    keys = [
        "live/MCH-OUTLET-042/audit_chain/1000.parquet",
        "live/MCH-OUTLET-042/audit_chain/2000.parquet",
    ]
    result = _load_keys_by_site(keys)
    assert "MCH-OUTLET-042" in result
    assert len(result["MCH-OUTLET-042"]) == 2


def test_skips_malformed_keys():
    keys = ["live/only_two_parts", "live/site/table_no_ts"]
    result = _load_keys_by_site(keys)
    assert result == {}


def test_empty_input():
    assert _load_keys_by_site([]) == {}


# ── merge_table ────────────────────────────────────────────────────────────────

def make_heartbeat_df(timestamps_ms: list[int], site: str = "MCH") -> pl.DataFrame:
    return pl.DataFrame({
        "timestamp_ms":      timestamps_ms,
        "site_id":           [site] * len(timestamps_ms),
        "calibration_status": ["VALID"] * len(timestamps_ms),
        "drift_score":        [0.02] * len(timestamps_ms),
        "certified_count":    [0] * len(timestamps_ms),
    })


def test_merge_table_empty_keys(monkeypatch):
    monkeypatch.setattr("pipelines.clarus.live_rollup._fetch_parquet", lambda k: None)
    result = merge_table([], days=90)
    assert result.is_empty()


def test_merge_table_combines_frames(monkeypatch):
    now_ms = int(time.time() * 1000)
    df1 = make_heartbeat_df([now_ms - 10_000, now_ms - 5_000])
    df2 = make_heartbeat_df([now_ms - 2_000])

    frames = {"key1": df1, "key2": df2}
    monkeypatch.setattr("pipelines.clarus.live_rollup._fetch_parquet",
                        lambda k: frames.get(k))

    result = merge_table(["key1", "key2"], days=90)
    assert len(result) == 3
    # sorted by timestamp_ms ascending
    assert result["timestamp_ms"][0] < result["timestamp_ms"][1]


def test_merge_table_filters_old_rows(monkeypatch):
    now_ms = int(time.time() * 1000)
    old_ms = now_ms - 91 * 86_400_000
    df = make_heartbeat_df([old_ms, now_ms - 1_000])

    monkeypatch.setattr("pipelines.clarus.live_rollup._fetch_parquet",
                        lambda k: df)

    result = merge_table(["key1"], days=90)
    assert len(result) == 1
    assert result["timestamp_ms"][0] == now_ms - 1_000


def test_merge_table_days_zero_keeps_all(monkeypatch):
    now_ms = int(time.time() * 1000)
    old_ms = now_ms - 365 * 86_400_000
    df = make_heartbeat_df([old_ms, now_ms - 1_000])

    monkeypatch.setattr("pipelines.clarus.live_rollup._fetch_parquet",
                        lambda k: df)

    result = merge_table(["key1"], days=0)
    assert len(result) == 2


def test_merge_table_skips_failed_fetches(monkeypatch):
    now_ms = int(time.time() * 1000)
    df = make_heartbeat_df([now_ms - 1_000])

    def fetch(k: str):
        return df if k == "good" else None

    monkeypatch.setattr("pipelines.clarus.live_rollup._fetch_parquet", fetch)
    result = merge_table(["good", "bad"], days=90)
    assert len(result) == 1
