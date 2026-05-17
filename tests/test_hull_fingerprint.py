"""Unit tests for hull_fingerprint - mocks CLIP and LanceDB to avoid I/O."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import polars as pl
import pytest

from pipelines.features.hull_fingerprint import (
    EMBEDDING_DIM,
    enrich_watchlist_hull,
    query_hull_similarity,
    store_hull_embedding,
    store_hull_images_from_dir,
)

FAKE_VEC = list(np.ones(EMBEDDING_DIM, dtype=np.float32) / np.sqrt(float(EMBEDDING_DIM)))


def _fake_embed(_path: str) -> list[float]:
    return FAKE_VEC


@pytest.fixture()
def tmp_lance(tmp_path: Path) -> str:
    return str(tmp_path / "hull_test.lance")


@pytest.fixture()
def sample_image(tmp_path: Path) -> Path:
    from PIL import Image
    p = tmp_path / "352179000_horae.jpg"
    Image.new("RGB", (1, 1), color=(128, 64, 32)).save(p)
    return p


def test_store_and_query(tmp_lance: str, sample_image: Path) -> None:
    with patch("pipelines.features.hull_fingerprint.embed_image", _fake_embed):
        store_hull_embedding("352179000", "Horae", str(sample_image), tmp_lance, True)
        store_hull_embedding("314189000", "Bangus", str(sample_image), tmp_lance, True)
        results = query_hull_similarity(str(sample_image), top_k=5, lance_path=tmp_lance)

    assert len(results) == 2
    for r in results:
        assert "mmsi" in r
        assert 0.0 <= r["similarity"] <= 1.0
        assert r["is_confirmed_positive"] is True


def test_query_empty_table_returns_empty(tmp_lance: str, sample_image: Path) -> None:
    with patch("pipelines.features.hull_fingerprint.embed_image", _fake_embed):
        results = query_hull_similarity(str(sample_image), lance_path=tmp_lance)
    assert results == []


def test_store_from_dir_indexes_mmsi_prefixed_files(tmp_path: Path, tmp_lance: str) -> None:
    from PIL import Image
    Image.new("RGB", (1, 1)).save(tmp_path / "352179000_horae_01.jpg")
    Image.new("RGB", (1, 1)).save(tmp_path / "314189000_bangus.jpg")
    Image.new("RGB", (1, 1)).save(tmp_path / "not_a_vessel.jpg")

    with patch("pipelines.features.hull_fingerprint.embed_image", _fake_embed):
        n = store_hull_images_from_dir(
            str(tmp_path), lance_path=tmp_lance, confirmed_mmsis={"352179000"},
        )
    assert n == 2


def _make_watchlist() -> pl.DataFrame:
    return pl.DataFrame({
        "mmsi": ["352179000", "314189000", "999999999"],
        "confidence": [0.30, 0.28, 0.05],
    })


def test_enrich_adds_column_with_scores(tmp_lance: str, sample_image: Path) -> None:
    with patch("pipelines.features.hull_fingerprint.embed_image", _fake_embed):
        store_hull_embedding("352179000", "Horae", str(sample_image), tmp_lance, True)
        store_hull_embedding("314189000", "Bangus", str(sample_image), tmp_lance, True)
        df = enrich_watchlist_hull(_make_watchlist(), lance_path=tmp_lance)

    assert "hull_visual_similarity" in df.columns
    sims = df["hull_visual_similarity"].to_list()
    assert sims[0] > 0.5, f"Expected >0.5 for Horae, got {sims[0]}"
    assert sims[1] > 0.5, f"Expected >0.5 for Bangus, got {sims[1]}"
    assert sims[2] == pytest.approx(0.0)


def test_enrich_skip_hull_returns_zeros(tmp_lance: str) -> None:
    df = enrich_watchlist_hull(_make_watchlist(), lance_path=tmp_lance, skip_hull=True)
    assert "hull_visual_similarity" in df.columns
    assert all(v == 0.0 for v in df["hull_visual_similarity"].to_list())


def test_enrich_missing_table_returns_zeros(tmp_lance: str) -> None:
    df = enrich_watchlist_hull(_make_watchlist(), lance_path=tmp_lance)
    assert "hull_visual_similarity" in df.columns
    assert all(v == pytest.approx(0.0) for v in df["hull_visual_similarity"].to_list())
