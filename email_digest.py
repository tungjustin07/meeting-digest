"""
Weekly meeting digest email.
Renders the Claude-generated summary as HTML + plain text, sends via Resend.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date

import resend
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("email_digest")


def send(week_start: date, week_end: date, payload: dict, dry_run: bool = False):
    summary = payload.get("raw_moments", {}).get("summary_text", "No summary generated.")
    analyzed = payload.get("recordings_analyzed") or []
    n_meetings = len(analyzed)

    # The summary covers the meetings actually analyzed, whose span can start
    # before week_start — week_of is only the storage key, not the period.
    start, end = _covered_range(analyzed, week_start, week_end)
    period = _format_range(start, end)
    count = f"{n_meetings} {'meeting' if n_meetings == 1 else 'meetings'}"

    subject = f"Meeting Digest — {period} | {count}"
    html = _render_html(period, summary, count)
    text = _render_text(period, summary, count)

    if dry_run:
        print("\n=" + subject)
        print("=" * 70)
        print(text)
        return

    resend.api_key = os.environ["RESEND_API_KEY"]
    resend.Emails.send({
        "from": os.environ["EMAIL_FROM"],
        "to": [os.environ["EMAIL_TO"]],
        "subject": subject,
        "html": html,
        "text": text,
    })
    log.info(f"Email sent: {subject}")


def _covered_range(analyzed: list[dict], fallback_start: date, fallback_end: date) -> tuple[date, date]:
    """Actual first/last meeting date in the analyzed set."""
    days = sorted(
        d for d in ((r.get("started_at") or "")[:10] for r in analyzed) if len(d) == 10
    )
    if not days:
        return fallback_start, fallback_end
    return date.fromisoformat(days[0]), date.fromisoformat(days[-1])


def _format_range(start: date, end: date) -> str:
    """Never drop the end month — 'Aug 31–4' was the old bug."""
    if start == end:
        return f"{end:%b %-d, %Y}"
    if start.year != end.year:
        return f"{start:%b %-d, %Y} – {end:%b %-d, %Y}"
    if start.month != end.month:
        return f"{start:%b %-d} – {end:%b %-d, %Y}"
    return f"{start:%b %-d}–{end:%-d, %Y}"


def _render_html(period: str, summary: str, count: str) -> str:
    summary_html = _escape(summary)
    summary_html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", summary_html)
    summary_html = re.sub(r"\*(.+?)\*", r"<strong>\1</strong>", summary_html)
    summary_html = re.sub(r"^- ", "• ", summary_html, flags=re.MULTILINE)
    summary_html = summary_html.replace("\n\n", "</p><p style='margin:8px 0'>")
    summary_html = summary_html.replace("\n", "<br>")
    summary_html = f"<p style='margin:8px 0'>{summary_html}</p>"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,sans-serif">
  <div style="max-width:640px;margin:28px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 16px rgba(0,0,0,.08)">

    <div style="background:#111;padding:24px 32px 20px">
      <p style="margin:0 0 4px;font-size:11px;color:#666;text-transform:uppercase;letter-spacing:.1em">Weekly Meeting Digest</p>
      <h1 style="margin:0;font-size:22px;font-weight:700;color:#fff">{period}</h1>
      <p style="margin:6px 0 0;font-size:13px;color:#888">{count} analyzed</p>
    </div>

    <div style="padding:24px 32px">
      <div style="font-size:14px;line-height:1.8;color:#222">
        {summary_html}
      </div>
    </div>

  </div>
</body>
</html>"""


def _render_text(period: str, summary: str, count: str) -> str:
    return (
        f"MEETING DIGEST — {period}\n"
        f"{count} analyzed\n"
        f"{'=' * 70}\n\n"
        f"{summary}"
    )


def _escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
