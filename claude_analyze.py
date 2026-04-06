"""
Claude-powered combined weekly digest — meetings + Slack channels.

Single Claude call produces a unified summary:
  - TL;DR (across both Slack and meetings)
  - HOT THIS WEEK / STILL OPEN
  - Per-channel Slack summaries
  - Per-meeting summaries with sentiment and action items
  - Recurring themes across both sources
  - Content angle ideas
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("claude_analyze")

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

_client: Optional[Anthropic] = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def _call(prompt: str, max_tokens: int = 4000) -> str:
    msg = _get_client().messages.create(
        model=CLAUDE_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text
    log.debug(f"Claude raw ({len(raw)} chars): {raw[:300]}")
    return raw


# ── Main summarizer ───────────────────────────────────────────────────────────

def summarize_meetings(
    recordings: list[dict],
    rag_summary: str = "",
    slack_channel_data: Optional[list[dict]] = None,
) -> str:
    """
    Single Claude call. Returns a formatted text summary.

    When slack_channel_data is provided, produces a unified digest combining
    Slack channel activity and meeting transcripts into one coherent narrative.

    When slack_channel_data is None or empty, produces a meetings-only digest.
    """
    has_slack = bool(slack_channel_data)
    has_meetings = bool(recordings)

    if not has_slack and not has_meetings:
        return "No meetings or Slack activity found for this period."

    # ── Build Slack block ─────────────────────────────────────────────────────
    slack_block = ""
    if has_slack:
        priority_format = {
            "high": "5-8 bullets (key decisions, action items with owner, blockers, important updates)",
            "medium": "3-5 bullets (key highlights only)",
            "low": "1 bullet or 'Nothing notable this week.'",
        }
        channel_blocks = []
        for ch in slack_channel_data:
            if not ch.get("messages"):
                continue
            priority = ch.get("priority", "medium")
            hot_text = ""
            if ch.get("hot"):
                hot_lines = [f'  - "{h["text"]}" ({", ".join(h["reasons"])})' for h in ch["hot"]]
                hot_text = "URGENT SIGNALS:\n" + "\n".join(hot_lines) + "\n"
            unanswered_text = ""
            if ch.get("unanswered"):
                unanswered_lines = [f'  - {u["user"]}: "{u["text"]}"' for u in ch["unanswered"]]
                unanswered_text = "UNANSWERED QUESTIONS:\n" + "\n".join(unanswered_lines) + "\n"
            awaiting_text = ""
            if ch.get("awaiting_reply"):
                awaiting_lines = [
                    f'  - ({a["days_ago"]}d ago) {a["parent"]}' for a in ch["awaiting_reply"]
                ]
                awaiting_text = "AWAITING JUSTIN'S REPLY:\n" + "\n".join(awaiting_lines) + "\n"

            messages_text = "\n".join(ch["messages"][:200])  # cap per channel
            channel_blocks.append(
                f"--- #{ch['name']} (Priority: {priority}) ---\n"
                f"Focus: {ch.get('focus', 'general updates')}\n"
                f"Format: {priority_format.get(priority, priority_format['medium'])}\n"
                f"{hot_text}{unanswered_text}{awaiting_text}\n"
                f"Messages:\n{messages_text}\n"
            )
        if channel_blocks:
            slack_block = "## Slack Channels\n\n" + "\n".join(channel_blocks)

    # ── Build meetings block ──────────────────────────────────────────────────
    meetings_block = ""
    if has_meetings:
        count = len(recordings)
        date_range = f"{recordings[0]['started_at'][:10]} – {recordings[-1]['started_at'][:10]}"
        meeting_blocks = []
        for r in recordings:
            tag = r.get("client_tag") or "internal"
            meeting_blocks.append(
                f"--- [{r['title']}] — {r['started_at'][:10]} — {tag} ---\n"
                f"{r.get('raw_transcript', '')}"
            )
        meetings_block = (
            f"## Meetings ({count} calls, {date_range})\n\n"
            + "\n\n".join(meeting_blocks)
        )

    # ── Build RAG block ───────────────────────────────────────────────────────
    rag_block = ""
    if rag_summary and rag_summary != "No historical matches found.":
        rag_block = f"\n## Recurring Themes from All-Time Meeting History (RAG)\n{rag_summary}\n"

    # ── Build combined prompt ─────────────────────────────────────────────────
    if has_slack and has_meetings:
        context_line = "You are creating a combined weekly digest for a GTM systems consultant / RevOps operator. Synthesize BOTH Slack channel activity AND meeting transcripts into one coherent weekly summary."
        slack_section = f"""
**SLACK** — per-channel summaries
*#channel-name* — sentiment emoji + one sentence
- bullet
- bullet
(repeat for each active channel; skip empty channels)

"""
        meetings_section = f"""
**MEETINGS** — per-meeting summaries
*[Meeting Title]* — [date] — [client_tag]
Sentiment: [emoji + one sentence, e.g. "🟢 On track — scoping finalized"]
- Key bullet (decision, action item with owner, blocker, key update)
- ...
(3-6 bullets max per meeting; skip if nothing notable)

"""
    elif has_slack:
        context_line = "You are creating a weekly Slack digest for a GTM systems consultant / RevOps operator."
        slack_section = """
**SLACK** — per-channel summaries
*#channel-name* — sentiment emoji + one sentence
- bullet
- bullet
(repeat for each active channel; skip empty channels)

"""
        meetings_section = ""
    else:
        context_line = "You are summarizing meetings for a GTM systems consultant / RevOps operator."
        slack_section = ""
        meetings_section = f"""
**MEETINGS** — per-meeting summaries
*[Meeting Title]* — [date] — [client_tag]
Sentiment: [emoji + one sentence]
- Key bullet (decision, action item with owner, blocker, key update)
- ...
(3-6 bullets max per meeting)

"""

    prompt = f"""{context_line}
Think of this like a weekly Slack digest — concise, structured, actionable.

{slack_block}

{meetings_block}
{rag_block}
---

## Output Format

Write the summary in this exact structure (plain text with markdown):

**TL;DR** — 3 bullets max, the most important things across all sources this week.
- ...
- ...
- ...

**HOT THIS WEEK** (only if something is urgent, blocked, or time-sensitive across Slack or meetings)
- ...

**STILL OPEN** (unanswered Slack questions + unresolved meeting decisions still pending)
- ...

{slack_section}{meetings_section}
**RECURRING THEMES** (patterns appearing across multiple channels or meetings — only if 2+ sources share a theme)
- ...

**CONTENT ANGLES** (2-3 one-liner ideas for LinkedIn posts based on the most interesting problems or patterns — just the angle, not a full draft)
- ...

## Rules
- Be concise. Bullets, not paragraphs.
- Flag dollar amounts, deadlines, and owner names when they appear.
- Skip scheduling logistics, OOO messages, and small talk.
- Use *single asterisks* for bold (never **double**).
- For meetings: flag action items with the owner name if mentioned.
- Content angles should be specific and grounded in what was actually discussed.
- If a channel or meeting has nothing notable, say "Nothing notable" and move on.
- For SLACK sections: format is *bold italic* for channel name with sentiment on same line.
- For MEETINGS sections: format is *bold italic* for meeting title, then Sentiment on next line.
"""

    sources = []
    if has_slack:
        sources.append(f"{len(slack_channel_data)} Slack channels")
    if has_meetings:
        sources.append(f"{len(recordings)} meetings")
    log.info(f"Summarizing {' + '.join(sources)} with Claude...")

    raw = _call(prompt, max_tokens=4000)
    log.info(f"Summary generated: {len(raw)} chars")
    return raw
