"""
Claude-powered meeting summarization.

Single Claude call per batch of recordings. Produces:
  - TL;DR (top 3 bullets)
  - HOT THIS WEEK / STILL OPEN
  - Per-meeting summaries with sentiment, decisions, action items, blockers
  - Recurring themes across all-time RAG results
  - Content angle suggestions (brief, not full posts)
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


def _call(prompt: str, max_tokens: int = 3000) -> str:
    msg = _get_client().messages.create(
        model=CLAUDE_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text
    log.debug(f"Claude raw ({len(raw)} chars): {raw[:300]}")
    return raw


# ── Main summarizer ───────────────────────────────────────────────────────────

def summarize_meetings(recordings: list[dict], rag_summary: str = "") -> str:
    """
    Single Claude call. Returns a formatted text summary in the slack-summarizer
    style: TL;DR, per-meeting breakdowns, recurring themes, content angles.
    """
    if not recordings:
        return "No meetings with transcripts found for this period."

    count = len(recordings)
    date_range = f"{recordings[0]['started_at'][:10]} – {recordings[-1]['started_at'][:10]}"

    meeting_blocks = []
    for r in recordings:
        tag = r.get("client_tag") or "internal"
        meeting_blocks.append(
            f"--- [{r['title']}] — {r['started_at'][:10]} — {tag} ---\n"
            f"{r.get('raw_transcript', '')}"
        )
    transcripts_text = "\n\n".join(meeting_blocks)

    rag_block = ""
    if rag_summary and rag_summary != "No historical matches found.":
        rag_block = f"""

## Recurring Themes from All-Time Meeting History (RAG)
{rag_summary}
"""

    prompt = f"""You are summarizing meetings for a GTM systems consultant / RevOps operator.
Think of this like a weekly Slack digest — concise, structured, actionable.

## Meetings ({count} calls, {date_range})

{transcripts_text}
{rag_block}
---

## Output Format

Write the summary in this exact structure (plain text with markdown):

**TL;DR** — 3 bullets max, the most important things across all meetings this period.
- ...
- ...
- ...

**HOT THIS WEEK** (only if something is urgent, blocked, or time-sensitive)
- ...

**STILL OPEN** (questions raised but not resolved, decisions still pending)
- ...

Then for EACH meeting, write:

**[Meeting Title]** — [date] — [client_tag]
Sentiment: [emoji + one sentence, e.g. "🟢 On track — scoping finalized"]
- Key bullet 1 (decision, action item with owner, blocker, or important update)
- Key bullet 2
- ...

After all meetings, add:

**RECURRING THEMES** (patterns you see across multiple meetings — only if 2+ meetings share a theme)
- ...

**CONTENT ANGLES** (2-3 one-liner ideas for LinkedIn posts based on the most interesting problems, insights, or patterns — just the angle, not a full draft)
- ...

## Rules
- Be concise. Bullets, not paragraphs.
- Flag dollar amounts, deadlines, and owner names when they appear.
- Skip scheduling logistics and small talk.
- Use *single asterisks* for bold.
- For each meeting: 3-6 bullets max. Focus on decisions, action items, blockers, key updates.
- Action items must include the owner name if mentioned.
- Content angles should be specific and grounded in what was actually discussed — not generic advice.
- If a meeting is just a casual check-in with nothing notable, say "Nothing notable" and move on.
"""

    log.info(f"Summarizing {count} meetings...")
    raw = _call(prompt, max_tokens=3000)
    log.info(f"Summary generated: {len(raw)} chars")
    return raw
