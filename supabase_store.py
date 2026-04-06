"""
Supabase reads and writes for the content engine.
All operations against the shared Supabase project (qadzpahnontwqbjuvntx).
"""

import logging
import os
from datetime import date
from typing import Optional

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()
log = logging.getLogger("supabase_store")

TRANSCRIPT_CHAR_LIMIT = 3000  # chars per recording sent to Claude

_client: Optional[Client] = None


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )
    return _client


# ── Recordings ────────────────────────────────────────────────────────────────

def fetch_recent_recordings(start: date, end: date) -> list[dict]:
    """
    Returns recordings started within [start, end] that have a transcript.
    Truncates raw_transcript to TRANSCRIPT_CHAR_LIMIT chars each.
    """
    resp = (
        _get_client()
        .table("recordings")
        .select("id, title, started_at, ended_at, participants, raw_transcript, client_tag, source")
        .gte("started_at", start.isoformat())
        .lte("started_at", f"{end.isoformat()}T23:59:59")
        .not_.is_("raw_transcript", "null")
        .order("started_at", desc=False)
        .execute()
    )
    rows = resp.data or []
    for r in rows:
        if r.get("raw_transcript"):
            r["raw_transcript"] = r["raw_transcript"][:TRANSCRIPT_CHAR_LIMIT]
    log.info(f"Fetched {len(rows)} recordings from {start} to {end}")
    return rows


def fetch_recording_ids_in_range(start: date, end: date) -> list[str]:
    """Lightweight fetch — just IDs — used to bound RAG attribution."""
    resp = (
        _get_client()
        .table("recordings")
        .select("id")
        .gte("started_at", start.isoformat())
        .lte("started_at", f"{end.isoformat()}T23:59:59")
        .execute()
    )
    return [r["id"] for r in (resp.data or [])]


# ── RAG ───────────────────────────────────────────────────────────────────────

def match_chunks_rag(
    query_embedding: list[float],
    match_count: int = 20,
    match_threshold: float = 0.65,
) -> list[dict]:
    """
    Calls the match_chunks() RPC function in Supabase.
    Returns dicts with: chunk_id, recording_id, recording_title, started_at,
                        client_tag, grain_url, speaker, chunk_text, similarity
    """
    resp = _get_client().rpc(
        "match_chunks",
        {
            "query_embedding": query_embedding,
            "match_threshold": match_threshold,
            "match_count": match_count,
            "filter_client_tag": None,  # search across all clients
            "filter_source": None,      # search across all sources
        },
    ).execute()
    return resp.data or []


# ── Content Calendar ──────────────────────────────────────────────────────────

def already_generated(week_of: date) -> bool:
    """True if this week already has output in content_calendar."""
    resp = (
        _get_client()
        .table("content_calendar")
        .select("week_of")
        .eq("week_of", week_of.isoformat())
        .execute()
    )
    return bool(resp.data)


def upsert_content_calendar(week_of: date, payload: dict):
    """
    Idempotent upsert keyed on week_of.
    payload keys: recordings_analyzed, raw_moments, recurring_problems,
                  content_angles, linkedin_posts, calendar_30day, model
    """
    _get_client().table("content_calendar").upsert(
        {**payload, "week_of": week_of.isoformat()},
        on_conflict="week_of",
    ).execute()
    log.info(f"Upserted content_calendar for week_of={week_of}")


def fetch_content_calendar(week_of: date) -> Optional[dict]:
    """Fetch a previously generated week's output."""
    resp = (
        _get_client()
        .table("content_calendar")
        .select("*")
        .eq("week_of", week_of.isoformat())
        .execute()
    )
    rows = resp.data or []
    return rows[0] if rows else None
