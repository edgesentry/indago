"""
Hull visual fingerprinting — CLIP-based vessel image embeddings.

Embeds ship hull images using OpenCLIP ViT-B/32 and stores them in a
LanceDB table (hull_embeddings.lance).  Supports three operations:

store   Index a directory of MMSI-labelled images into LanceDB.
query   Find watchlist vessels visually similar to a query image.
enrich  Add hull_visual_similarity column to a composite-score DataFrame.

hull_visual_similarity is defined as: for each MMSI in the watchlist,
the maximum cosine similarity between its stored embedding(s) and any
embedding tagged is_confirmed_positive=True.  Zero when no image is
available — the column is additive / informational and does not change
the existing confidence formula.

Usage:
    # Index images: expects <dir>/<mmsi>_*.jpg  (e.g. 352179000_01.jpg)
    uv run python -m pipelines.features.hull_fingerprint \\
        store --image-dir data/hull_images

    # Query: find top-5 watchlist vessels visually similar to a photo
    uv run python -m pipelines.features.hull_fingerprint \\
        query --image path/to/unknown_vessel.jpg --top-k 5
"""

from __future__ import annotations

import argparse
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import polars as pl
from dotenv import load_dotenv

from pipelines.storage.config import lance_storage_options

if TYPE_CHECKING:
    import lancedb  # noqa: F401

load_dotenv()

HULL_TABLE = "hull_embeddings"
CLIP_MODEL = "ViT-B-32"
CLIP_PRETRAINED = "openai"
EMBEDDING_DIM = 512

_DEFAULT_LANCE_DIR = os.path.join(
    os.getenv("DATA_DIR", str(Path.home() / ".indago" / "data")),
    "hull_embeddings.lance",
)
DEFAULT_LANCE_PATH = os.getenv("HULL_LANCE_PATH", _DEFAULT_LANCE_DIR)

_IMAGE_MMSI_RE = re.compile(r"^(\d{9})")


# ---------------------------------------------------------------------------
# CLIP model (lazy singleton — avoids 600 MB download unless images used)
# ---------------------------------------------------------------------------

_model = None
_preprocess = None


def _load_clip():
    global _model, _preprocess
    if _model is None:
        import open_clip  # type: ignore[import]
        import torch

        _model, _, _preprocess = open_clip.create_model_and_transforms(
            CLIP_MODEL, pretrained=CLIP_PRETRAINED
        )
        _model.eval()
        if torch.cuda.is_available():
            _model = _model.cuda()
    return _model, _preprocess


# ---------------------------------------------------------------------------
# Core embedding
# ---------------------------------------------------------------------------


def embed_image(image_path: str) -> list[float]:
    """Return a 512-dim CLIP embedding for one image file."""
    import torch
    from PIL import Image

    model, preprocess = _load_clip()
    img = Image.open(image_path).convert("RGB")
    tensor = preprocess(img).unsqueeze(0)
    if torch.cuda.is_available():
        tensor = tensor.cuda()
    with torch.no_grad():
        features = model.encode_image(tensor)
        features = features / features.norm(dim=-1, keepdim=True)
    return features.squeeze().cpu().tolist()


# ---------------------------------------------------------------------------
# LanceDB helpers
# ---------------------------------------------------------------------------


def _connect(lance_path: str):
    import lancedb  # type: ignore[import]

    opts = lance_storage_options()
    if opts:
        return lancedb.connect(lance_path, storage_options=opts)
    return lancedb.connect(lance_path)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def store_hull_embedding(
    mmsi: str,
    vessel_name: str,
    image_path: str,
    lance_path: str = DEFAULT_LANCE_PATH,
    is_confirmed_positive: bool = False,
) -> None:
    """Embed one image and append into the hull_embeddings table."""
    import pyarrow as pa

    vec = embed_image(image_path)
    now = datetime.now(UTC)

    row = pa.table(
        {
            "mmsi": [mmsi],
            "vessel_name": [vessel_name],
            "image_source": [str(image_path)],
            "is_confirmed_positive": [is_confirmed_positive],
            "embedding": pa.array([vec], type=pa.list_(pa.float32(), EMBEDDING_DIM)),
            "ingested_at": pa.array([now], type=pa.timestamp("ms", tz="UTC")),
        }
    )

    db = _connect(lance_path)
    try:
        db.create_table(HULL_TABLE, row)
    except Exception:
        db.open_table(HULL_TABLE).add(row)


def store_hull_images_from_dir(
    image_dir: str,
    lance_path: str = DEFAULT_LANCE_PATH,
    confirmed_mmsis: set[str] | None = None,
) -> int:
    """Bulk-index all images in a directory.

    Filename convention: <9-digit-mmsi>[_anything].<ext>
    e.g.  352179000_horae_01.jpg   ->  MMSI 352179000

    Returns the number of images indexed.
    """
    p = Path(image_dir)
    indexed = 0
    for f in sorted(p.iterdir()):
        if f.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        m = _IMAGE_MMSI_RE.match(f.name)
        if not m:
            print(f"  skip {f.name} - no 9-digit MMSI prefix")
            continue
        mmsi = m.group(1)
        is_pos = confirmed_mmsis is not None and mmsi in confirmed_mmsis
        try:
            store_hull_embedding(mmsi, f.stem, str(f), lance_path, is_pos)
            indexed += 1
            print(f"  tick {f.name}  mmsi={mmsi}  confirmed_positive={is_pos}")
        except Exception as e:
            print(f"  fail {f.name}  {e}")
    return indexed


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


def query_hull_similarity(
    image_path: str,
    top_k: int = 5,
    lance_path: str = DEFAULT_LANCE_PATH,
) -> list[dict]:
    """Return top-k watchlist vessels most visually similar to the query image.

    Each result dict has: mmsi, vessel_name, similarity, image_source,
    is_confirmed_positive.
    """
    vec = embed_image(image_path)
    db = _connect(lance_path)
    if HULL_TABLE not in (db.list_tables().tables or []):
        return []

    tbl = db.open_table(HULL_TABLE)
    results = (
        tbl.search(vec, vector_column_name="embedding")
        .metric("cosine")
        .limit(top_k)
        .to_list()
    )

    return [
        {
            "mmsi": r["mmsi"],
            "vessel_name": r["vessel_name"],
            "similarity": round(1.0 - r.get("_distance", 1.0), 4),
            "image_source": r.get("image_source", ""),
            "is_confirmed_positive": r.get("is_confirmed_positive", False),
        }
        for r in results
    ]


# ---------------------------------------------------------------------------
# Watchlist enrichment
# ---------------------------------------------------------------------------


def enrich_watchlist_hull(
    df: pl.DataFrame,
    lance_path: str = DEFAULT_LANCE_PATH,
    skip_hull: bool = False,
) -> pl.DataFrame:
    """Add hull_visual_similarity column to a composite-score DataFrame.

    For each MMSI that has a hull embedding, the score is the maximum cosine
    similarity between that vessel's embedding and any confirmed-positive
    vessel's embedding in the table.  Zero when no image is available.
    """
    null_col = pl.lit(0.0, dtype=pl.Float32).alias("hull_visual_similarity")

    if skip_hull:
        return df.with_columns(null_col)

    try:
        db = _connect(lance_path)
        if HULL_TABLE not in (db.list_tables().tables or []):
            return df.with_columns(null_col)

        tbl = db.open_table(HULL_TABLE)
        rows = tbl.to_pandas()
        if rows.empty:
            return df.with_columns(null_col)

        confirmed = rows[rows["is_confirmed_positive"]]["embedding"].tolist()
        if not confirmed:
            return df.with_columns(null_col)

        confirmed_mat = np.array(confirmed, dtype=np.float32)
        confirmed_mat /= np.linalg.norm(confirmed_mat, axis=1, keepdims=True) + 1e-9

        mmsi_to_sim: dict[str, float] = {}
        for _, row in rows.iterrows():
            vec = np.array(row["embedding"], dtype=np.float32)
            norm = np.linalg.norm(vec)
            if norm < 1e-9:
                continue
            vec /= norm
            sims = confirmed_mat @ vec
            mmsi_to_sim[row["mmsi"]] = float(max(mmsi_to_sim.get(row["mmsi"], 0.0), sims.max()))

        mmsi_list = df["mmsi"].to_list()
        scores = [float(mmsi_to_sim.get(m, 0.0)) for m in mmsi_list]
        return df.with_columns(
            pl.Series("hull_visual_similarity", scores, dtype=pl.Float32)
        )

    except Exception as exc:
        print(f"Warning: hull fingerprint enrichment skipped ({exc})")
        return df.with_columns(null_col)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Hull visual fingerprinting")
    sub = parser.add_subparsers(dest="cmd")

    p_store = sub.add_parser("store", help="Index hull images from a directory")
    p_store.add_argument("--image-dir", required=True)
    p_store.add_argument("--lance-path", default=DEFAULT_LANCE_PATH)
    p_store.add_argument(
        "--confirmed-mmsis",
        help="Comma-separated MMSIs to tag as confirmed positives",
        default="",
    )

    p_query = sub.add_parser("query", help="Find vessels similar to a query image")
    p_query.add_argument("--image", required=True)
    p_query.add_argument("--top-k", type=int, default=5)
    p_query.add_argument("--lance-path", default=DEFAULT_LANCE_PATH)

    args = parser.parse_args()

    if args.cmd == "store":
        confirmed = set(args.confirmed_mmsis.split(",")) if args.confirmed_mmsis else None
        n = store_hull_images_from_dir(args.image_dir, args.lance_path, confirmed)
        print(f"Indexed {n} image(s) -> {args.lance_path}")

    elif args.cmd == "query":
        results = query_hull_similarity(args.image, args.top_k, args.lance_path)
        if not results:
            print("No embeddings found in hull_embeddings table.")
            return
        print(f"\nTop-{args.top_k} visual matches for {args.image}:\n")
        for i, r in enumerate(results, 1):
            pos = " (confirmed positive)" if r["is_confirmed_positive"] else ""
            print(f"  {i}. MMSI {r['mmsi']:>12}  similarity={r['similarity']:.4f}  "
                  f"{r['vessel_name']}{pos}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
