"""Tests for notify_metrics.py — trend display and delta formatting."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.notify_metrics import _delta_str, _format_body, _load_trend


# ---------------------------------------------------------------------------
# _delta_str
# ---------------------------------------------------------------------------

def test_delta_str_positive():
    result = _delta_str(0.392, 0.388)
    assert "↑" in result
    assert "0.0040" in result


def test_delta_str_negative():
    result = _delta_str(0.376, 0.388)
    assert "↓" in result
    assert "0.0120" in result


def test_delta_str_zero():
    result = _delta_str(0.388, 0.388)
    assert "→" in result


def test_delta_str_none_values():
    assert _delta_str(None, 0.388) == ""
    assert _delta_str(0.388, None) == ""
    assert _delta_str(None, None) == ""


def test_delta_str_integer_fmt():
    result = _delta_str(98, 97, "d")
    assert "↑" in result
    assert "1" in result


# ---------------------------------------------------------------------------
# _load_trend
# ---------------------------------------------------------------------------

def test_load_trend_reads_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "processed").mkdir(parents=True)
    trend = {"prev_p50": 0.388, "p50_7d_ago": 0.376, "prev_known_positives": 97}
    (tmp_path / "data" / "processed" / "metrics_trend.json").write_text(json.dumps(trend))

    result = _load_trend()
    assert result["prev_p50"] == pytest.approx(0.388)
    assert result["p50_7d_ago"] == pytest.approx(0.376)
    assert result["prev_known_positives"] == 97


def test_load_trend_returns_empty_when_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _load_trend() == {}


# ---------------------------------------------------------------------------
# _format_body — trend columns in email
# ---------------------------------------------------------------------------

def _make_report(p50=0.392, p50_lo=0.311, p50_hi=0.473, recall=1.0, positives=98):
    return {
        "metrics_summary": {
            "precision_at_50": {"mean": p50, "ci95_low": p50_lo, "ci95_high": p50_hi},
            "recall_at_200": {"mean": recall},
        },
        "total_known_cases": positives,
        "regions": ["singapore", "japan"],
        "skipped_regions": [],
        "region_summary": [],
        "generated_at_utc": "2026-05-15T13:00:00Z",
    }


def test_format_body_shows_prev_day_delta(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "processed").mkdir(parents=True)
    trend = {"prev_p50": 0.388, "prev_known_positives": 97}
    (tmp_path / "data" / "processed" / "metrics_trend.json").write_text(json.dumps(trend))

    _, html = _format_body(_make_report(), None, "http://ci", "snap-id")
    assert "vs prev day" in html
    assert "↑" in html  # p50 improved: 0.388 → 0.392


def test_format_body_shows_7day_trend(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "processed").mkdir(parents=True)
    trend = {"prev_p50": 0.388, "p50_7d_ago": 0.376, "prev_known_positives": 97}
    (tmp_path / "data" / "processed" / "metrics_trend.json").write_text(json.dumps(trend))

    _, html = _format_body(_make_report(), None, "http://ci", "snap-id")
    assert "0.3760" in html   # 7-day-ago value
    assert "0.3920" in html   # current value
    assert "7-day trend" in html


def test_format_body_no_trend_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _, html = _format_body(_make_report(), None, "http://ci", "snap-id")
    assert "Precision@50" in html
    assert "Known positives" in html


def test_format_body_regression_uses_trend_prev(tmp_path, monkeypatch):
    """Regression detection uses trend prev_p50 when PREVIOUS_P50 env is not set."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "processed").mkdir(parents=True)
    # Large drop: 0.420 → 0.392 (delta = -0.028 > threshold 0.01)
    trend = {"prev_p50": 0.420, "prev_known_positives": 98}
    (tmp_path / "data" / "processed" / "metrics_trend.json").write_text(json.dumps(trend))

    subject, _ = _format_body(_make_report(p50=0.392), None, "http://ci", "snap-id")
    assert "regression" in subject.lower() or "⚠️" in subject


def test_format_body_improvement_uses_trend_prev(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "processed").mkdir(parents=True)
    trend = {"prev_p50": 0.370, "prev_known_positives": 95}
    (tmp_path / "data" / "processed" / "metrics_trend.json").write_text(json.dumps(trend))

    subject, _ = _format_body(_make_report(p50=0.392), None, "http://ci", "snap-id")
    assert "✅" in subject or "improved" in subject.lower()
