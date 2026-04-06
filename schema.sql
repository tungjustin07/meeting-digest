-- ============================================================
-- Content Engine — Supabase Schema
-- Run this in: Supabase Dashboard > SQL Editor
-- ============================================================

CREATE TABLE IF NOT EXISTS content_calendar (
    id                  BIGSERIAL PRIMARY KEY,
    week_of             DATE NOT NULL UNIQUE,       -- Monday of the processed week
    recordings_analyzed JSONB DEFAULT '[]',         -- [{id, title, started_at, client_tag}]
    raw_moments         JSONB DEFAULT '[]',         -- {hooks, pain_points, objections, wins}
    recurring_problems  JSONB DEFAULT '[]',         -- [{theme, frequency, recency, representative_quotes, meeting_sources, linkedin_angles}]
    content_angles      JSONB DEFAULT '[]',         -- [{angle, post_type, rationale, source_meetings}]
    linkedin_posts      JSONB DEFAULT '[]',         -- [{type, hook, body, cta, hashtags, source_moment}]
    calendar_30day      JSONB DEFAULT '[]',         -- [{day_offset, date, post_type, angle, title, ready}]
    model               TEXT,
    generated_at        TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_content_calendar_week_of
    ON content_calendar (week_of DESC);

CREATE OR REPLACE FUNCTION touch_content_calendar_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$;

DROP TRIGGER IF EXISTS content_calendar_updated_at ON content_calendar;
CREATE TRIGGER content_calendar_updated_at
    BEFORE UPDATE ON content_calendar
    FOR EACH ROW EXECUTE FUNCTION touch_content_calendar_updated_at();
