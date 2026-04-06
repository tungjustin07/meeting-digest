"""
Voyage AI embedding + Supabase match_chunks RAG search.
Used to find historically recurring themes across all meetings.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import voyageai
from dotenv import load_dotenv

import supabase_store

load_dotenv()
log = logging.getLogger("rag_search")

VOYAGE_MODEL = "voyage-3-lite"
SIMILARITY_THRESHOLD = 0.3
MATCH_COUNT = 20
RATE_LIMIT_SLEEP = 0.5  # seconds between Voyage calls

_voyage: Optional[voyageai.Client] = None


def _get_voyage() -> voyageai.Client:
    global _voyage
    if _voyage is None:
        _voyage = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])
    return _voyage


def embed_query(text: str) -> list[float]:
    """
    Embed a single search query string.
    Uses input_type="query" (asymmetric search — different from document embedding).
    """
    retries = 0
    while True:
        try:
            result = _get_voyage().embed(
                [text],
                model=VOYAGE_MODEL,
                input_type="query",
            )
            return result.embeddings[0]
        except Exception as e:
            if "429" in str(e) or "rate" in str(e).lower():
                wait = min(20 * (2 ** retries), 60)
                log.warning(f"Voyage rate limit hit — sleeping {wait}s")
                time.sleep(wait)
                retries += 1
                if retries > 5:
                    raise
            else:
                raise


def search_theme(theme_text: str) -> list[dict]:
    """
    Full pipeline: embed theme → match_chunks RPC → return results above threshold.
    """
    embedding = embed_query(theme_text)
    results = supabase_store.match_chunks_rag(
        query_embedding=embedding,
        match_count=MATCH_COUNT,
        match_threshold=SIMILARITY_THRESHOLD,
    )
    log.info(f"Theme '{theme_text[:60]}' → {len(results)} RAG matches")
    return results


def search_multiple_themes(themes: list[str]) -> dict[str, list[dict]]:
    """
    Batch search for all themes from Phase 1 extraction.
    Returns dict keyed by theme text.
    Rate-limit aware: sleeps between Voyage API calls.

    Deduplication: if the same chunk appears for multiple themes it's kept
    only under the theme with the highest similarity score.
    """
    theme_results: dict[str, list[dict]] = {}
    seen_chunk_ids: dict[int, tuple[str, float]] = {}  # chunk_id → (theme, similarity)

    for i, theme in enumerate(themes):
        if i > 0:
            time.sleep(RATE_LIMIT_SLEEP)

        raw = search_theme(theme)
        deduped = []
        for chunk in raw:
            cid = chunk.get("chunk_id")
            sim = chunk.get("similarity", 0.0)
            if cid is None:
                deduped.append(chunk)
                continue
            if cid not in seen_chunk_ids:
                seen_chunk_ids[cid] = (theme, sim)
                deduped.append(chunk)
            else:
                prev_theme, prev_sim = seen_chunk_ids[cid]
                if sim > prev_sim:
                    # Re-attribute to the more similar theme
                    seen_chunk_ids[cid] = (theme, sim)
                    # Remove from previous theme's results
                    theme_results[prev_theme] = [
                        c for c in theme_results.get(prev_theme, []) if c.get("chunk_id") != cid
                    ]
                    deduped.append(chunk)

        theme_results[theme] = deduped

    return theme_results


def summarize_rag_for_prompt(theme_results: dict[str, list[dict]], max_chunks_per_theme: int = 5) -> str:
    """
    Formats RAG results into a string block for injection into Claude prompts.
    Groups by theme, shows top N chunks with recording title, date, and text snippet.
    """
    if not theme_results:
        return "No historical matches found."

    lines = []
    for theme, chunks in theme_results.items():
        if not chunks:
            continue
        unique_recordings = len({c.get("recording_id") for c in chunks})
        lines.append(f'\n### Theme: "{theme}"')
        lines.append(f"Matched {len(chunks)} chunks across {unique_recordings} past meetings:")
        for chunk in chunks[:max_chunks_per_theme]:
            title = chunk.get("recording_title", "Unknown")
            started = (chunk.get("started_at") or "")[:10]
            text = (chunk.get("chunk_text") or "")[:200].replace("\n", " ")
            sim = chunk.get("similarity", 0.0)
            lines.append(f'  - [{title}, {started}] (sim={sim:.2f}): "{text}..."')

    return "\n".join(lines) if lines else "No historical matches found."
