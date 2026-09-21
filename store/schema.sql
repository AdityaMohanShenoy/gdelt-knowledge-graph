-- Evidence store — BUILD_PLAN P1.1.
--
-- Postgres rather than the plan's SQLite. Postgres is already running with the
-- article corpus, P2.4 wants four annotators working concurrently (the plan's
-- own trigger for choosing Supabase), and SQLite would put the evidence store
-- in a different database from the articles it references: no foreign keys and
-- two backup stories. The DDL stays portable.
--
-- Evidence tables are append-only, enforced by trigger rather than convention.
-- Corrections are new rows superseding old ones, which is what makes P5.2 a
-- recompile rather than a migration.

CREATE TABLE IF NOT EXISTS sources (
    source_id            BIGSERIAL PRIMARY KEY,
    -- article_documents is the mutable fetch queue (status, leases, retries).
    -- This is the settled evidence record, and holds the text by reference.
    article_document_id  BIGINT REFERENCES article_documents (document_id),
    url                  TEXT NOT NULL,
    -- Deliberately NOT unique. The table is append-only, and the plan's
    -- correction model is a new row superseding the old one; a unique key would
    -- make correction impossible by either route. The highest source_id for a
    -- url_key is the current record — see the current_sources view.
    url_key              TEXT NOT NULL,
    -- A DATE, not a timestamp: trafilatura reports a day, and a TIMESTAMPTZ
    -- would imply a precision and a timezone we do not have. Validated against
    -- the GDELT event day by 13_load_sources, not trusted as extracted.
    published_at         DATE,
    fetched_at           TIMESTAMPTZ,
    content_hash         TEXT,
    raw_html_path        TEXT,
    fetch_status         TEXT NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS sources_url_key_idx ON sources (url_key, source_id DESC);

-- The current record per URL. History stays queryable in sources itself, which
-- is what makes a rebuild a recompile rather than a migration.
CREATE OR REPLACE VIEW current_sources AS
SELECT DISTINCT ON (url_key) *
FROM sources
ORDER BY url_key, source_id DESC;

CREATE TABLE IF NOT EXISTS entities (
    entity_id       BIGSERIAL PRIMARY KEY,
    kind            TEXT NOT NULL CHECK (kind IN ('actor', 'place', 'organisation')),
    canonical_name  TEXT NOT NULL,
    aliases         JSONB NOT NULL DEFAULT '[]'::jsonb,
    external_ids    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (kind, canonical_name)
);

CREATE TABLE IF NOT EXISTS events (
    event_id           BIGSERIAL PRIMARY KEY,
    event_type         TEXT,
    description        TEXT,
    -- A canonical event carries a point estimate plus the interval it is known
    -- to within; P4 reasoning needs the interval, not just the point.
    best_time          TIMESTAMPTZ,
    time_range_start   TIMESTAMPTZ,
    time_range_end     TIMESTAMPTZ,
    time_confidence    DOUBLE PRECISION CHECK (time_confidence BETWEEN 0 AND 1),
    location_entity_id BIGINT REFERENCES entities (entity_id),
    supporting_sources INTEGER NOT NULL DEFAULT 0,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (time_range_start IS NULL OR time_range_end IS NULL
           OR time_range_start <= time_range_end)
);

CREATE TABLE IF NOT EXISTS mentions (
    mention_id        BIGSERIAL PRIMARY KEY,
    source_id         BIGINT NOT NULL REFERENCES sources (source_id),
    event_id          BIGINT REFERENCES events (event_id),
    actor1_entity_id  BIGINT REFERENCES entities (entity_id),
    actor2_entity_id  BIGINT REFERENCES entities (entity_id),
    action            TEXT,
    event_type        TEXT,
    event_time        TIMESTAMPTZ,
    -- Character offsets into the source's cleaned text. P2.1 requires that
    -- slicing these out reproduces the claim, so they are stored, never derived.
    evidence_start    INTEGER NOT NULL,
    evidence_end      INTEGER NOT NULL,
    confidence        DOUBLE PRECISION,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (evidence_end >= evidence_start)
);

CREATE TABLE IF NOT EXISTS conditions (
    condition_id     BIGSERIAL PRIMARY KEY,
    description      TEXT NOT NULL,
    valid_from       TIMESTAMPTZ,
    valid_to         TIMESTAMPTZ,
    indicator_series TEXT,
    evidence         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to)
);

CREATE TABLE IF NOT EXISTS claims (
    claim_id        BIGSERIAL PRIMARY KEY,
    -- Cause may be an event or a persistent condition (P4.1).
    cause_kind      TEXT NOT NULL CHECK (cause_kind IN ('event', 'condition')),
    cause_id        BIGINT NOT NULL,
    effect_kind     TEXT NOT NULL CHECK (effect_kind IN ('event', 'condition')),
    effect_id       BIGINT NOT NULL,
    relation_type   TEXT,
    stratum         TEXT CHECK (stratum IN ('trigger', 'mobilisation', 'grievance', 'structural')),
    machine_strength DOUBLE PRECISION,
    confidence      DOUBLE PRECISION,
    grade           TEXT,
    -- Rejected candidates stay. They are the hard negatives a trained ranker
    -- needs; accepts plus random negatives teach nothing.
    verdict         TEXT CHECK (verdict IN ('accepted', 'rejected', 'unreviewed')),
    build_id        BIGINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (cause_kind, cause_id, effect_kind, effect_id, build_id)
);

CREATE TABLE IF NOT EXISTS claim_channels (
    claim_channel_id BIGSERIAL PRIMARY KEY,
    claim_id         BIGINT NOT NULL REFERENCES claims (claim_id) ON DELETE CASCADE,
    channel_key      TEXT NOT NULL,
    score            DOUBLE PRECISION,
    -- A channel with no corpus reports unavailable, never zero: absent evidence
    -- and evidence of absence are different inputs to the fusion.
    available        BOOLEAN NOT NULL DEFAULT TRUE,
    raw_inputs       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (claim_id, channel_key)
);

CREATE TABLE IF NOT EXISTS annotations (
    annotation_id    BIGSERIAL PRIMARY KEY,
    claim_id         BIGINT NOT NULL REFERENCES claims (claim_id),
    annotator        TEXT NOT NULL,
    action           TEXT NOT NULL CHECK (action IN ('accept', 'edit', 'reject')),
    reject_reason    TEXT CHECK (reject_reason IN (
        'NO_CAUSAL_EVIDENCE', 'TEMPORALLY_INVALID', 'WRONG_EVENT_MATCH',
        'DUPLICATE_EVENT', 'CORRELATED_ONLY', 'INSUFFICIENT_EVIDENCE',
        'WRONG_DIRECTION', 'OTHER')),
    reason_text      TEXT,
    -- Both values are kept. P3.4 measures calibration by comparing them, so the
    -- machine's suggestion is never overwritten by the human's.
    machine_strength DOUBLE PRECISION,
    human_strength   DOUBLE PRECISION,
    relation_type    TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (action <> 'reject' OR reject_reason IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS build_versions (
    build_id      BIGSERIAL PRIMARY KEY,
    config_hash   TEXT NOT NULL UNIQUE,
    config        JSONB NOT NULL,
    graph_version TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS mentions_source_idx ON mentions (source_id);
CREATE INDEX IF NOT EXISTS mentions_event_idx ON mentions (event_id);
CREATE INDEX IF NOT EXISTS claims_effect_idx ON claims (effect_kind, effect_id);
CREATE INDEX IF NOT EXISTS claims_cause_idx ON claims (cause_kind, cause_id);
CREATE INDEX IF NOT EXISTS claims_verdict_idx ON claims (verdict);
CREATE INDEX IF NOT EXISTS annotations_claim_idx ON annotations (claim_id);

-- Append-only evidence. Enforced, not merely documented: a correction is a new
-- row that supersedes, so the record of what was believed when survives.
CREATE OR REPLACE FUNCTION evidence_is_append_only()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: supersede with a new row instead of %',
        TG_TABLE_NAME, lower(TG_OP);
END;
$$;

DROP TRIGGER IF EXISTS sources_append_only ON sources;
CREATE TRIGGER sources_append_only
    BEFORE UPDATE OR DELETE ON sources
    FOR EACH ROW EXECUTE FUNCTION evidence_is_append_only();

DROP TRIGGER IF EXISTS mentions_append_only ON mentions;
CREATE TRIGGER mentions_append_only
    BEFORE UPDATE OR DELETE ON mentions
    FOR EACH ROW EXECUTE FUNCTION evidence_is_append_only();

DROP TRIGGER IF EXISTS annotations_append_only ON annotations;
CREATE TRIGGER annotations_append_only
    BEFORE UPDATE OR DELETE ON annotations
    FOR EACH ROW EXECUTE FUNCTION evidence_is_append_only();
