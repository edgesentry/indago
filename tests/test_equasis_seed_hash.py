"""Tests for the seed content-hash cache invalidation in _ensure_equasis_ownership_csv."""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
from unittest.mock import patch

import pytest

import scripts.run_pipeline as rp


def _write_seed(path: Path, content: str = "mmsi,manager_name\n312171000,Harry Victor\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _seed_hash(seed_path: Path) -> str:
    return hashlib.sha256(seed_path.read_bytes()).hexdigest()


def _patch_paths(monkeypatch, tmp_path: Path):
    csv_path = tmp_path / "equasis" / "ownership_chains.csv"
    seed_path = tmp_path / "seed" / "ownership_seed.csv"
    hash_path = tmp_path / "equasis" / "ownership_chains.seed_hash"
    monkeypatch.setattr(rp, "_EQUASIS_CSV", csv_path)
    monkeypatch.setattr(rp, "_EQUASIS_SEED", seed_path)
    monkeypatch.setattr(rp, "_EQUASIS_SEED_HASH", hash_path)
    return csv_path, seed_path, hash_path


def test_cache_hit_returns_existing_csv(monkeypatch, tmp_path):
    """CSV exists and hash matches → return without rebuilding."""
    csv_path, seed_path, hash_path = _patch_paths(monkeypatch, tmp_path)
    _write_seed(seed_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text("mmsi,manager_id\n312171000,co-harry\n")
    hash_path.write_text(_seed_hash(seed_path))

    with patch("pipelines.ingest.equasis_ownership.build_ownership_csv") as mock_build:
        result = rp._ensure_equasis_ownership_csv("unused.duckdb")

    assert result == csv_path
    mock_build.assert_not_called()


def test_stale_cache_no_hash_file_triggers_rebuild(monkeypatch, tmp_path, tmp_db):
    """CSV exists but no hash file → rebuild (e.g. after pulling old CSV from R2)."""
    csv_path, seed_path, hash_path = _patch_paths(monkeypatch, tmp_path)
    _write_seed(seed_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text("mmsi,manager_id\n312171000,stale\n")
    # hash_path intentionally absent

    with patch("pipelines.ingest.equasis_ownership.build_ownership_csv", return_value=1) as mock_build:
        result = rp._ensure_equasis_ownership_csv(tmp_db)

    mock_build.assert_called_once()
    assert result == csv_path


def test_seed_changed_triggers_rebuild(monkeypatch, tmp_path, tmp_db):
    """CSV exists, hash file present but mismatches current seed → rebuild."""
    csv_path, seed_path, hash_path = _patch_paths(monkeypatch, tmp_path)
    _write_seed(seed_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text("mmsi,manager_id\n312171000,old\n")
    hash_path.write_text("0" * 64)  # wrong hash

    with patch("pipelines.ingest.equasis_ownership.build_ownership_csv", return_value=1) as mock_build:
        result = rp._ensure_equasis_ownership_csv(tmp_db)

    mock_build.assert_called_once()
    assert result == csv_path


def test_successful_build_writes_hash_file(monkeypatch, tmp_path, tmp_db):
    """After a successful build, the seed hash is persisted alongside the CSV."""
    csv_path, seed_path, hash_path = _patch_paths(monkeypatch, tmp_path)
    _write_seed(seed_path)
    # No CSV yet — forces build path

    def fake_build(*args, **kwargs):
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_text("mmsi,manager_id\n312171000,co-harry\n")
        return 1

    with patch("pipelines.ingest.equasis_ownership.build_ownership_csv", side_effect=fake_build):
        rp._ensure_equasis_ownership_csv(tmp_db)

    assert hash_path.is_file()
    assert hash_path.read_text().strip() == _seed_hash(seed_path)


def test_no_seed_returns_none(monkeypatch, tmp_path, tmp_db):
    """No seed file and no CSV → return None (skip ownership edges)."""
    csv_path, seed_path, hash_path = _patch_paths(monkeypatch, tmp_path)
    # Neither CSV nor seed exists

    result = rp._ensure_equasis_ownership_csv(tmp_db)

    assert result is None


def test_build_failure_returns_none(monkeypatch, tmp_path, tmp_db):
    """build_ownership_csv raises → return None gracefully."""
    csv_path, seed_path, hash_path = _patch_paths(monkeypatch, tmp_path)
    _write_seed(seed_path)

    with patch(
        "pipelines.ingest.equasis_ownership.build_ownership_csv",
        side_effect=RuntimeError("DB error"),
    ):
        result = rp._ensure_equasis_ownership_csv(tmp_db)

    assert result is None
    assert not hash_path.exists()


def test_build_zero_rows_returns_none(monkeypatch, tmp_path, tmp_db):
    """build_ownership_csv returns 0 rows → return None, no hash written."""
    csv_path, seed_path, hash_path = _patch_paths(monkeypatch, tmp_path)
    _write_seed(seed_path)

    with patch("pipelines.ingest.equasis_ownership.build_ownership_csv", return_value=0):
        result = rp._ensure_equasis_ownership_csv(tmp_db)

    assert result is None
    assert not hash_path.exists()


def test_env_override_bypasses_hash_logic(monkeypatch, tmp_path):
    """EQUASIS_OWNERSHIP_CSV env var always wins — hash logic not consulted."""
    csv_path, seed_path, hash_path = _patch_paths(monkeypatch, tmp_path)
    override = tmp_path / "override.csv"
    override.write_text("mmsi,manager_id\n")
    monkeypatch.setenv("EQUASIS_OWNERSHIP_CSV", str(override))

    with patch("pipelines.ingest.equasis_ownership.build_ownership_csv") as mock_build:
        result = rp._ensure_equasis_ownership_csv("unused.duckdb")

    assert result == override
    mock_build.assert_not_called()
    monkeypatch.delenv("EQUASIS_OWNERSHIP_CSV")
