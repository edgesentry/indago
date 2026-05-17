"""Tests for scripts/hull_embed.py — mocks R2 and CLIP to test differential embed logic."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

import scripts.hull_embed as hull_embed
from pipelines.features.hull_fingerprint import EMBEDDING_DIM

FAKE_VEC = list(np.ones(EMBEDDING_DIM, dtype=np.float32) / np.sqrt(float(EMBEDDING_DIM)))

MANIFEST_ROWS = [
    {"mmsi": "352179000", "vessel_name": "Horae", "is_confirmed_positive": True},
    {"mmsi": "314189000", "vessel_name": "Bangus", "is_confirmed_positive": True},
    {"mmsi": "352001906", "vessel_name": "Anaya", "is_confirmed_positive": False},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest_bytes(rows: list[dict]) -> bytes:
    import io
    table = pa.table({
        "mmsi": pa.array([r["mmsi"] for r in rows]),
        "vessel_name": pa.array([r["vessel_name"] for r in rows]),
        "is_confirmed_positive": pa.array([r["is_confirmed_positive"] for r in rows]),
    })
    buf = io.BytesIO()
    pq.write_table(table, buf)
    return buf.getvalue()


def _fake_fs(manifest_rows: list[dict], image_filenames: dict[str, list[str]]):
    """Build a mock pyarrow S3FileSystem for hull_embed functions."""
    fs = MagicMock()

    # open_input_stream for manifest
    def open_input_stream(path):
        if "manifest.parquet" in path:
            import io
            stream = MagicMock()
            stream.__enter__ = lambda s: s
            stream.__exit__ = MagicMock(return_value=False)
            stream.read = lambda: _make_manifest_bytes(manifest_rows)
            return stream
        # individual image files
        stream = MagicMock()
        stream.__enter__ = lambda s: s
        stream.__exit__ = MagicMock(return_value=False)
        stream.read = lambda: b"\xff\xd8\xff"  # minimal JPEG header
        return stream

    fs.open_input_stream = open_input_stream

    # get_file_info for listing images per MMSI
    def get_file_info(selector):
        prefix = selector.base_dir.rstrip("/")
        mmsi = prefix.split("/")[-1]
        filenames = image_filenames.get(mmsi, [])
        infos = []
        for fn in filenames:
            info = MagicMock()
            info.path = f"{prefix}/{fn}"
            info.type = MagicMock()
            import pyarrow.fs as pafs
            info.type = pafs.FileType.File
            infos.append(info)
        return infos

    fs.get_file_info = get_file_info

    # open_output_stream for zip upload
    out_stream = MagicMock()
    out_stream.__enter__ = lambda s: s
    out_stream.__exit__ = MagicMock(return_value=False)
    out_stream.write = MagicMock()
    fs.open_output_stream = MagicMock(return_value=out_stream)

    return fs


# ---------------------------------------------------------------------------
# _pull_manifest
# ---------------------------------------------------------------------------


def test_pull_manifest_returns_rows():
    fs = _fake_fs(MANIFEST_ROWS, {})
    rows = hull_embed._pull_manifest(fs, "maridb-public")
    assert len(rows) == 3
    assert rows[0]["mmsi"] == "352179000"
    assert rows[0]["is_confirmed_positive"] is True


def test_pull_manifest_returns_empty_on_error():
    fs = MagicMock()
    fs.open_input_stream.side_effect = Exception("not found")
    rows = hull_embed._pull_manifest(fs, "maridb-public")
    assert rows == []


# ---------------------------------------------------------------------------
# _list_r2_images
# ---------------------------------------------------------------------------


def test_list_r2_images_returns_jpg_files():
    images = {"352179000": ["horae_01.jpg", "horae_02.png", "readme.txt"]}
    fs = _fake_fs(MANIFEST_ROWS, images)
    result = hull_embed._list_r2_images(fs, "maridb-public", "352179000")
    # readme.txt should be excluded
    assert set(result) == {"horae_01.jpg", "horae_02.png"}


def test_list_r2_images_empty_on_missing_mmsi():
    fs = _fake_fs(MANIFEST_ROWS, {})
    result = hull_embed._list_r2_images(fs, "maridb-public", "999999999")
    assert result == []


# ---------------------------------------------------------------------------
# _get_embedded_mmsis
# ---------------------------------------------------------------------------


def test_get_embedded_mmsis_returns_set(tmp_path):
    from PIL import Image
    from pipelines.features.hull_fingerprint import store_hull_embedding

    lance_path = str(tmp_path / "hull.lance")
    img = tmp_path / "test.jpg"
    Image.new("RGB", (1, 1)).save(img)

    def fake_embed(_p): return FAKE_VEC

    with patch("pipelines.features.hull_fingerprint.embed_image", fake_embed):
        store_hull_embedding("352179000", "Horae", str(img), lance_path, True)
        store_hull_embedding("314189000", "Bangus", str(img), lance_path, True)

    result = hull_embed._get_embedded_mmsis(lance_path)
    assert result == {"352179000", "314189000"}


def test_get_embedded_mmsis_empty_for_missing_path(tmp_path):
    result = hull_embed._get_embedded_mmsis(str(tmp_path / "nonexistent.lance"))
    assert result == set()


# ---------------------------------------------------------------------------
# run_embed — differential logic
# ---------------------------------------------------------------------------


def test_run_embed_skips_already_embedded(tmp_path):
    """When all MMSIs are already embedded, nothing is written and R2 push is skipped."""
    from PIL import Image
    from pipelines.features.hull_fingerprint import store_hull_embedding

    lance_path = str(tmp_path / "hull.lance")
    img = tmp_path / "test.jpg"
    Image.new("RGB", (1, 1)).save(img)

    def fake_embed(_p): return FAKE_VEC

    # Pre-populate all three MMSIs
    with patch("pipelines.features.hull_fingerprint.embed_image", fake_embed):
        for row in MANIFEST_ROWS:
            store_hull_embedding(row["mmsi"], row["vessel_name"], str(img), lance_path, True)

    images = {r["mmsi"]: ["vessel.jpg"] for r in MANIFEST_ROWS}
    fs = _fake_fs(MANIFEST_ROWS, images)

    with (
        patch("scripts.hull_embed._build_fs", return_value=fs),
        patch("scripts.hull_embed._pull_hull_lance", return_value=False),
        patch("scripts.hull_embed._push_hull_lance") as mock_push,
        patch("os.environ.__setitem__"),
        patch("pipelines.features.hull_fingerprint.DEFAULT_LANCE_PATH", lance_path),
    ):
        import os
        os.environ["HULL_LANCE_PATH"] = lance_path
        rc = hull_embed.run_embed(data_dir=tmp_path, force=False, dry_run=False)

    assert rc == 0
    mock_push.assert_not_called()


def test_run_embed_embeds_new_mmsis(tmp_path):
    """New MMSIs (not in LanceDB) are embedded and R2 push is called."""
    from PIL import Image

    img = tmp_path / "vessel.jpg"
    Image.new("RGB", (1, 1)).save(img)

    images = {r["mmsi"]: ["vessel.jpg"] for r in MANIFEST_ROWS}
    fs = _fake_fs(MANIFEST_ROWS, images)

    lance_path = str(tmp_path / "hull.lance")
    import os
    os.environ["HULL_LANCE_PATH"] = lance_path

    def fake_embed(_p): return FAKE_VEC

    def fake_download(fs, bucket, mmsi, filename, local_dir):
        dest = local_dir / filename
        Image.new("RGB", (1, 1)).save(dest)
        return dest

    with (
        patch("scripts.hull_embed._build_fs", return_value=fs),
        patch("scripts.hull_embed._pull_hull_lance", return_value=False),
        patch("scripts.hull_embed._push_hull_lance", return_value=1024) as mock_push,
        patch("scripts.hull_embed._download_image", side_effect=fake_download),
        patch("pipelines.features.hull_fingerprint.embed_image", fake_embed),
    ):
        rc = hull_embed.run_embed(data_dir=tmp_path, force=False, dry_run=False)

    assert rc == 0
    mock_push.assert_called_once()


def test_run_embed_dry_run_skips_push(tmp_path):
    """--dry-run embeds but does not push to R2."""
    from PIL import Image

    img = tmp_path / "vessel.jpg"
    Image.new("RGB", (1, 1)).save(img)

    single_manifest = [MANIFEST_ROWS[0]]
    images = {"352179000": ["vessel.jpg"]}
    fs = _fake_fs(single_manifest, images)

    lance_path = str(tmp_path / "hull.lance")
    import os
    os.environ["HULL_LANCE_PATH"] = lance_path

    def fake_embed(_p): return FAKE_VEC

    def fake_download(fs, bucket, mmsi, filename, local_dir):
        dest = local_dir / filename
        Image.new("RGB", (1, 1)).save(dest)
        return dest

    with (
        patch("scripts.hull_embed._build_fs", return_value=fs),
        patch("scripts.hull_embed._pull_hull_lance", return_value=False),
        patch("scripts.hull_embed._push_hull_lance") as mock_push,
        patch("scripts.hull_embed._download_image", side_effect=fake_download),
        patch("pipelines.features.hull_fingerprint.embed_image", fake_embed),
    ):
        rc = hull_embed.run_embed(data_dir=tmp_path, force=False, dry_run=True)

    assert rc == 0
    mock_push.assert_not_called()


def test_run_embed_mmsi_filter(tmp_path):
    """--mmsi restricts embedding to specified vessels only."""
    from PIL import Image

    img = tmp_path / "vessel.jpg"
    Image.new("RGB", (1, 1)).save(img)

    images = {r["mmsi"]: ["vessel.jpg"] for r in MANIFEST_ROWS}
    fs = _fake_fs(MANIFEST_ROWS, images)

    lance_path = str(tmp_path / "hull.lance")
    import os
    os.environ["HULL_LANCE_PATH"] = lance_path

    embedded: list[str] = []

    def fake_embed(_p): return FAKE_VEC

    def fake_download(fs, bucket, mmsi, filename, local_dir):
        dest = local_dir / filename
        Image.new("RGB", (1, 1)).save(dest)
        return dest

    original_store = __import__(
        "pipelines.features.hull_fingerprint", fromlist=["store_hull_embedding"]
    ).store_hull_embedding

    def capturing_store(mmsi, **kwargs):
        embedded.append(mmsi)
        original_store(mmsi, **kwargs)

    with (
        patch("scripts.hull_embed._build_fs", return_value=fs),
        patch("scripts.hull_embed._pull_hull_lance", return_value=False),
        patch("scripts.hull_embed._push_hull_lance", return_value=1024),
        patch("scripts.hull_embed._download_image", side_effect=fake_download),
        patch("pipelines.features.hull_fingerprint.embed_image", fake_embed),
        patch("pipelines.features.hull_fingerprint.store_hull_embedding", side_effect=capturing_store),
    ):
        rc = hull_embed.run_embed(
            data_dir=tmp_path,
            force=False,
            dry_run=False,
            mmsi_filter=["352179000"],
        )

    assert rc == 0
    assert embedded == ["352179000"]
