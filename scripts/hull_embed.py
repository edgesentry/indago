"""Hull visual fingerprinting — differential embed and R2 sync.

Pulls ship images from R2, embeds new MMSIs via CLIP, and pushes the
updated hull_embeddings.lance back to R2.

R2 layout
---------
  maridb-public/hull_images/manifest.parquet
      mmsi (str), vessel_name (str), is_confirmed_positive (bool)
  maridb-public/hull_images/<mmsi>/<filename>.jpg|png|webp
  maridb-public/hull_embeddings.lance.zip

Differential logic
------------------
  1. Read manifest.parquet from R2 → target MMSI set
  2. Pull hull_embeddings.lance.zip from R2 (skip if first run)
  3. Read already-embedded MMSIs from LanceDB
  4. new = target - already_embedded   (or all, if --force)
  5. For each new MMSI: download images → CLIP embed → append to LanceDB
  6. Push updated hull_embeddings.lance.zip to R2

Usage
-----
  uv run python scripts/hull_embed.py               # differential
  uv run python scripts/hull_embed.py --force        # re-embed all
  uv run python scripts/hull_embed.py --dry-run      # skip R2 write
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import pyarrow.fs as pafs
from dotenv import load_dotenv

load_dotenv()

_DEFAULT_BUCKET = os.getenv("S3_BUCKET", "maridb-public")
_DEFAULT_ENDPOINT = os.getenv("S3_ENDPOINT", "")
_DEFAULT_DATA_DIR = os.getenv("DATA_DIR", str(Path.home() / ".indago" / "data"))

_MANIFEST_R2_KEY = "hull_images/manifest.parquet"
_HULL_LANCE_ZIP_KEY = "hull_embeddings.lance.zip"
_HULL_LANCE_LOCAL = "hull_embeddings.lance"
_HULL_IMAGES_PREFIX = "hull_images"
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


# ---------------------------------------------------------------------------
# R2 helpers
# ---------------------------------------------------------------------------


def _build_fs(anonymous: bool = False) -> pafs.S3FileSystem:
    endpoint = _DEFAULT_ENDPOINT
    if not endpoint:
        kwargs: dict = {"region": os.getenv("AWS_REGION", "us-east-1")}
        if not anonymous:
            kwargs["access_key"] = os.environ["AWS_ACCESS_KEY_ID"]
            kwargs["secret_key"] = os.environ["AWS_SECRET_ACCESS_KEY"]
        return pafs.S3FileSystem(anonymous=anonymous, **kwargs)

    host = endpoint.split("://", 1)[-1].rstrip("/")
    scheme = "https" if endpoint.startswith("https://") else "http"
    kwargs = {
        "endpoint_override": host,
        "scheme": scheme,
        "region": os.getenv("AWS_REGION", "auto"),
    }
    if not anonymous:
        kwargs["access_key"] = os.environ["AWS_ACCESS_KEY_ID"]
        kwargs["secret_key"] = os.environ["AWS_SECRET_ACCESS_KEY"]
    return pafs.S3FileSystem(anonymous=anonymous, **kwargs)


def _pull_manifest(fs: pafs.S3FileSystem, bucket: str) -> list[dict]:
    """Download manifest.parquet and return list of {mmsi, vessel_name, is_confirmed_positive}."""
    import pyarrow.parquet as pq

    r2_path = f"{bucket}/{_MANIFEST_R2_KEY}"
    try:
        with fs.open_input_stream(r2_path) as f:
            data = f.read()
    except Exception as exc:
        print(f"Warning: could not read manifest from R2 ({exc})")
        return []

    import pyarrow as pa

    table = pq.read_table(pa.BufferReader(data))
    return table.to_pylist()


def _pull_hull_lance(fs: pafs.S3FileSystem, bucket: str, data_dir: Path) -> bool:
    """Download hull_embeddings.lance.zip and extract. Returns True if found."""
    r2_path = f"{bucket}/{_HULL_LANCE_ZIP_KEY}"
    local_zip = data_dir / "hull_embeddings.lance.zip"
    lance_dir = data_dir / _HULL_LANCE_LOCAL

    try:
        with fs.open_input_stream(r2_path) as src:
            with local_zip.open("wb") as dst:
                while chunk := src.read(4 * 1024 * 1024):
                    dst.write(chunk)
    except Exception:
        return False

    if lance_dir.exists():
        import shutil
        shutil.rmtree(lance_dir)
    with zipfile.ZipFile(local_zip, "r") as zf:
        zf.extractall(data_dir / _HULL_LANCE_LOCAL)
    local_zip.unlink(missing_ok=True)
    return True


def _push_hull_lance(fs: pafs.S3FileSystem, bucket: str, data_dir: Path) -> int:
    """Zip hull_embeddings.lance and upload to R2. Returns bytes uploaded."""
    lance_dir = data_dir / _HULL_LANCE_LOCAL
    r2_path = f"{bucket}/{_HULL_LANCE_ZIP_KEY}"
    local_zip = data_dir / "hull_embeddings.lance.zip"

    with zipfile.ZipFile(local_zip, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        for p in sorted(lance_dir.rglob("*")):
            if p.is_file():
                zf.write(p, arcname=str(p.relative_to(lance_dir)))

    size = local_zip.stat().st_size
    with local_zip.open("rb") as src:
        with fs.open_output_stream(r2_path) as dst:
            while chunk := src.read(4 * 1024 * 1024):
                dst.write(chunk)
    local_zip.unlink(missing_ok=True)
    return size


def _list_r2_images(fs: pafs.S3FileSystem, bucket: str, mmsi: str) -> list[str]:
    """List image filenames in R2 hull_images/<mmsi>/."""
    prefix = f"{bucket}/{_HULL_IMAGES_PREFIX}/{mmsi}/"
    try:
        sel = pafs.FileSelector(prefix, recursive=False)
        infos = fs.get_file_info(sel)
        return [
            Path(i.path).name
            for i in infos
            if i.type == pafs.FileType.File
            and Path(i.path).suffix.lower() in _IMAGE_EXTS
        ]
    except Exception:
        return []


def _download_image(
    fs: pafs.S3FileSystem, bucket: str, mmsi: str, filename: str, local_dir: Path
) -> Path:
    r2_path = f"{bucket}/{_HULL_IMAGES_PREFIX}/{mmsi}/{filename}"
    dest = local_dir / filename
    with fs.open_input_stream(r2_path) as src:
        dest.write_bytes(src.read())
    return dest


# ---------------------------------------------------------------------------
# Main embed logic
# ---------------------------------------------------------------------------


def _get_embedded_mmsis(lance_path: str) -> set[str]:
    try:
        import lancedb
        db = lancedb.connect(lance_path)
        tables = db.list_tables()
        table_names = tables.tables if hasattr(tables, "tables") else list(tables)
        if "hull_embeddings" not in table_names:
            return set()
        rows = db.open_table("hull_embeddings").to_pandas()
        return set(rows["mmsi"].tolist())
    except Exception:
        return set()


def run_embed(
    data_dir: Path,
    force: bool = False,
    dry_run: bool = False,
    mmsi_filter: list[str] | None = None,
) -> int:
    from pipelines.features.hull_fingerprint import (
        DEFAULT_LANCE_PATH,
        store_hull_embedding,
    )

    bucket = _DEFAULT_BUCKET
    fs = _build_fs()
    lance_path = str(data_dir / _HULL_LANCE_LOCAL)

    print("Step 1: Read manifest from R2 ...")
    manifest = _pull_manifest(fs, bucket)
    if not manifest:
        print("No manifest found. Upload hull_images/manifest.parquet to R2 first.")
        return 1
    print(f"  {len(manifest)} vessel(s) in manifest")

    if mmsi_filter:
        manifest = [r for r in manifest if r["mmsi"] in mmsi_filter]
        print(f"  filtered to {len(manifest)} vessel(s) by --mmsi")

    print("\nStep 2: Pull existing hull_embeddings.lance from R2 ...")
    found = _pull_hull_lance(fs, bucket, data_dir)
    print(f"  {'found and extracted' if found else 'not found — first run'}")

    os.environ["HULL_LANCE_PATH"] = lance_path

    already_embedded = set() if force else _get_embedded_mmsis(lance_path)
    print(f"\nStep 3: Differential check — {len(already_embedded)} already embedded")

    to_embed = [r for r in manifest if r["mmsi"] not in already_embedded]
    if not to_embed:
        print("  Nothing new to embed. Use --force to re-embed all.")
        return 0
    print(f"  {len(to_embed)} new MMSI(s) to embed: {[r['mmsi'] for r in to_embed]}")

    print("\nStep 4: Download images and embed ...")
    embedded = 0
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for row in to_embed:
            mmsi = row["mmsi"]
            vessel_name = row.get("vessel_name", mmsi)
            is_pos = bool(row.get("is_confirmed_positive", False))

            images = _list_r2_images(fs, bucket, mmsi)
            if not images:
                print(f"  skip {mmsi} ({vessel_name}) — no images in R2")
                continue

            mmsi_dir = tmp_path / mmsi
            mmsi_dir.mkdir()
            for filename in images:
                _download_image(fs, bucket, mmsi, filename, mmsi_dir)

            for img_file in sorted(mmsi_dir.iterdir()):
                try:
                    store_hull_embedding(
                        mmsi=mmsi,
                        vessel_name=vessel_name,
                        image_path=str(img_file),
                        lance_path=lance_path,
                        is_confirmed_positive=is_pos,
                    )
                    print(f"  ok {mmsi} {vessel_name} <- {img_file.name}")
                    embedded += 1
                except Exception as exc:
                    print(f"  fail {mmsi} {img_file.name}: {exc}")

    if embedded == 0:
        print("\nNo embeddings written.")
        return 0

    print(f"\nStep 5: {embedded} embedding(s) written to {lance_path}")

    if dry_run:
        print("  --dry-run: skipping R2 push")
        return 0

    print("\nStep 6: Push hull_embeddings.lance to R2 ...")
    size = _push_hull_lance(fs, bucket, data_dir)
    print(f"  uploaded {size / 1_048_576:.1f} MB -> {bucket}/{_HULL_LANCE_ZIP_KEY}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Hull visual fingerprinting — differential embed")
    parser.add_argument(
        "--data-dir", default=_DEFAULT_DATA_DIR, metavar="DIR",
        help="Local data directory (default: ~/.indago/data)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-embed all MMSIs, not just new ones",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Download and embed but skip R2 push",
    )
    parser.add_argument(
        "--mmsi", nargs="+", metavar="MMSI",
        help="Only embed these specific MMSIs (space-separated)",
    )
    args = parser.parse_args()
    return run_embed(
        data_dir=Path(args.data_dir),
        force=args.force,
        dry_run=args.dry_run,
        mmsi_filter=args.mmsi,
    )


if __name__ == "__main__":
    sys.exit(main())
