"""
Slack data fetcher for the combined weekly digest.
Fetches messages from configured channels, returns structured data for Claude.
No LLM calls — pure data collection.

Adapted from /Users/justintung/Projects/slack-summarizer/summarizer.py
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

load_dotenv()
log = logging.getLogger("slack_fetch")

URGENT_EMOJI = {"fire", "rotating_light", "bangbang", "warning", "sos", "eyes"}
REACTION_THRESHOLD = 5
REPLY_THRESHOLD = 8

_user_cache: dict[str, str] = {}
_reader: Optional[WebClient] = None
_writer: Optional[WebClient] = None


def _get_reader() -> WebClient:
    global _reader
    if _reader is None:
        _reader = WebClient(token=os.environ["SLACK_USER_TOKEN"])
    return _reader


def _get_writer() -> WebClient:
    global _writer
    if _writer is None:
        _writer = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
    return _writer


def _load_config(config_path: Optional[str] = None) -> dict:
    path = config_path or str(Path(__file__).parent / "config.yaml")
    with open(path) as f:
        return yaml.safe_load(f)


def _resolve_user(user_id: str) -> str:
    if user_id in _user_cache:
        return _user_cache[user_id]
    try:
        result = _get_reader().users_info(user=user_id)
        name = result["user"]["real_name"]
    except Exception:
        name = user_id
    _user_cache[user_id] = name
    return name


def _resolve_mentions(text: str) -> str:
    def replace(match: re.Match) -> str:
        return f"@{_resolve_user(match.group(1))}"
    return re.sub(r"<@([A-Z0-9]+)>", replace, text)


def _fetch_messages(channel_id: str, channel_name: str) -> tuple[list[str], list[dict], list[dict]]:
    one_week_ago = str(time.time() - (7 * 24 * 60 * 60))
    three_days_ago = time.time() - (3 * 24 * 60 * 60)
    slack_user_id = os.environ.get("SLACK_USER_ID", "")
    all_text: list[str] = []
    raw_messages: list[dict] = []
    awaiting_reply: list[dict] = []
    cursor = None

    while True:
        try:
            kwargs: dict = {"channel": channel_id, "oldest": one_week_ago, "limit": 200}
            if cursor:
                kwargs["cursor"] = cursor
            result = _get_reader().conversations_history(**kwargs)
            raw_messages.extend(result.get("messages", []))
            cursor = result.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break
        except SlackApiError as e:
            err = e.response["error"]
            if err == "ratelimited":
                wait = int(e.response.headers.get("Retry-After", 10))
                log.warning(f"Rate limited on #{channel_name}. Waiting {wait}s...")
                time.sleep(wait)
                continue
            elif err in ("channel_not_found", "not_in_channel"):
                log.warning(f"Skipping #{channel_name}: {err}")
                return [], [], []
            else:
                log.warning(f"Error fetching #{channel_name}: {err}")
                return [], [], []

    for msg in raw_messages:
        if msg.get("subtype"):
            continue
        text = msg.get("text", "").strip()
        if len(text) < 5:
            continue
        user = _resolve_user(msg.get("user", "Unknown"))
        all_text.append(f"{user}: {text}")

        if msg.get("reply_count", 0) > 0:
            try:
                threads = _get_reader().conversations_replies(channel=channel_id, ts=msg["ts"])
                replies = threads["messages"][1:]
                for reply in replies:
                    reply_text = reply.get("text", "").strip()
                    if len(reply_text) < 5:
                        continue
                    reply_user = _resolve_user(reply.get("user", "Unknown"))
                    all_text.append(f"  ↳ {reply_user}: {reply_text}")

                if replies and slack_user_id:
                    last_reply = replies[-1]
                    last_ts = float(last_reply.get("ts", 0))
                    last_user = last_reply.get("user", "")
                    justin_in_thread = any(r.get("user") == slack_user_id for r in replies)
                    if (last_user == slack_user_id
                            and justin_in_thread
                            and last_ts < three_days_ago):
                        parent_text = msg.get("text", "").strip()[:100]
                        parent_user = _resolve_user(msg.get("user", "Unknown"))
                        awaiting_reply.append({
                            "channel": channel_name,
                            "parent": f"{parent_user}: {parent_text}",
                            "days_ago": round((time.time() - last_ts) / 86400),
                        })
            except SlackApiError as e:
                if e.response["error"] == "ratelimited":
                    wait = int(e.response.headers.get("Retry-After", 10))
                    time.sleep(wait)

    return all_text, raw_messages, awaiting_reply


def _detect_urgency(raw_messages: list[dict]) -> list[dict]:
    hot = []
    for msg in raw_messages:
        if msg.get("subtype"):
            continue
        text = msg.get("text", "").strip()
        reasons = []
        reactions = msg.get("reactions", [])
        total_reactions = sum(r["count"] for r in reactions)
        emoji_names = {r["name"] for r in reactions}
        if total_reactions >= REACTION_THRESHOLD:
            reasons.append(f"{total_reactions} reactions")
        if URGENT_EMOJI & emoji_names:
            reasons.append(f"urgent emoji: {', '.join(URGENT_EMOJI & emoji_names)}")
        if msg.get("reply_count", 0) >= REPLY_THRESHOLD:
            reasons.append(f"{msg['reply_count']} thread replies")
        if "<!here>" in text or "<!channel>" in text:
            reasons.append("@here/@channel broadcast")
        if reasons:
            user = _resolve_user(msg.get("user", "Unknown"))
            hot.append({"user": user, "text": text[:150], "reasons": reasons})
    return hot


def _detect_unanswered(raw_messages: list[dict]) -> list[dict]:
    unanswered = []
    for msg in raw_messages:
        if msg.get("subtype"):
            continue
        text = msg.get("text", "").strip()
        if "?" in text and msg.get("reply_count", 0) == 0:
            user = _resolve_user(msg.get("user", "Unknown"))
            unanswered.append({"user": user, "text": text[:150]})
    return unanswered


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_slack_data(config_path: Optional[str] = None) -> list[dict]:
    """
    Fetches last 7 days of messages from all configured channels.
    Returns [] if SLACK_USER_TOKEN or SLACK_BOT_TOKEN are missing.

    Each item: {name, priority, focus, messages, hot, unanswered, awaiting_reply}
    """
    if not os.environ.get("SLACK_USER_TOKEN") or not os.environ.get("SLACK_BOT_TOKEN"):
        log.info("Slack tokens not set — skipping Slack fetch")
        return []

    try:
        config = _load_config(config_path)
    except FileNotFoundError:
        log.info("config.yaml not found — skipping Slack fetch")
        return []

    # Pre-seed known users from config
    for uid, name in config.get("known_users", {}).items():
        _user_cache[uid] = name

    channels = config.get("channels", [])
    channel_data = []

    for ch in channels:
        log.info(f"  Fetching #{ch['name']}...")
        messages, raw, awaiting = _fetch_messages(ch["id"], ch["name"])
        hot = _detect_urgency(raw)
        unanswered = _detect_unanswered(raw)
        log.info(f"    → {len(messages)} messages, {len(hot)} hot, {len(unanswered)} unanswered")

        channel_data.append({
            "name": ch["name"],
            "priority": ch.get("priority", "medium"),
            "focus": ch.get("focus", "general updates"),
            "messages": [_resolve_mentions(m) for m in messages],
            "hot": hot,
            "unanswered": unanswered,
            "awaiting_reply": awaiting,
        })

    return channel_data


def send_slack_dm(text: str) -> None:
    """Send formatted text as a DM to SLACK_USER_ID. Chunks if >3900 chars."""
    slack_user_id = os.environ.get("SLACK_USER_ID")
    if not slack_user_id:
        log.warning("SLACK_USER_ID not set — cannot send DM")
        return

    reader = _get_reader()
    result = reader.conversations_list(types="im", limit=200)
    dm_channel_id = None
    for ch in result.get("channels", []):
        if ch.get("user") == slack_user_id:
            dm_channel_id = ch["id"]
            break

    if not dm_channel_id:
        log.warning(f"Could not find self-DM channel for {slack_user_id}")
        return

    if len(text) <= 3900:
        reader.chat_postMessage(channel=dm_channel_id, text=text, mrkdwn=True)
    else:
        lines = text.split("\n")
        chunks = []
        current = ""
        for line in lines:
            if len(current) + len(line) + 1 > 3900:
                chunks.append(current)
                current = line
            else:
                current += "\n" + line if current else line
        if current:
            chunks.append(current)
        for i, chunk in enumerate(chunks):
            reader.chat_postMessage(channel=dm_channel_id, text=chunk, mrkdwn=True)
            if i < len(chunks) - 1:
                time.sleep(1)

    log.info("Slack DM sent")
