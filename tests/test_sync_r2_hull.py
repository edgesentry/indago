"""Tests for sync_r2.py push-hull / pull-hull commands."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import scripts.sync_r2 as sync_r2


def _make_lance_dir(data_dir: Path) -> Path:
    """Create a minimal hull_embeddings.lance directory with fake files."""
    lance_dir = data_dir / "hull_embeddings.lance"
    lance_dir.mkdir()
    (lance_dir / "_versions").mkdir()
    (lance_dir / "_versions" / "1.manifest").write_bytes(b"fake-manifest")
    (lance_dir / "data").mkdir()
    (lance_dir / "data" / "0.lance").write_bytes(b"fake-lance-data" * 100)
    return lance_dir


# ---------------------------------------------------------------------------
# push-hull
# ---------------------------------------------------------------------------


class TestPushHull:
    def test_returns_1_when_lance_dir_missing(self, tmp_path):
        args = argparse.Namespace(data_dir=str(tmp_path))
        result = sync_r2.cmd_push_hull(args)
        assert result == 1

    def test_uploads_zip_and_returns_0(self, tmp_path):
        _make_lance_dir(tmp_path)

        uploaded: list[tuple[Path, str]] = []

        def capture_upload(_fs, local_path: Path, r2_path: str) -> int:
            # Verify it is a valid zip
            assert zipfile.is_zipfile(local_path)
            with zipfile.ZipFile(local_path) as zf:
                names = zf.namelist()
            assert any("0.lance" in n for n in names)
            uploaded.append((local_path, r2_path))
            return local_path.stat().st_size

        args = argparse.Namespace(data_dir=str(tmp_path))

        with (
            patch.object(sync_r2, "_build_r2_fs", return_value=MagicMock()),
            patch.object(sync_r2, "_upload_file", side_effect=capture_upload),
        ):
            result = sync_r2.cmd_push_hull(args)

        assert result == 0
        assert len(uploaded) == 1
        _, r2_path = uploaded[0]
        assert r2_path.endswith("hull_embeddings.lance.zip")

    def test_zip_contains_all_lance_files(self, tmp_path):
        lance_dir = _make_lance_dir(tmp_path)
        # Add a second data file
        (lance_dir / "data" / "1.lance").write_bytes(b"more-data")

        captured_names: list[str] = []

        def capture_upload(_fs, local_path: Path, r2_path: str) -> int:
            with zipfile.ZipFile(local_path) as zf:
                captured_names.extend(zf.namelist())
            return 0

        args = argparse.Namespace(data_dir=str(tmp_path))

        with (
            patch.object(sync_r2, "_build_r2_fs", return_value=MagicMock()),
            patch.object(sync_r2, "_upload_file", side_effect=capture_upload),
        ):
            sync_r2.cmd_push_hull(args)

        assert any("0.lance" in n for n in captured_names)
        assert any("1.lance" in n for n in captured_names)
        assert any("manifest" in n for n in captured_names)


# ---------------------------------------------------------------------------
# pull-hull
# ---------------------------------------------------------------------------


def _make_zip_bytes(files: dict[str, bytes]) -> bytes:
    """Create an in-memory zip with the given {relative_path: content} mapping."""
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


class TestPullHull:
    def _make_fs(self, zip_bytes: bytes) -> MagicMock:
        fs = MagicMock()
        stream = MagicMock()
        stream.__enter__ = lambda s: s
        stream.__exit__ = MagicMock(return_value=False)
        # Yield zip bytes in one chunk, then empty to end loop
        stream.read = MagicMock(side_effect=[zip_bytes, b""])
        fs.open_input_stream.return_value = stream
        return fs

    def test_extracts_lance_files(self, tmp_path):
        zip_bytes = _make_zip_bytes({
            "data/0.lance": b"lance-data",
            "_versions/1.manifest": b"manifest",
        })
        fs = self._make_fs(zip_bytes)
        args = argparse.Namespace(data_dir=str(tmp_path))

        with patch.object(sync_r2, "_build_r2_fs", return_value=fs):
            result = sync_r2.cmd_pull_hull(args)

        assert result == 0
        lance_dir = tmp_path / "hull_embeddings.lance"
        assert (lance_dir / "data" / "0.lance").exists()
        assert (lance_dir / "_versions" / "1.manifest").exists()

    def test_overwrites_existing_lance_dir(self, tmp_path):
        # Pre-existing stale directory
        old_dir = tmp_path / "hull_embeddings.lance"
        old_dir.mkdir()
        (old_dir / "stale.lance").write_bytes(b"old")

        zip_bytes = _make_zip_bytes({"data/fresh.lance": b"new-data"})
        fs = self._make_fs(zip_bytes)
        args = argparse.Namespace(data_dir=str(tmp_path))

        with patch.object(sync_r2, "_build_r2_fs", return_value=fs):
            result = sync_r2.cmd_pull_hull(args)

        assert result == 0
        assert not (old_dir / "stale.lance").exists()
        assert (old_dir / "data" / "fresh.lance").exists()

    def test_returns_1_on_r2_error(self, tmp_path, capsys):
        fs = MagicMock()
        fs.open_input_stream.side_effect = Exception("R2 unavailable")
        args = argparse.Namespace(data_dir=str(tmp_path))

        with patch.object(sync_r2, "_build_r2_fs", return_value=fs):
            result = sync_r2.cmd_pull_hull(args)

        assert result == 1
