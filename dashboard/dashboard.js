/**
 * indago pipeline dashboard — maintainer ops tool
 *
 * Shows pipeline health: regression gate pass/fail, region coverage,
 * skipped regions, and data freshness.
 *
 * Analyst metrics (P@50, Recall, lead days, SHAP) live at arktrace.edgesentry.io.
 *
 * Data flow:
 *   1. Fetch metrics/index.json from R2
 *   2. For each entry: check OPFS cache (< 24h) → else fetch from R2
 *   3. Render pipeline status charts with Observable Plot (CDN)
 *   4. Render run history table
 */

import * as Plot from "https://cdn.jsdelivr.net/npm/@observablehq/plot@0.6/+esm";

// ?local serves from ./metrics/ (for local dev — run dev-serve.sh)
// ?refresh clears OPFS cache and re-fetches from R2
const _params = new URLSearchParams(location.search);
const LOCAL_MODE = _params.has("local") || _params.get("local") === "1" || _params.get("local") === "true";
const FORCE_REFRESH = _params.has("refresh");
const R2_BASE = LOCAL_MODE ? "." : "https://pub-e088008b61ee432b906ef710d52af28c.r2.dev";
const INDEX_URL = `${R2_BASE}/metrics/index.json`;
const OPFS_CACHE_TTL_MS = LOCAL_MODE ? 0 : 24 * 60 * 60 * 1000;

const GATE_THRESHOLD = 0.25;

// ---------------------------------------------------------------------------
// OPFS helpers
// ---------------------------------------------------------------------------

async function opfsGet(key) {
  if (FORCE_REFRESH) return null;
  try {
    const root = await navigator.storage.getDirectory();
    const dir = await root.getDirectoryHandle("indago-metrics", { create: true });
    const file = await dir.getFileHandle(key);
    const f = await file.getFile();
    const text = await f.text();
    const { ts, data } = JSON.parse(text);
    if (Date.now() - ts < OPFS_CACHE_TTL_MS) return data;
  } catch (_) { /* cache miss */ }
  return null;
}

async function opfsSet(key, data) {
  try {
    const root = await navigator.storage.getDirectory();
    const dir = await root.getDirectoryHandle("indago-metrics", { create: true });
    const file = await dir.getFileHandle(key, { create: true });
    const writable = await file.createWritable();
    await writable.write(JSON.stringify({ ts: Date.now(), data }));
    await writable.close();
  } catch (_) { /* best-effort */ }
}

async function fetchWithCache(url, cacheKey) {
  const cached = await opfsGet(cacheKey);
  if (cached) return cached;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${url}`);
  const data = await res.json();
  await opfsSet(cacheKey, data);
  return data;
}

// ---------------------------------------------------------------------------
// Chart helpers
// ---------------------------------------------------------------------------

function sparkline(snapshots, field, { color = "#3fb950", fmt = (v) => String(v) } = {}) {
  const data = snapshots
    .filter((s) => s[field] != null)
    .map((s) => ({ date: new Date(s.date), value: +s[field] }));

  if (data.length === 0) return null;

  return Plot.plot({
    width: 300,
    height: 100,
    marginLeft: 32,
    marginRight: 8,
    marginTop: 8,
    marginBottom: 24,
    style: { background: "transparent", color: "#8b949e", fontSize: "11px" },
    x: { type: "time", label: null, tickFormat: "%m/%d" },
    y: { label: null, tickFormat: fmt, ticks: 3 },
    marks: [
      Plot.lineY(data, { x: "date", y: "value", stroke: color, strokeWidth: 2 }),
      Plot.dotY(data, { x: "date", y: "value", fill: color, r: 3 }),
    ],
  });
}

function trendChart(snapshots, { width = 560 } = {}) {
  const data = snapshots
    .filter((s) => s.precision_at_50 != null)
    .map((s) => ({
      date: new Date(s.date),
      p50: +s.precision_at_50,
      lo: s.precision_at_50_ci_low != null ? +s.precision_at_50_ci_low : null,
      hi: s.precision_at_50_ci_high != null ? +s.precision_at_50_ci_high : null,
    }));

  if (data.length === 0) return null;

  const hasCi = data.some((d) => d.lo != null && d.hi != null);
  const marks = [];
  if (hasCi) {
    marks.push(
      Plot.areaY(data.filter((d) => d.lo != null), {
        x: "date", y1: "lo", y2: "hi",
        fill: "#58a6ff", fillOpacity: 0.15,
      })
    );
  }
  marks.push(
    Plot.lineY(data, { x: "date", y: "p50", stroke: "#58a6ff", strokeWidth: 2 }),
    Plot.dotY(data, { x: "date", y: "p50", fill: "#58a6ff", r: 3 }),
  );

  return Plot.plot({
    width,
    height: 140,
    marginLeft: 40,
    marginRight: 8,
    marginTop: 8,
    marginBottom: 28,
    style: { background: "transparent", color: "#8b949e", fontSize: "11px" },
    x: { type: "time", label: null, tickFormat: "%m/%d" },
    y: { label: null, tickFormat: ".3f", ticks: 4 },
    marks,
  });
}

function leadTimeTrendChart(snapshots, { width = 560 } = {}) {
  const data = snapshots
    .filter((s) => s.mean_lead_days != null)
    .map((s) => ({
      date: new Date(s.date),
      mean: +s.mean_lead_days,
      median: s.median_lead_days != null ? +s.median_lead_days : null,
    }));

  if (data.length === 0) return null;

  const marks = [
    Plot.lineY(data, { x: "date", y: "mean", stroke: "#bc8cff", strokeWidth: 2 }),
    Plot.dotY(data, { x: "date", y: "mean", fill: "#bc8cff", r: 3 }),
  ];
  if (data.some((d) => d.median != null)) {
    marks.push(
      Plot.lineY(data.filter((d) => d.median != null), {
        x: "date", y: "median", stroke: "#bc8cff", strokeWidth: 1.5, strokeDasharray: "4,3",
      })
    );
  }

  return Plot.plot({
    width,
    height: 140,
    marginLeft: 40,
    marginRight: 8,
    marginTop: 8,
    marginBottom: 28,
    style: { background: "transparent", color: "#8b949e", fontSize: "11px" },
    x: { type: "time", label: null, tickFormat: "%m/%d" },
    y: { label: null, tickFormat: (v) => `${v}d`, ticks: 4 },
    marks,
  });
}

function knownPositivesChart(snapshots, { width = 560 } = {}) {
  const data = snapshots
    .filter((s) => s.known_positives != null)
    .map((s) => ({ date: new Date(s.date), value: +s.known_positives }));

  if (data.length === 0) return null;

  return Plot.plot({
    width,
    height: 140,
    marginLeft: 40,
    marginRight: 8,
    marginTop: 8,
    marginBottom: 28,
    style: { background: "transparent", color: "#8b949e", fontSize: "11px" },
    x: { type: "time", label: null, tickFormat: "%m/%d" },
    y: { label: null, tickFormat: "d", ticks: 4 },
    marks: [
      Plot.lineY(data, { x: "date", y: "value", stroke: "#e3b341", strokeWidth: 2 }),
      Plot.dotY(data, { x: "date", y: "value", fill: "#e3b341", r: 3 }),
    ],
  });
}

// ---------------------------------------------------------------------------
// DOM helpers
// ---------------------------------------------------------------------------

function setStatus(msg, isError = false) {
  const el = document.getElementById("status");
  el.textContent = msg;
  el.className = isError ? "error" : "";
}

function setMetric(id, text, colorCls = "") {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text ?? "—";
  el.className = ["metric-value", colorCls].filter(Boolean).join(" ");
}

function setSub(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text ?? "";
}

function mountChart(containerId, chart) {
  const el = document.getElementById(containerId);
  if (!el || !chart) return;
  el.innerHTML = "";
  el.appendChild(chart);
}

function gatePass(snap) {
  return snap.precision_at_50 != null && snap.precision_at_50 >= GATE_THRESHOLD;
}

function renderTable(snapshots) {
  const tbody = document.getElementById("history-body");
  tbody.innerHTML = "";
  for (const s of snapshots) {
    const pass = gatePass(s);
    const regions = (s.regions || []).join(", ") || "—";
    const skipped = (s.skipped_regions || []);
    const skippedText = skipped.length > 0 ? skipped.join(", ") : "none";
    const genTime = s.generated_at_utc?.slice(0, 16).replace("T", " ") ?? "—";

    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${s.date}</td>
      <td class="${pass ? "good" : "bad"}">${pass ? "PASS" : "FAIL"}</td>
      <td>${regions}</td>
      <td class="${skipped.length > 0 ? "bad" : "good"}">${skippedText}</td>
      <td style="color:#484f58;font-size:0.7rem">${genTime} UTC</td>
    `;
    tbody.appendChild(row);
  }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  setStatus("Fetching index from R2…");

  let index;
  try {
    index = await fetchWithCache(INDEX_URL, "index.json");
  } catch (err) {
    setStatus(`Failed to load index: ${err.message}`, true);
    return;
  }

  const entries = index.entries || [];
  if (entries.length === 0) {
    setStatus("No snapshots found in index.", true);
    return;
  }

  setStatus(`Loading ${entries.length} snapshot(s)…`);

  const snapshots = [];
  for (const dateKey of entries) {
    const url = `${R2_BASE}/metrics/${dateKey}.json`;
    try {
      const snap = await fetchWithCache(url, `snapshot-${dateKey}.json`);
      snapshots.push(snap);
    } catch (err) {
      console.warn(`Failed to load snapshot ${dateKey}:`, err);
    }
  }

  if (snapshots.length === 0) {
    setStatus("No snapshots could be loaded.", true);
    return;
  }

  snapshots.sort((a, b) => a.date.localeCompare(b.date));
  const latest = snapshots.at(-1);

  // Pipeline status (regression gate)
  const pass = gatePass(latest);
  setMetric("val-gate", pass ? "PASS" : "FAIL", pass ? "good" : "bad");
  setSub("sub-gate", `regression gate · P@50 ≥ ${GATE_THRESHOLD} · latest: ${latest.precision_at_50?.toFixed(4) ?? "—"}`);

  // Regression gate history as 0/1 sparkline
  mountChart("chart-gate", sparkline(snapshots, "precision_at_50", {
    color: pass ? "#3fb950" : "#f85149",
    fmt: (v) => v.toFixed(2),
  }));

  // Regions covered
  const regionCount = (latest.regions || []).length;
  const totalKnown = 5;
  const regionColor = regionCount >= totalKnown ? "good" : regionCount > 0 ? "warn" : "bad";
  setMetric("val-regions", `${regionCount}/${totalKnown}`, regionColor);
  setSub("sub-regions", (latest.regions || []).join(" · ") || "no regions");

  mountChart("chart-regions", sparkline(
    snapshots.map((s) => ({ ...s, region_count: (s.regions || []).length })),
    "region_count",
    { color: "#58a6ff", fmt: (v) => String(Math.round(v)) },
  ));

  // Skipped regions
  const skipped = latest.skipped_regions || [];
  const skippedColor = skipped.length === 0 ? "good" : "bad";
  setMetric("val-skipped", String(skipped.length), skippedColor);
  setSub("sub-skipped", skipped.length > 0 ? `skipped: ${skipped.join(", ")}` : "all regions healthy");

  mountChart("chart-skipped", sparkline(
    snapshots.map((s) => ({ ...s, skipped_count: (s.skipped_regions || []).length })),
    "skipped_count",
    { color: "#f85149", fmt: (v) => String(Math.round(v)) },
  ));

  // Data freshness
  if (latest.generated_at_utc) {
    const genMs = new Date(latest.generated_at_utc).getTime();
    const hoursAgo = Math.round((Date.now() - genMs) / 3_600_000);
    const freshnessColor = hoursAgo <= 26 ? "good" : hoursAgo <= 48 ? "warn" : "bad";
    setMetric("val-freshness", `${hoursAgo}h`, freshnessColor);
    setSub("sub-freshness", `last run: ${latest.generated_at_utc.slice(0, 16).replace("T", " ")} UTC`);
  }

  // Precision@50 trend (30-day with CI band)
  const p50Latest = latest.precision_at_50;
  const p50Prev = snapshots.length >= 2 ? snapshots.at(-2)?.precision_at_50 : null;
  const p50Delta = p50Latest != null && p50Prev != null ? p50Latest - p50Prev : null;
  const p50DeltaStr = p50Delta != null
    ? `${p50Delta >= 0 ? "+" : ""}${p50Delta.toFixed(4)} vs prev day`
    : "";
  setMetric("val-p50-trend", p50Latest != null ? p50Latest.toFixed(4) : "—",
    p50Delta == null ? "" : p50Delta > 0.001 ? "good" : p50Delta < -0.001 ? "bad" : "");
  setSub("sub-p50-trend", p50DeltaStr || "precision at rank 50");
  mountChart("chart-p50-trend", trendChart(snapshots));

  // Known positives trend
  const kpLatest = latest.known_positives;
  const kpPrev = snapshots.length >= 2 ? snapshots.at(-2)?.known_positives : null;
  const kpDelta = kpLatest != null && kpPrev != null ? kpLatest - kpPrev : null;
  const kpDeltaStr = kpDelta != null
    ? `${kpDelta >= 0 ? "+" : ""}${kpDelta} vs prev day`
    : "";
  setMetric("val-kp-trend", kpLatest ?? "—");
  setSub("sub-kp-trend", kpDeltaStr || "OFAC-matched watchlist positives");
  mountChart("chart-kp-trend", knownPositivesChart(snapshots));

  // Lead time trend
  const ltLatest = latest.mean_lead_days;
  const ltPrev = snapshots.length >= 2 ? snapshots.at(-2)?.mean_lead_days : null;
  const ltDelta = ltLatest != null && ltPrev != null ? ltLatest - ltPrev : null;
  const ltDeltaStr = ltDelta != null
    ? `${ltDelta >= 0 ? "+" : ""}${ltDelta.toFixed(1)}d vs prev day`
    : "";
  const medianLatest = latest.median_lead_days;
  const preDesigCount = latest.pre_designation_count;
  const p25Latest = latest.p25_lead_days;
  const p75Latest = latest.p75_lead_days;
  setMetric("val-lt-trend", ltLatest != null ? `${ltLatest.toFixed(1)}d` : "—");
  setSub("sub-lt-trend", [
    ltDeltaStr || "mean lead days",
    medianLatest != null ? `median ${medianLatest.toFixed(0)}d` : "",
    p25Latest != null && p75Latest != null ? `p25–p75: ${p25Latest.toFixed(0)}–${p75Latest.toFixed(0)}d` : "",
    preDesigCount != null ? `${preDesigCount} vessels` : "",
  ].filter(Boolean).join(" · "));
  mountChart("chart-lt-trend", leadTimeTrendChart(snapshots));

  renderTable([...snapshots].reverse());

  const cached = await navigator.storage.estimate();
  const updatedAt = index.updated_at_utc?.slice(0, 16).replace("T", " ") ?? "unknown";
  const cacheKB = cached.usage ? Math.round(cached.usage / 1024) : "?";
  document.getElementById("footer").textContent =
    `Index updated: ${updatedAt} UTC · OPFS cache: ~${cacheKB} KB · Source: maridb-public R2`;

  setStatus(`Showing ${snapshots.length} snapshot(s) · latest: ${latest.date}`);
}

main().catch((err) => setStatus(`Unexpected error: ${err.message}`, true));
