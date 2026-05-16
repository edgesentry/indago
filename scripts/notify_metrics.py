"""Send an email summary after a data-publish CI run.

Reads the backtest report JSON produced by run_public_backtest_batch.py and
sends a formatted email with Precision@50, Recall@200, AUROC per region, and
a regression flag if Precision@50 dropped more than 0.02 vs the previous run.

Environment variables (all required unless noted)
-------------------------------------------------
NOTIFY_EMAIL        Recipient address (skip silently if unset)
SMTP_HOST           SMTP server hostname  (default: smtp.gmail.com)
SMTP_PORT           SMTP server port      (default: 587)
SMTP_USER           Sender address / login
SMTP_PASSWORD       SMTP password / app-password
PREVIOUS_P50        Precision@50 from the previous run (optional — used for
                    regression detection; pass via workflow step output)
GITHUB_RUN_ID       Injected automatically by GitHub Actions
GITHUB_REPOSITORY   Injected automatically by GitHub Actions
SNAPSHOT_ID         Timestamp of the R2 snapshot just pushed (optional)
SNAPSHOT_SIZE_MB    Size of the snapshot in MB (optional)
"""

from __future__ import annotations

import json
import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

_REPORT_PATH = Path("data/processed/backtest_public_integration_summary.json")
_TREND_PATH = Path("data/processed/metrics_trend.json")
_LEAD_TIME_PATH = Path("data/processed/lead_time_report.json")
_REGRESSION_THRESHOLD = 0.01  # #507: lowered from 0.02 — catches single-step drops like 0.27→0.26


def _load_report() -> tuple[dict, bool]:
    """Return (report, report_found)."""
    if not _REPORT_PATH.exists():
        return {}, False
    with _REPORT_PATH.open() as f:
        return json.load(f), True


def _format_pipeline_only_body(run_url: str, snapshot_info: str) -> tuple[str, str]:
    """Return (subject, html_body) for a pipeline run with no backtest report."""
    subject = "maridb data publish — pipeline completed (no backtest metrics)"
    html = f"""<html><body>
<h2>maridb data publish</h2>
<p>Pipeline completed successfully. No backtest report was available for this run
(backtest metrics are produced by the separate <em>Public Backtest Integration</em> workflow).</p>
<p><strong>Snapshot:</strong> {snapshot_info}</p>
<p><a href="{run_url}">View CI run →</a></p>
</body></html>"""
    return subject, html


def _load_trend() -> dict:
    """Return trend data from metrics_trend.json written by push_metrics_snapshot.py."""
    try:
        return json.loads(_TREND_PATH.read_text())
    except Exception:
        return {}


def _load_lead_time() -> dict:
    """Return lead time report produced by validate_lead_time_ofac.py."""
    try:
        return json.loads(_LEAD_TIME_PATH.read_text())
    except Exception:
        return {}


def _delta_str(new: float | None, old: float | None, fmt: str = ".4f") -> str:
    """Format a signed delta with up/down arrow."""
    if new is None or old is None:
        return ""
    d = new - old
    arrow = "↑" if d > 0 else "↓" if d < 0 else "→"
    color = "#27ae60" if d > 0 else "#c0392b" if d < 0 else "#8b949e"
    return f' <span style="color:{color}">{arrow} {abs(d):{fmt}}</span>'


def _format_body(
    report: dict, prev_p50: float | None, run_url: str, snapshot_info: str
) -> tuple[str, str]:
    """Return (subject, html_body)."""
    metrics = report.get("metrics_summary", {})
    p50 = metrics.get("precision_at_50", {}).get("mean", 0.0)
    p50_lo = metrics.get("precision_at_50", {}).get("ci95_low")
    p50_hi = metrics.get("precision_at_50", {}).get("ci95_high")
    recall = metrics.get("recall_at_200", {}).get("mean", 0.0)
    regions = report.get("regions", [])
    skipped_regions = report.get("skipped_regions", [])
    skipped_reason = report.get("skipped_reason", "")
    total_positives = report.get("total_known_cases", 0)
    generated_at = report.get("generated_at_utc", "")[:10]

    trend = _load_trend()
    trend_prev_p50: float | None = prev_p50 or trend.get("prev_p50")
    trend_p50_7d: float | None = trend.get("p50_7d_ago")
    trend_prev_positives: int | None = trend.get("prev_known_positives")

    lead = _load_lead_time()
    mean_lead: float | None = lead.get("mean_lead_days")
    median_lead: float | None = lead.get("median_lead_days")
    p25_lead: float | None = lead.get("p25_lead_days")
    p75_lead: float | None = lead.get("p75_lead_days")
    pre_desig_count: int | None = lead.get("pre_designation_count")
    prev_mean_lead: float | None = trend.get("prev_mean_lead_days")
    prev_median_lead: float | None = trend.get("prev_median_lead_days")

    regression = trend_prev_p50 is not None and (trend_prev_p50 - p50) > _REGRESSION_THRESHOLD
    improvement = trend_prev_p50 is not None and (p50 - trend_prev_p50) > _REGRESSION_THRESHOLD

    if regression:
        subject = (
            f"⚠️ indago data publish — Precision@50 regression ({p50:.4f} ↓ from {trend_prev_p50:.4f})"
        )
        status_banner = f'<p style="color:#c0392b;font-weight:bold">⚠️ Regression detected: Precision@50 dropped {trend_prev_p50 - p50:.4f} vs previous run</p>'
    elif improvement:
        subject = (
            f"✅ indago data publish — Precision@50 improved ({p50:.4f} ↑ from {trend_prev_p50:.4f})"
        )
        status_banner = f'<p style="color:#27ae60;font-weight:bold">✅ Improvement: Precision@50 up {p50 - trend_prev_p50:.4f} vs previous run</p>'
    else:
        subject = f"indago data publish — Precision@50 {p50:.4f} ({generated_at})"
        status_banner = ""

    ci_str = f" (CI 95%: {p50_lo:.4f}–{p50_hi:.4f})" if p50_lo and p50_hi else ""

    skipped_note = ""
    if skipped_regions:
        skipped_note = (
            f'<p style="color:#e67e22"><strong>⚠️ Skipped regions (not evaluated):</strong> '
            f"{', '.join(skipped_regions)}<br>"
            f"<em>{skipped_reason}</em></p>"
        )

    region_rows = ""
    for rs in report.get("region_summary", []):
        region = rs.get("region", "")
        matched = rs.get("matched_total", 0)
        total = rs.get("source_positive_total", 0)
        recall_wl = rs.get("source_recall_in_watchlist", 0)
        region_rows += (
            f"<tr><td>{region}</td><td>{matched}/{total}</td><td>{recall_wl:.0%}</td></tr>"
        )

    html = f"""
<html><body style="font-family:sans-serif;max-width:600px">
<h2>indago — Data Publish Summary</h2>
{status_banner}
{skipped_note}
<p><strong>Date:</strong> {generated_at}<br>
<strong>Evaluated regions:</strong> {", ".join(regions) if regions else "none"}<br>
<strong>Snapshot:</strong> {snapshot_info}</p>

<h3>Overall Metrics</h3>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse">
  <tr><th>Metric</th><th>Value</th><th>vs prev day</th><th>7-day trend</th></tr>
  <tr>
    <td>Precision@50</td>
    <td><strong>{p50:.4f}</strong>{ci_str}</td>
    <td>{_delta_str(p50, trend_prev_p50)}</td>
    <td>{"" if trend_p50_7d is None else f"{trend_p50_7d:.4f} → {p50:.4f}{_delta_str(p50, trend_p50_7d)}"}</td>
  </tr>
  <tr>
    <td>Recall@200</td>
    <td>{recall:.4f}</td>
    <td></td><td></td>
  </tr>
  <tr>
    <td>Known positives</td>
    <td>{total_positives}</td>
    <td>{_delta_str(total_positives, trend_prev_positives, "d") if trend_prev_positives is not None else ""}</td>
    <td></td>
  </tr>
</table>

{f"""
<h3>Lead Time — Pre-Designation Detection</h3>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse">
  <tr><th>Metric</th><th>Value</th><th>vs prev day</th></tr>
  <tr>
    <td>Pre-designation detections</td>
    <td><strong>{pre_desig_count if pre_desig_count is not None else "—"}</strong></td>
    <td></td>
  </tr>
  <tr>
    <td>Mean lead time</td>
    <td><strong>{f"{mean_lead:.1f} days" if mean_lead is not None else "—"}</strong></td>
    <td>{_delta_str(mean_lead, prev_mean_lead, ".1f") if mean_lead is not None else ""}</td>
  </tr>
  <tr>
    <td>Median lead time</td>
    <td>{f"{median_lead:.1f} days" if median_lead is not None else "—"}</td>
    <td>{_delta_str(median_lead, prev_median_lead, ".1f") if median_lead is not None else ""}</td>
  </tr>
  <tr>
    <td>p25 / p75</td>
    <td>{f"{p25_lead:.0f} / {p75_lead:.0f} days" if p25_lead is not None and p75_lead is not None else "—"}</td>
    <td></td>
  </tr>
</table>
""" if pre_desig_count is not None or mean_lead is not None else ""}

<h3>Per-Region Coverage</h3>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse">
  <tr><th>Region</th><th>Positives matched</th><th>Recall in watchlist</th></tr>
  {region_rows}
</table>

<p><a href="{run_url}">View CI run →</a></p>
</body></html>
"""
    return subject, html


def main() -> int:
    recipient = os.getenv("NOTIFY_EMAIL")
    if not recipient:
        print("NOTIFY_EMAIL not set — skipping notification.")
        return 0

    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")

    if not smtp_user or not smtp_password:
        print("SMTP_USER / SMTP_PASSWORD not set — skipping notification.", file=sys.stderr)
        return 0

    prev_p50_str = os.getenv("PREVIOUS_P50")
    prev_p50 = float(prev_p50_str) if prev_p50_str else None

    run_id = os.getenv("GITHUB_RUN_ID", "")
    repo = os.getenv("GITHUB_REPOSITORY", "edgesentry/indago")
    run_url = (
        f"https://github.com/{repo}/actions/runs/{run_id}"
        if run_id
        else f"https://github.com/{repo}/actions"
    )

    snapshot_id = os.getenv("SNAPSHOT_ID", "")
    snapshot_mb = os.getenv("SNAPSHOT_SIZE_MB", "")
    snapshot_info = f"{snapshot_id} ({snapshot_mb} MB)" if snapshot_id else "see CI run"

    report, report_found = _load_report()

    if not report_found or (report.get("total_known_cases", 0) == 0 and not report.get("regions")):
        # No backtest results available — send pipeline-only status email.
        # This happens when: (a) report file missing, or (b) all regions were
        # skipped because watchlists have no OFAC-matched vessels yet.
        subject, html_body = _format_pipeline_only_body(run_url, snapshot_info)
    else:
        subject, html_body = _format_body(report, prev_p50, run_url, snapshot_info)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html"))

    print(f"Sending email to {recipient} via {smtp_host}:{smtp_port} …")
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, recipient, msg.as_string())

    print(f"Email sent: {subject}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
