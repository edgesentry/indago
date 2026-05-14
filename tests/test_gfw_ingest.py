"""Unit tests for GFW SAR/Sentinel-2 EO ingest (fetch_gfw_detections).

These tests mock the HTTP layer so no real API calls are made.
They cover response parsing, deduplication, and error handling.
"""

from datetime import UTC
from unittest.mock import MagicMock, patch

import pytest

from pipelines.ingest.eo_gfw import fetch_gfw_detections

TOKEN = "test-token"
JAPAN = (115.0, 25.0, 145.0, 48.0)


def _make_vessel(vessel_id: str, date: str, lat: float, lon: float, detections: int = 1) -> dict:
    return {
        "vesselId": vessel_id,
        "date": date,
        "entryTimestamp": "2026-04-15T10:00:00Z",
        "exitTimestamp": "2026-04-16T10:00:00Z",
        "lat": lat,
        "lon": lon,
        "detections": detections,
        "mmsi": "123456789",
        "flag": "JP",
        "geartype": "FISHING",
        "vesselType": "FISHING",
    }


def _mock_response(vessels: list[dict], dataset_key: str = "public-global-sar-presence:v4.0"):
    resp = MagicMock()
    resp.status_code = 200
    resp.is_success = True
    resp.json.return_value = {
        "total": len(vessels),
        "entries": [{dataset_key: vessels}] if vessels else [],
    }
    return resp


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_parses_sar_response():
    vessel = _make_vessel("v1", "2026-04", 35.0, 139.0, detections=2)

    with patch("httpx.post") as mock_post:
        mock_post.return_value = _mock_response([vessel])
        recs = fetch_gfw_detections(bbox=JAPAN, days=30, api_token=TOKEN)

    assert len(recs) > 0
    r = recs[0]
    assert r["lat"] == 35.0
    assert r["lon"] == 139.0
    assert r["source"] == "gfw-sar"
    assert r["detected_at"].tzinfo is UTC
    assert 0 < r["confidence"] <= 1.0


def test_confidence_capped_at_one():
    vessel = _make_vessel("v1", "2026-04", 35.0, 139.0, detections=10)

    with patch("httpx.post") as mock_post:
        mock_post.return_value = _mock_response([vessel])
        recs = fetch_gfw_detections(bbox=JAPAN, days=30, api_token=TOKEN)

    assert recs[0]["confidence"] == 1.0


def test_skips_records_missing_vessel_id():
    bad = _make_vessel("v1", "2026-04", 35.0, 139.0)
    bad["vesselId"] = ""

    with patch("httpx.post") as mock_post:
        mock_post.return_value = _mock_response([bad])
        recs = fetch_gfw_detections(bbox=JAPAN, days=30, api_token=TOKEN)

    assert recs == []


def test_skips_records_missing_timestamp():
    bad = _make_vessel("v1", "2026-04", 35.0, 139.0)
    bad["entryTimestamp"] = ""
    bad["exitTimestamp"] = ""

    with patch("httpx.post") as mock_post:
        mock_post.return_value = _mock_response([bad])
        recs = fetch_gfw_detections(bbox=JAPAN, days=30, api_token=TOKEN)

    assert recs == []


def test_empty_entries_returns_empty():
    with patch("httpx.post") as mock_post:
        mock_post.return_value = _mock_response([])
        recs = fetch_gfw_detections(bbox=JAPAN, days=30, api_token=TOKEN)

    assert recs == []


# ---------------------------------------------------------------------------
# Deduplication across SAR and Sentinel-2
# ---------------------------------------------------------------------------


def test_deduplicates_same_vessel_across_sensors():
    vessel = _make_vessel("v1", "2026-04", 35.0, 139.0)

    sar_resp = _mock_response([vessel], "public-global-sar-presence:v4.0")
    s2_resp = _mock_response([vessel], "public-global-sentinel2-presence:v4.0")

    with patch("httpx.post") as mock_post:
        mock_post.side_effect = [sar_resp, s2_resp]
        recs = fetch_gfw_detections(bbox=JAPAN, days=30, api_token=TOKEN)

    # Same vessel+date seen by both sensors → only one record
    assert len(recs) == 1
    assert recs[0]["source"] == "gfw-sar"  # SAR fetched first


def test_keeps_different_vessels_from_each_sensor():
    v1 = _make_vessel("v1", "2026-04", 35.0, 139.0)
    v2 = _make_vessel("v2", "2026-04", 36.0, 140.0)

    sar_resp = _mock_response([v1], "public-global-sar-presence:v4.0")
    s2_resp = _mock_response([v2], "public-global-sentinel2-presence:v4.0")

    with patch("httpx.post") as mock_post:
        mock_post.side_effect = [sar_resp, s2_resp]
        recs = fetch_gfw_detections(bbox=JAPAN, days=30, api_token=TOKEN)

    assert len(recs) == 2
    sources = {r["source"] for r in recs}
    assert sources == {"gfw-sar", "gfw-s2"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_raises_when_no_token():
    with pytest.raises(RuntimeError, match="GFW_API_TOKEN not set"):
        fetch_gfw_detections(api_token="", api_tokens=[])


def test_raises_on_auth_error():
    resp = MagicMock()
    resp.status_code = 401
    resp.is_success = False

    with patch("httpx.post", return_value=resp):
        with pytest.raises(PermissionError, match="401"):
            fetch_gfw_detections(bbox=JAPAN, days=30, api_token=TOKEN)


def test_raises_on_server_error():
    resp = MagicMock()
    resp.status_code = 524
    resp.is_success = False
    resp.text = "timeout"

    with patch("httpx.post", return_value=resp):
        with pytest.raises(RuntimeError, match="524"):
            fetch_gfw_detections(bbox=JAPAN, days=30, api_token=TOKEN)
