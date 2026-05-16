"""Tests for pipelines.score.gdelt_enrichment (indago#156)."""

from __future__ import annotations

import json
from unittest.mock import patch

import polars as pl

from pipelines.score.gdelt_enrichment import enrich_watchlist_gdelt, lookup_gdelt_context


def _sample_events() -> list[dict]:
    return [
        {
            "event_id": "99",
            "event_date": "20260410",
            "description": "Iran reduced relations with Cambodia in South China Sea on 2026-04-10.",
            "source_url": "http://example.com/ir-kh",
            "actor1_country": "IR",
            "actor2_country": "KH",
            "event_root_code": "16",
            "goldstein_scale": -7.0,
        }
    ]


@patch("pipelines.ingest.gdelt.query_gdelt_context")
def test_lookup_returns_json_and_count(mock_query):
    mock_query.return_value = _sample_events()
    ctx, count = lookup_gdelt_context("IR", "ALPHA TANKER", lance_path="/tmp/gdelt.lance")
    assert count == 1
    assert ctx is not None
    parsed = json.loads(ctx)
    assert parsed[0]["actor1_country"] == "IR"
    assert "Iran" in parsed[0]["description"]


@patch("pipelines.ingest.gdelt.query_gdelt_context")
def test_lookup_caches_by_flag_and_name(mock_query):
    mock_query.return_value = _sample_events()
    cache: dict = {}
    lookup_gdelt_context("IR", "VESSEL A", _cache=cache)
    lookup_gdelt_context("IR", "VESSEL A", _cache=cache)
    assert mock_query.call_count == 1


@patch("pipelines.ingest.gdelt.query_gdelt_context")
def test_lookup_empty_when_query_fails(mock_query):
    mock_query.side_effect = RuntimeError("no lance")
    ctx, count = lookup_gdelt_context("IR", "ALPHA")
    assert ctx is None
    assert count == 0


@patch("pipelines.ingest.gdelt.query_gdelt_context")
def test_enrich_watchlist_adds_columns(mock_query):
    mock_query.return_value = _sample_events()
    df = pl.DataFrame(
        {
            "mmsi": ["111111111"],
            "flag": ["IR"],
            "vessel_name": ["ALPHA"],
            "confidence": [0.5],
        }
    )
    out = enrich_watchlist_gdelt(df, lance_path="/tmp/gdelt.lance")
    assert "gdelt_context_json" in out.columns
    assert "gdelt_event_count" in out.columns
    assert out["gdelt_event_count"][0] == 1
    assert out["gdelt_context_json"][0] is not None


def test_skip_gdelt_leaves_null_context():
    df = pl.DataFrame({"mmsi": ["1"], "flag": ["IR"], "vessel_name": ["A"], "confidence": [0.5]})
    out = enrich_watchlist_gdelt(df, skip_gdelt=True)
    assert out["gdelt_event_count"][0] == 0
    assert out["gdelt_context_json"][0] is None
