"""Tests for sync_r2.py push-arktrace and ownership_chain column validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pyarrow.parquet as pq

import scripts.sync_r2 as sync_r2


def _write_watchlist_parquet(path: Path, *, with_ownership_chain: bool) -> None:
    schema = pa.schema(
        [
            pa.field("mmsi", pa.string()),
            pa.field("confidence", pa.float64()),
        ]
        + ([pa.field("ownership_chain", pa.string())] if with_ownership_chain else [])
    )
    table = pa.table(
        {
            "mmsi": ["111111111"],
            "confidence": [0.5],
            **(
                {"ownership_chain": [json.dumps([{"hop": 0, "kind": "vessel", "sanctioned": False}])]}
                if with_ownership_chain
                else {}
            ),
        },
        schema=schema,
    )
    pq.write_table(table, path)


def test_watchlists_missing_ownership_chain_detects_absent_column(tmp_path):
    good = tmp_path / "singapore_watchlist.parquet"
    bad = tmp_path / "candidate_watchlist.parquet"
    _write_watchlist_parquet(good, with_ownership_chain=True)
    _write_watchlist_parquet(bad, with_ownership_chain=False)

    missing = sync_r2._watchlists_missing_ownership_chain([good, bad])
    assert missing == ["candidate_watchlist.parquet"]


def test_watchlists_missing_ownership_chain_empty_when_present(tmp_path):
    path = tmp_path / "singapore_watchlist.parquet"
    _write_watchlist_parquet(path, with_ownership_chain=True)
    assert sync_r2._watchlists_missing_ownership_chain([path]) == []


def test_push_arktrace_warns_when_ownership_chain_missing(tmp_path, capsys):
    _write_watchlist_parquet(
        tmp_path / "singapore_watchlist.parquet",
        with_ownership_chain=False,
    )

    args = argparse.Namespace(data_dir=str(tmp_path))
    mock_fs = MagicMock()

    with patch.object(sync_r2, "_build_r2_fs", return_value=mock_fs):
        with patch.object(sync_r2, "_upload_file"):
            result = sync_r2.cmd_push_arktrace(args)

    assert result == 0
    err = capsys.readouterr().err
    assert "missing ownership_chain" in err
    assert "singapore_watchlist.parquet" in err


def test_resolve_watchlist_paths_prefers_score_subdir(tmp_path):
    score_dir = tmp_path / "score"
    score_dir.mkdir()
    _write_watchlist_parquet(tmp_path / "singapore_watchlist.parquet", with_ownership_chain=False)
    _write_watchlist_parquet(score_dir / "singapore_watchlist.parquet", with_ownership_chain=True)
    _write_watchlist_parquet(tmp_path / "candidate_watchlist.parquet", with_ownership_chain=True)

    resolved = sync_r2._resolve_watchlist_paths_for_push(tmp_path)
    by_name = {p.name: p for p in resolved}

    assert by_name["singapore_watchlist.parquet"] == score_dir / "singapore_watchlist.parquet"
    assert by_name["candidate_watchlist.parquet"] == tmp_path / "candidate_watchlist.parquet"


def test_push_arktrace_uploads_score_watchlist_when_stale_root_exists(tmp_path, capsys):
    score_dir = tmp_path / "score"
    score_dir.mkdir()
    _write_watchlist_parquet(tmp_path / "singapore_watchlist.parquet", with_ownership_chain=False)
    _write_watchlist_parquet(score_dir / "singapore_watchlist.parquet", with_ownership_chain=True)

    args = argparse.Namespace(data_dir=str(tmp_path))
    uploaded: list[Path] = []

    def capture_upload(_fs, local_path: Path, _r2_path: str) -> int:
        uploaded.append(local_path)
        return local_path.stat().st_size

    with patch.object(sync_r2, "_build_r2_fs", return_value=MagicMock()):
        with patch.object(sync_r2, "_upload_file", side_effect=capture_upload):
            result = sync_r2.cmd_push_arktrace(args)

    assert result == 0
    assert score_dir / "singapore_watchlist.parquet" in uploaded
    assert tmp_path / "singapore_watchlist.parquet" not in uploaded
    assert "missing ownership_chain" not in capsys.readouterr().err


def test_push_arktrace_no_warn_when_ownership_chain_present(tmp_path, capsys):
    _write_watchlist_parquet(
        tmp_path / "singapore_watchlist.parquet",
        with_ownership_chain=True,
    )

    args = argparse.Namespace(data_dir=str(tmp_path))

    with patch.object(sync_r2, "_build_r2_fs", return_value=MagicMock()):
        with patch.object(sync_r2, "_upload_file"):
            result = sync_r2.cmd_push_arktrace(args)

    assert result == 0
    assert "missing ownership_chain" not in capsys.readouterr().err
