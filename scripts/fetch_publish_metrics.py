#!/usr/bin/env python3
"""Fetch and print indago data-publish metrics from public R2 snapshots.

Reads maridb-public/metrics/index.json and the newest daily JSON files.
No AWS credentials required (uses the public r2.dev mirror used by dashboard/).

Usage
-----
    uv run python scripts/fetch_publish_metrics.py
    uv run python scripts/fetch_publish_metrics.py --days 7
    uv run python scripts/fetch_publish_metrics.py --interpret
    uv run python scripts/fetch_publish_metrics.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

_DEFAULT_BASE = "https://pub-e088008b61ee432b906ef710d52af28c.r2.dev"
_REGRESSION_THRESHOLD = 0.02


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "indago-fetch-publish-metrics/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} for {url}") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"Failed to fetch {url}: {e}") from e


def _fetch_snapshots(base: str, days: int) -> list[dict]:
    index = _get(f"{base}/metrics/index.json")
    entries: list[str] = index.get("entries", [])[:days]
    snaps: list[dict] = []
    for key in entries:
        snap = _get(f"{base}/metrics/{key}.json")
        snap.setdefault("date", key)
        snaps.append(snap)
    return snaps


def _delta_str(new: float | int | None, old: float | int | None, fmt: str = ".4f") -> str:
    if new is None or old is None:
        return "—"
    d = float(new) - float(old)
    if abs(d) < 1e-9:
        return "→ 0"
    arrow = "↑" if d > 0 else "↓"
    return f"{arrow} {abs(d):{fmt}}"


def _interpret(snaps: list[dict]) -> list[str]:
    if not snaps:
        return ["No snapshots found."]
    lines: list[str] = []
    latest = snaps[0]
    prev = snaps[1] if len(snaps) > 1 else None
    old = snaps[-1] if len(snaps) > 1 else None

    p50 = latest.get("precision_at_50")
    lines.append(f"Latest date: {latest.get('date')} (generated {latest.get('generated_at_utc', '?')[:19]})")
    if p50 is not None:
        ci_lo, ci_hi = latest.get("precision_at_50_ci_low"), latest.get("precision_at_50_ci_high")
        ci = f" (CI 95%: {ci_lo:.4f}–{ci_hi:.4f})" if ci_lo is not None and ci_hi is not None else ""
        lines.append(f"  Precision@50 (regional mean): {p50:.4f}{ci}")
        if prev and prev.get("precision_at_50") is not None:
            d = float(p50) - float(prev["precision_at_50"])
            if d < -_REGRESSION_THRESHOLD:
                lines.append(f"  ⚠️  Regression vs prior day ({d:+.4f}, threshold −{_REGRESSION_THRESHOLD})")
            elif d > _REGRESSION_THRESHOLD:
                lines.append(f"  ✅ Improved vs prior day ({d:+.4f})")
            else:
                lines.append(f"  → Stable vs prior day ({d:+.4f} — normal noise if |d| < {_REGRESSION_THRESHOLD})")
        if old and old.get("precision_at_50") is not None and len(snaps) > 2:
            d7 = float(p50) - float(old["precision_at_50"])
            lines.append(
                f"  7d+ trend ({old.get('date')} → {latest.get('date')}): {old['precision_at_50']:.4f} → {p50:.4f} ({d7:+.4f})"
            )
    if latest.get("recall_at_200") is not None:
        lines.append(f"  Recall@200: {latest['recall_at_200']:.4f}")
        if float(latest["recall_at_200"]) < 1.0:
            lines.append("  ⚠️  Recall@200 < 1.0 — investigate ranking in at least one region")
    if latest.get("known_positives") is not None:
        lines.append(f"  Known positives: {latest['known_positives']}")
    skipped = latest.get("skipped_regions") or []
    if skipped:
        lines.append(f"  ⚠️  Skipped regions: {', '.join(skipped)}")
    else:
        lines.append(f"  Regions: {', '.join(latest.get('regions') or [])}")
    if latest.get("pre_designation_count") is not None:
        lines.append(
            f"  Pre-designation: {latest['pre_designation_count']} cases; "
            f"median lead {latest.get('median_lead_days', '—')}d, "
            f"mean {latest.get('mean_lead_days', '—')}d"
        )
    lines.append("")
    lines.append("Note: email P@50 is the mean of 5 regional P@50 values; global candidate_watchlist P@50 may differ by ~0.00x.")
    lines.append("See docs/ref-data-publish-metrics.md for full interpretation.")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch indago publish metrics from public R2")
    parser.add_argument("--base", default=_DEFAULT_BASE, help="R2 public base URL")
    parser.add_argument("--days", type=int, default=3, help="Number of daily snapshots (newest first)")
    parser.add_argument("--json", action="store_true", help="Emit JSON array only")
    parser.add_argument("--interpret", action="store_true", help="Print human interpretation")
    args = parser.parse_args()

    snaps = _fetch_snapshots(args.base, max(1, args.days))
    if args.json:
        print(json.dumps(snaps, indent=2))
        return 0
    if args.interpret:
        for line in _interpret(snaps):
            print(line)
        return 0

    for i, s in enumerate(snaps):
        prev = snaps[i + 1] if i + 1 < len(snaps) else None
        print(f"\n=== {s.get('date')} ===")
        for key in (
            "precision_at_50",
            "precision_at_50_ci_low",
            "precision_at_50_ci_high",
            "recall_at_200",
            "auroc",
            "known_positives",
            "pre_designation_count",
            "mean_lead_days",
            "median_lead_days",
            "regions",
            "skipped_regions",
        ):
            if key in s and s[key] is not None:
                extra = ""
                if prev and key in prev and prev[key] is not None and key == "precision_at_50":
                    extra = f"  ({_delta_str(s[key], prev[key])} vs prior)"
                print(f"  {key}: {s[key]}{extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
