"""
Content Engine — combined weekly digest (Slack + meetings).

Fetches Slack channel activity and meeting transcripts, summarizes both
into one unified digest via Claude, and delivers via email + Slack DM.

Usage:
    python run_weekly.py                          # full run (email + Slack DM)
    python run_weekly.py --dry-run               # print to terminal, no email/Slack/Supabase
    python run_weekly.py --email-only            # re-send from existing Supabase data
    python run_weekly.py --week-of 2026-03-30    # explicit Monday start
    python run_weekly.py --no-slack              # skip Slack fetch (meetings only)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("run_weekly")

MAX_TRANSCRIPT_RECORDINGS = 7  # most recent N for full transcript analysis


def this_monday() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


def main():
    parser = argparse.ArgumentParser(description="Combined weekly digest (Slack + meetings)")
    parser.add_argument("--week-of", help="Monday start date YYYY-MM-DD (default: this Monday)")
    parser.add_argument("--dry-run", action="store_true", help="Print output, no email/Slack/Supabase")
    parser.add_argument("--email-only", action="store_true", help="Re-send email from existing Supabase data")
    parser.add_argument("--no-slack", action="store_true", help="Skip Slack fetch (meetings only)")
    args = parser.parse_args()

    import supabase_store
    import rag_search
    import claude_analyze
    import email_digest
    import slack_fetch

    week_start = date.fromisoformat(args.week_of) if args.week_of else this_monday()
    week_end = date.today()

    log.info(f"Content engine: {week_start} → {week_end}")

    # ── --email-only ──────────────────────────────────────────────────────────
    if args.email_only:
        existing = supabase_store.fetch_content_calendar(week_start)
        if not existing:
            log.error("No existing data — run without --email-only first")
            sys.exit(1)
        email_digest.send(week_start, week_end, existing, dry_run=args.dry_run)
        log.info("Done (email-only).")
        return

    # ── Step 0: Fetch Slack channels ──────────────────────────────────────────
    slack_data: list[dict] = []
    if not args.no_slack:
        log.info("Step 0/3: Fetching Slack channel data...")
        config_yaml = Path(__file__).parent / "config.yaml"
        slack_data = slack_fetch.fetch_slack_data(
            str(config_yaml) if config_yaml.exists() else None
        )
        active_channels = sum(1 for ch in slack_data if ch.get("messages"))
        log.info(f"  → {len(slack_data)} channels fetched, {active_channels} active")
    else:
        log.info("Step 0/3: Slack fetch skipped (--no-slack)")

    # ── Step 1: Fetch all-time recordings ─────────────────────────────────────
    log.info("Step 1/3: Fetching recordings...")
    all_recordings = supabase_store.fetch_recent_recordings(date(2020, 1, 1), week_end)
    recordings = all_recordings[-MAX_TRANSCRIPT_RECORDINGS:]
    log.info(f"  → {len(all_recordings)} total, using most recent {len(recordings)} for summarization")

    recordings_meta = [
        {"id": r["id"], "title": r["title"], "started_at": r.get("started_at", "")[:10], "client_tag": r.get("client_tag")}
        for r in all_recordings
    ]

    # ── Step 2: RAG search for recurring themes ───────────────────────────────
    log.info("Step 2/3: RAG search for recurring themes...")
    themes = []
    for r in recordings:
        text = (r.get("raw_transcript") or "")[:200].strip()
        if text:
            themes.append(text)

    rag_summary = ""
    if themes:
        theme_results = rag_search.search_multiple_themes(themes[:5])
        rag_summary = rag_search.summarize_rag_for_prompt(theme_results)

    # ── Step 3: Summarize with Claude ─────────────────────────────────────────
    log.info("Step 3/3: Summarizing with Claude...")
    if not recordings and not slack_data:
        log.warning("No recordings or Slack activity found — skipping summary")
        sys.exit(0)

    summary = claude_analyze.summarize_meetings(
        recordings,
        rag_summary,
        slack_channel_data=slack_data if slack_data else None,
    )

    # ── Store + Send ──────────────────────────────────────────────────────────
    n_meetings = len(recordings_meta)
    n_channels = len([ch for ch in slack_data if ch.get("messages")]) if slack_data else 0

    payload = {
        "recordings_analyzed": recordings_meta,
        "raw_moments": {"summary_text": summary},
        "recurring_problems": [],
        "content_angles": [],
        "linkedin_posts": [],
        "calendar_30day": [],
        "model": os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001"),
    }

    if not args.dry_run:
        supabase_store.upsert_content_calendar(week_start, payload)

    # Email
    email_digest.send(week_start, week_end, payload, dry_run=args.dry_run,
                      n_channels=n_channels)

    # Slack DM
    if slack_data and not args.dry_run:
        log.info("Sending Slack DM...")
        slack_fetch.send_slack_dm(summary)

    log.info("Done.")


if __name__ == "__main__":
    main()
