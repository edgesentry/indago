#!/usr/bin/env python3
"""Inspect regional watchlists on R2 or local data/processed.

Fetches the latest arktrace-public score/*_watchlist.parquet files (no credentials),
or reads local paths after ``sync_r2.py pull-watchlists``.

Usage (from indago repo root)
-----
    uv run python .agents/skills/indago-inspect-watchlist/inspect_watchlist.py
    uv run python .agents/skills/indago-inspect-watchlist/inspect_watchlist.py --pull
    uv run python .agents/skills/indago-inspect-watchlist/inspect_watchlist.py \\
        --sanctions-distance 1 2 --min-chain-hops 2
    uv run python .agents/skills/indago-inspect-watchlist/inspect_watchlist.py --mmsi 352001906
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import polars as pl

_SKILL_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SKILL_DIR.parents[2]

_ARKTRACE_PUBLIC_BASE = "https://arktrace-public.edgesentry.io"
_DEFAULT_REGIONS = ("singapore", "japansea", "europe", "blacksea", "middleeast")
_SYNC_R2 = _REPO_ROOT / "scripts" / "sync_r2.py"


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "indago-inspect-watchlist/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "indago-inspect-watchlist/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        dest.write_bytes(resp.read())


def chain_hops(raw: str | None) -> int:
    if not raw:
        return 0
    try:
        parsed = json.loads(raw)
        return len(parsed) if isinstance(parsed, list) else 0
    except json.JSONDecodeError:
        return 0


def _find_local_watchlists(data_dir: Path) -> list[Path]:
    score_dir = data_dir / "score"
    roots = [score_dir, data_dir] if score_dir.is_dir() else [data_dir]
    by_name: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.glob("*_watchlist.parquet"):
            existing = by_name.get(path.name)
            if existing is None or "score" in path.parts:
                by_name[path.name] = path
    return sorted(by_name.values())


def _fetch_arktrace_watchlists(
    cache_dir: Path | None,
    regions: tuple[str, ...],
) -> list[tuple[str, Path]]:
    """Return (region_tag, local_path) for each regional watchlist."""
    manifest_url = f"{_ARKTRACE_PUBLIC_BASE}/ducklake_manifest.json"
    try:
        manifest = _get_json(manifest_url)
    except urllib.error.URLError as exc:
        raise SystemExit(f"Failed to fetch manifest: {exc}") from exc

    files = manifest.get("files", [])
    wl_entries = [
        f
        for f in files
        if f.get("register_as") == "watchlist.parquet" and f.get("region") in regions
    ]
    if not wl_entries:
        raise SystemExit("No regional watchlist entries in ducklake_manifest.json")

    out: list[tuple[str, Path]] = []
    tmp_root = cache_dir or Path(tempfile.mkdtemp(prefix="inspect-wl-"))
    tmp_root.mkdir(parents=True, exist_ok=True)

    for entry in sorted(wl_entries, key=lambda e: e.get("region", "")):
        region = entry["region"]
        url = entry.get("url") or f"{_ARKTRACE_PUBLIC_BASE}/{entry['key']}"
        dest = tmp_root / f"{region}_watchlist.parquet"
        if not dest.exists() or dest.stat().st_size != entry.get("size_bytes", -1):
            print(f"Downloading {region} ({entry.get('size_bytes', 0) / 1024:.1f} KB) ...", file=sys.stderr)
            try:
                _download(url, dest)
            except urllib.error.URLError as exc:
                print(f"[warn] skip {region}: {exc}", file=sys.stderr)
                continue
        out.append((region, dest))
    return out


def _load_frames(paths: list[tuple[str, Path]]) -> pl.DataFrame:
    frames: list[pl.DataFrame] = []
    for region, path in paths:
        df = pl.read_parquet(path)
        if "region" not in df.columns:
            df = df.with_columns(pl.lit(region).alias("region"))
        frames.append(df.with_columns(pl.lit(region).alias("_source_region")))
    if not frames:
        raise SystemExit("No watchlist parquet files loaded")
    return pl.concat(frames, how="diagonal_relaxed")


def _enrich(df: pl.DataFrame) -> pl.DataFrame:
    has_chain = "ownership_chain" in df.columns
    has_dist = "sanctions_distance" in df.columns
    out = df
    if has_chain:
        out = out.with_columns(
            pl.col("ownership_chain")
            .map_elements(chain_hops, return_dtype=pl.Int64)
            .alias("chain_hops")
        )
    else:
        out = out.with_columns(pl.lit(0, dtype=pl.Int64).alias("chain_hops"))
    if not has_dist:
        out = out.with_columns(pl.lit(None, dtype=pl.Int64).alias("sanctions_distance"))
    return out


def _print_summary(df: pl.DataFrame) -> None:
    print("=== Summary by region ===")
    if "_source_region" not in df.columns:
        print(df.height, "rows total")
        return
    summary = (
        df.group_by("_source_region")
        .agg(
            pl.len().alias("rows"),
            pl.col("confidence").mean().alias("mean_conf"),
            pl.col("confidence").max().alias("max_conf"),
            pl.col("sanctions_distance").value_counts().alias("dist_counts"),
            pl.col("chain_hops").max().alias("max_chain_hops"),
        )
        .sort("_source_region")
    )
    print(summary)


def _print_columns(df: pl.DataFrame) -> None:
    print("\n=== Columns ===")
    print(", ".join(df.columns))


def _filter_rows(
    df: pl.DataFrame,
    sanctions_distances: list[int] | None,
    min_chain_hops: int | None,
    mmsi: str | None,
    limit: int,
) -> pl.DataFrame:
    out = df
    if mmsi:
        out = out.filter(pl.col("mmsi") == mmsi)
    if sanctions_distances:
        out = out.filter(pl.col("sanctions_distance").is_in(sanctions_distances))
    if min_chain_hops is not None:
        out = out.filter(pl.col("chain_hops") >= min_chain_hops)
    cols = [
        c
        for c in (
            "mmsi",
            "vessel_name",
            "sanctions_distance",
            "chain_hops",
            "confidence",
            "_source_region",
            "region",
            "flag",
        )
        if c in out.columns
    ]
    sort_cols = [c for c in ("sanctions_distance", "chain_hops", "confidence") if c in out.columns]
    return out.select(cols).sort(sort_cols, descending=[False, True, True]).head(limit)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect R2 or local regional watchlists")
    parser.add_argument(
        "--source",
        choices=("arktrace-public", "local"),
        default="arktrace-public",
        help="arktrace-public = browser-facing score/*.parquet (default)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=_REPO_ROOT / "data/processed",
        help="Local data root (for --source local or --pull output)",
    )
    parser.add_argument(
        "--pull",
        action="store_true",
        help="Also run sync_r2.py pull-watchlists into --data-dir (maridb-public zip)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Cache downloaded arktrace-public parquets (default: temp dir)",
    )
    parser.add_argument(
        "--regions",
        nargs="*",
        default=list(_DEFAULT_REGIONS),
        help="Regions to include (default: all 5 publish regions)",
    )
    parser.add_argument(
        "--sanctions-distance",
        type=int,
        nargs="*",
        metavar="N",
        help="Filter by sanctions_distance (e.g. 1 2 for demo chain candidates)",
    )
    parser.add_argument(
        "--min-chain-hops",
        type=int,
        default=None,
        help="Minimum ownership_chain JSON length (2 = vessel + operator)",
    )
    parser.add_argument("--mmsi", help="Show one vessel (prints ownership_chain JSON)")
    parser.add_argument("--limit", type=int, default=30, help="Max rows in table output")
    parser.add_argument("--json", action="store_true", help="Emit filtered rows as JSON")
    parser.add_argument("--summary-only", action="store_true", help="Skip filtered row table")
    args = parser.parse_args()

    if args.pull:
        import subprocess

        if not _SYNC_R2.is_file():
            raise SystemExit(f"sync_r2.py not found at {_SYNC_R2} (run from indago repo root)")
        cmd = [
            sys.executable,
            str(_SYNC_R2),
            "pull-watchlists",
            "--data-dir",
            str(args.data_dir),
        ]
        print("Running:", " ".join(cmd), file=sys.stderr)
        subprocess.run(cmd, check=True, cwd=_REPO_ROOT)

    regions = tuple(args.regions)

    if args.source == "arktrace-public":
        paths = _fetch_arktrace_watchlists(args.cache_dir, regions)
    else:
        local = _find_local_watchlists(args.data_dir)
        if not local:
            raise SystemExit(
                f"No *_watchlist.parquet under {args.data_dir}. "
                f"Run pipeline or: uv run python {_SYNC_R2} pull-watchlists"
            )
        paths = []
        for p in local:
            stem = p.stem.replace("_watchlist", "")
            if stem in regions or not regions:
                paths.append((stem, p))

    df = _enrich(_load_frames(paths))
    _print_columns(df)
    _print_summary(df)

    if args.mmsi:
        row_df = df.filter(pl.col("mmsi") == args.mmsi)
        if row_df.is_empty():
            print(f"\nMMSI {args.mmsi} not in loaded watchlists", file=sys.stderr)
            return 1
        row = row_df.row(0, named=True)
        print(f"\n=== MMSI {args.mmsi} ===")
        for k in ("vessel_name", "sanctions_distance", "chain_hops", "confidence", "_source_region"):
            if k in row:
                print(f"  {k}: {row[k]}")
        raw = row.get("ownership_chain")
        if raw:
            try:
                print(json.dumps(json.loads(raw), indent=2))
            except json.JSONDecodeError:
                print(raw)
        else:
            print("  ownership_chain: (null)")
        return 0

    filtered = _filter_rows(
        df,
        args.sanctions_distance,
        args.min_chain_hops,
        None,
        args.limit,
    )

    if not args.summary_only:
        label = "Filtered rows" if args.sanctions_distance or args.min_chain_hops else "Top by confidence"
        print(f"\n=== {label} (limit {args.limit}) ===")
        if args.json:
            print(json.dumps(filtered.to_dicts(), indent=2))
        else:
            print(filtered)

    demo = df.filter(
        pl.col("sanctions_distance").is_in([1, 2]) & (pl.col("chain_hops") >= 2)
    )
    print(f"\nDemo-ready (distance 1–2, chain_hops >= 2): {demo.height}")
    if demo.height == 0 and not args.summary_only:
        print(
            "  → No multi-hop ownership demo ships on R2 yet (Equasis OWNED_BY not in CI graph).",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
