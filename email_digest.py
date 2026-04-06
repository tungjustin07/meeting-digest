"""
Weekly meeting summary email digest.
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


def send(week_start: date, week_end: date, payload: dict, dry_run: bool = False, n_channels: int = 0):
    summary = payload.get("raw_moments", {}).get("summary_text", "No summary generated.")
    n_meetings = len(payload.get("recordings_analyzed", []))

    parts = []
    if n_channels:
        parts.append(f"{n_channels} channels")
    if n_meetings:
        parts.append(f"{n_meetings} meetings")
    detail = " · ".join(parts) if parts else "digest"

    subject = f"Weekly Meeting + Slack Digest - {week_start.strftime('%b %-d, %Y')} - {week_end.strftime('%b %-d, %Y')}"
    html = _render_html(week_start, week_end, summary, n_meetings, n_channels)
    text = _render_text(week_start, week_end, summary, n_meetings, n_channels)

    if dry_run:
        print("\n" + "=" + subject)
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


def _render_html(week_start: date, week_end: date, summary: str, n_meetings: int, n_channels: int = 0) -> str:
    # Convert markdown-ish summary to HTML
    summary_html = _escape(summary)
    # Bold: **text** or *text*
    summary_html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", summary_html)
    summary_html = re.sub(r"\*(.+?)\*", r"<strong>\1</strong>", summary_html)
    # Bullets
    summary_html = re.sub(r"^- ", "• ", summary_html, flags=re.MULTILINE)
    # Line breaks
    summary_html = summary_html.replace("\n\n", "</p><p style='margin:8px 0'>")
    summary_html = summary_html.replace("\n", "<br>")
    summary_html = f"<p style='margin:8px 0'>{summary_html}</p>"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,sans-serif">
  <div style="max-width:640px;margin:28px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 16px rgba(0,0,0,.08)">

    <div style="background:#111;padding:24px 32px 20px">
      <p style="margin:0 0 4px;font-size:11px;color:#666;text-transform:uppercase;letter-spacing:.1em">Weekly Digest</p>
      <h1 style="margin:0;font-size:22px;font-weight:700;color:#fff">{week_start.strftime('%b %-d')} – {week_end.strftime('%b %-d, %Y')}</h1>
      <p style="margin:6px 0 0;font-size:13px;color:#888">{n_meetings} meetings · {n_channels} Slack channels</p>
    </div>

    <div style="padding:24px 32px">
      <div style="font-size:14px;line-height:1.8;color:#222">
        {summary_html}
      </div>
    </div>

  </div>
</body>
</html>"""


def _render_text(week_start: date, week_end: date, summary: str, n_meetings: int, n_channels: int = 0) -> str:
    parts = []
    if n_channels:
        parts.append(f"{n_channels} Slack channels")
    if n_meetings:
        parts.append(f"{n_meetings} meetings")
    detail = " · ".join(parts) if parts else "digest"
    return (
        f"WEEKLY DIGEST — {week_start.strftime('%b %-d')} – {week_end.strftime('%b %-d, %Y')}\n"
        f"{detail}\n"
        f"{'=' * 70}\n\n"
        f"{summary}"
    )


def _escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
