# meeting-digest

**Public repository.** Weekly meeting → LinkedIn content pipeline. Reads recent client/sales meeting transcripts, extracts recurring themes via RAG over the all-time corpus, and produces a 30-day LinkedIn content calendar plus draft posts. Stores results in Supabase and emails the digest.

```bash
git clone https://github.com/tungjustin07/meeting-digest.git
cd meeting-digest
```

## What it does

1. **Pull recent meetings** (full transcripts, last 7 by default) from the meeting source (Granola / Otter / etc.).
2. **RAG over all-time corpus** using Voyage embeddings to surface recurring problems, objections, and wins across every meeting in scope — not just this week's.
3. **Claude analysis.** Extracts:
   - Raw moments (hooks, pain points, objections, wins)
   - Recurring problems (with frequency, recency, representative quotes, source meetings)
   - LinkedIn-friendly content angles
   - Drafted posts (hook, body, CTA, hashtags) tied back to source moments
   - 30-day post calendar
4. **Persist** to Supabase `content_calendar` (one row per ISO week).
5. **Email** the digest via Resend.

## Layout

```
run_weekly.py        # entry point + CLI
claude_analyze.py    # prompt + JSON-mode parsing
rag_search.py        # Voyage embedding + Supabase pgvector lookup
supabase_store.py    # write content_calendar rows
email_digest.py      # Resend HTML email
schema.sql           # run this in Supabase SQL Editor first
requirements.txt
```

## Setup

1. Create the Supabase table: paste `schema.sql` into the Supabase SQL Editor.
2. `pip install -r requirements.txt`
3. Create a local `.env` (never commit it):
   ```
   ANTHROPIC_API_KEY=
   CLAUDE_MODEL=claude-haiku-4-5-20251001
   SUPABASE_URL=
   SUPABASE_SERVICE_KEY=
   VOYAGE_API_KEY=
   RESEND_API_KEY=
   EMAIL_FROM=
   EMAIL_TO=
   ```

## Running

```bash
python run_weekly.py                          # full weekly run
python run_weekly.py --dry-run                # print, no email or DB write
python run_weekly.py --email-only             # re-send from an existing Supabase row
python run_weekly.py --week-of 2026-03-30     # explicit Monday-of-week
```

## Schema

`content_calendar` (one row per `week_of` Monday) holds:
`recordings_analyzed`, `raw_moments`, `recurring_problems`, `content_angles`, `linkedin_posts`, `calendar_30day`. All JSONB. See `schema.sql` for the full shape.

## GitHub Actions / secrets

This repo is **public**. Put API keys and email settings in encrypted Actions secrets (Settings → Secrets and variables → Actions), not in the repository. Forks do not inherit secrets.

## Security

- Keep meeting transcripts, Supabase keys, and email credentials out of git
- Prefer `--dry-run` when testing so client content is not emailed by accident
- Review generated LinkedIn drafts before publishing — they may contain sensitive client language
