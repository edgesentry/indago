"""Unit tests for BCA aggregation pipeline (pipelines/bca/aggregate.py).

All tests run without R2 access — pure function tests on in-memory DataFrames.
"""

from __future__ import annotations

import polars as pl
import pytest

from pipelines.bca.aggregate import (
    RULE_TO_COLUMN,
    aggregate,
    compute_score,
    derive_operator_id,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_audit_chain(rows: list[dict]) -> pl.DataFrame:
    """Build a minimal audit_chain DataFrame matching the clarus schema."""
    schema = {
        "timestamp_ms":     pl.Int64,
        "site_id":          pl.Utf8,
        "rule_id":          pl.Utf8,
        "measured_value":   pl.Float64,
        "threshold":        pl.Float64,
        "severity":         pl.Utf8,
        "evidence_quality": pl.Utf8,
    }
    return pl.DataFrame(rows, schema=schema)


# ── derive_operator_id ─────────────────────────────────────────────────────────

def test_derive_operator_id_standard():
    assert derive_operator_id("MCH-OUTLET-042") == "MCH"


def test_derive_operator_id_short():
    assert derive_operator_id("ACM-001") == "ACM"


def test_derive_operator_id_no_separator():
    assert derive_operator_id("SITEONLY") == "SITEONLY"


# ── compute_score ──────────────────────────────────────────────────────────────

def test_compute_score_zero_alerts():
    assert compute_score(0) == 100.0


def test_compute_score_one_alert():
    assert compute_score(1) == 95.0


def test_compute_score_clamps_to_zero():
    assert compute_score(100) == 0.0
    assert compute_score(999) == 0.0


def test_compute_score_twenty_alerts():
    assert compute_score(20) == 0.0


# ── aggregate ─────────────────────────────────────────────────────────────────

def test_aggregate_empty_returns_correct_schema():
    result = aggregate(pl.DataFrame())
    assert result.is_empty()
    assert "outlet_id" in result.columns
    assert "score" in result.columns


def test_aggregate_no_bca_rules_returns_empty():
    df = make_audit_chain([{
        "timestamp_ms": 1_000, "site_id": "MCH-OUTLET-042",
        "rule_id": "RESTRICTED_ZONE_APPROACH", "measured_value": 3.0,
        "threshold": 5.0, "severity": "High", "evidence_quality": "Certified",
    }])
    result = aggregate(df)
    assert result.is_empty()


def test_aggregate_single_outlet_single_rule():
    df = make_audit_chain([
        {"timestamp_ms": 1_000, "site_id": "MCH-OUTLET-042",
         "rule_id": "EUI_PLATINUM_EXCEEDED", "measured_value": 120.0,
         "threshold": 115.0, "severity": "High", "evidence_quality": "Certified"},
    ])
    result = aggregate(df)
    assert len(result) == 1
    row = result.row(0, named=True)
    assert row["outlet_id"] == "MCH-OUTLET-042"
    assert row["operator_id"] == "MCH"
    assert abs(row["eui_kwh_m2"] - 120.0) < 1e-6
    assert row["alert_count"] == 1
    assert row["score"] == 95.0


def test_aggregate_latest_value_wins():
    df = make_audit_chain([
        {"timestamp_ms": 1_000, "site_id": "MCH-OUTLET-042",
         "rule_id": "EUI_PLATINUM_EXCEEDED", "measured_value": 118.0,
         "threshold": 115.0, "severity": "High", "evidence_quality": "Certified"},
        {"timestamp_ms": 2_000, "site_id": "MCH-OUTLET-042",
         "rule_id": "EUI_PLATINUM_EXCEEDED", "measured_value": 122.5,
         "threshold": 115.0, "severity": "High", "evidence_quality": "Certified"},
    ])
    result = aggregate(df)
    row = result.row(0, named=True)
    assert abs(row["eui_kwh_m2"] - 122.5) < 1e-6


def test_aggregate_all_three_metrics():
    df = make_audit_chain([
        {"timestamp_ms": 1_000, "site_id": "MCH-OUTLET-042",
         "rule_id": "EUI_PLATINUM_EXCEEDED", "measured_value": 120.0,
         "threshold": 115.0, "severity": "High", "evidence_quality": "Certified"},
        {"timestamp_ms": 1_001, "site_id": "MCH-OUTLET-042",
         "rule_id": "CHILLER_COP_EXCEEDED", "measured_value": 0.67,
         "threshold": 0.65, "severity": "High", "evidence_quality": "Certified"},
        {"timestamp_ms": 1_002, "site_id": "MCH-OUTLET-042",
         "rule_id": "LPD_PLATINUM_EXCEEDED", "measured_value": 15.8,
         "threshold": 15.0, "severity": "High", "evidence_quality": "Certified"},
    ])
    result = aggregate(df)
    row = result.row(0, named=True)
    assert abs(row["eui_kwh_m2"] - 120.0) < 1e-6
    assert abs(row["chiller_cop"] - 0.67) < 1e-6
    assert abs(row["lpd_w_m2"] - 15.8) < 1e-6
    assert row["alert_count"] == 3
    assert row["score"] == 85.0


def test_aggregate_multiple_outlets():
    df = make_audit_chain([
        {"timestamp_ms": 1_000, "site_id": "MCH-OUTLET-042",
         "rule_id": "EUI_PLATINUM_EXCEEDED", "measured_value": 120.0,
         "threshold": 115.0, "severity": "High", "evidence_quality": "Certified"},
        {"timestamp_ms": 2_000, "site_id": "MCH-OUTLET-043",
         "rule_id": "EUI_PLATINUM_EXCEEDED", "measured_value": 117.0,
         "threshold": 115.0, "severity": "High", "evidence_quality": "Certified"},
    ])
    result = aggregate(df)
    assert len(result) == 2
    outlet_ids = set(result["outlet_id"].to_list())
    assert outlet_ids == {"MCH-OUTLET-042", "MCH-OUTLET-043"}


def test_aggregate_period_bounds():
    df = make_audit_chain([
        {"timestamp_ms": 1_000, "site_id": "MCH-OUTLET-042",
         "rule_id": "EUI_PLATINUM_EXCEEDED", "measured_value": 120.0,
         "threshold": 115.0, "severity": "High", "evidence_quality": "Certified"},
        {"timestamp_ms": 5_000, "site_id": "MCH-OUTLET-042",
         "rule_id": "EUI_PLATINUM_EXCEEDED", "measured_value": 121.0,
         "threshold": 115.0, "severity": "High", "evidence_quality": "Certified"},
    ])
    result = aggregate(df)
    row = result.row(0, named=True)
    assert row["period_start"] == 1_000
    assert row["period_end"] == 5_000


def test_aggregate_output_columns():
    df = make_audit_chain([{
        "timestamp_ms": 1_000, "site_id": "ACM-001",
        "rule_id": "EUI_PLATINUM_EXCEEDED", "measured_value": 118.0,
        "threshold": 115.0, "severity": "High", "evidence_quality": "Certified",
    }])
    result = aggregate(df)
    expected = {"outlet_id", "operator_id", "eui_kwh_m2", "chiller_cop",
                "lpd_w_m2", "alert_count", "score", "period_start", "period_end"}
    assert set(result.columns) == expected


def test_filter_window_removes_old_events():
    from pipelines.bca.aggregate import filter_window
    import time

    now_ms = int(time.time() * 1000)
    old_ms = now_ms - 91 * 86_400_000  # 91 days ago
    recent_ms = now_ms - 1 * 86_400_000  # 1 day ago

    df = make_audit_chain([
        {"timestamp_ms": old_ms,    "site_id": "MCH-OUTLET-042",
         "rule_id": "EUI_PLATINUM_EXCEEDED", "measured_value": 120.0,
         "threshold": 115.0, "severity": "High", "evidence_quality": "Certified"},
        {"timestamp_ms": recent_ms, "site_id": "MCH-OUTLET-042",
         "rule_id": "EUI_PLATINUM_EXCEEDED", "measured_value": 118.0,
         "threshold": 115.0, "severity": "High", "evidence_quality": "Certified"},
    ])
    result = filter_window(df, days=90)
    assert len(result) == 1
    assert result["timestamp_ms"][0] == recent_ms


def test_filter_window_zero_days_returns_all():
    from pipelines.bca.aggregate import filter_window
    import time

    now_ms = int(time.time() * 1000)
    old_ms = now_ms - 365 * 86_400_000

    df = make_audit_chain([
        {"timestamp_ms": old_ms, "site_id": "MCH-OUTLET-042",
         "rule_id": "EUI_PLATINUM_EXCEEDED", "measured_value": 120.0,
         "threshold": 115.0, "severity": "High", "evidence_quality": "Certified"},
    ])
    result = filter_window(df, days=0)
    assert len(result) == 1


def test_rule_to_column_mapping_complete():
    assert set(RULE_TO_COLUMN.keys()) == {
        "EUI_PLATINUM_EXCEEDED", "CHILLER_COP_EXCEEDED", "LPD_PLATINUM_EXCEEDED"
    }
    assert set(RULE_TO_COLUMN.values()) == {"eui_kwh_m2", "chiller_cop", "lpd_w_m2"}
