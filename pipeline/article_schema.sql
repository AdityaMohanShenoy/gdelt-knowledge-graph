CREATE TABLE IF NOT EXISTS article_documents (
    document_id BIGSERIAL PRIMARY KEY,
    url_key TEXT NOT NULL UNIQUE,
    host_key TEXT GENERATED ALWAYS AS (
        lower(split_part(split_part(url_key, '://', 2), '/', 1))
    ) STORED,
    source_url TEXT NOT NULL,
    final_url TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    http_status INTEGER,
    content_type TEXT,
    title TEXT,
    cleaned_text TEXT,
    text_length INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT,
    raw_html_path TEXT,
    extraction_reason TEXT,
    extractor_version TEXT,
    last_error TEXT,
    lease_expires_at TIMESTAMPTZ,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    fetched_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (
        status IN (
            'pending',
            'fetching',
            'extracted',
            'insufficient_text',
            'paywall',
            'blocked',
            'dead',
            'unsupported_content',
            'response_too_large',
            'http_error',
            'parse_error',
            'retryable_error',
            'retry_exhausted'
        )
    )
);

-- Publication date as reported by the extractor. Added after the table shipped,
-- so it is an ALTER rather than a column in the CREATE above.
ALTER TABLE article_documents ADD COLUMN IF NOT EXISTS published_at DATE;

CREATE INDEX IF NOT EXISTS article_documents_status_idx
    ON article_documents (status, next_attempt_at, document_id);

CREATE INDEX IF NOT EXISTS article_documents_final_url_idx
    ON article_documents (final_url);

CREATE INDEX IF NOT EXISTS article_documents_text_search_idx
    ON article_documents
    USING GIN (to_tsvector('english', COALESCE(title, '') || ' ' || COALESCE(cleaned_text, '')));

CREATE OR REPLACE FUNCTION article_documents_set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS article_documents_updated_at ON article_documents;

CREATE TRIGGER article_documents_updated_at
BEFORE UPDATE ON article_documents
FOR EACH ROW
    EXECUTE FUNCTION article_documents_set_updated_at();

ALTER TABLE article_documents
    ADD COLUMN IF NOT EXISTS host_key TEXT GENERATED ALWAYS AS (
        lower(split_part(split_part(url_key, '://', 2), '/', 1))
    ) STORED;

CREATE INDEX IF NOT EXISTS article_documents_host_status_idx
    ON article_documents (host_key, status, lease_expires_at, document_id);

CREATE INDEX IF NOT EXISTS article_documents_runnable_document_idx
    ON article_documents (document_id)
    INCLUDE (host_key, next_attempt_at)
    WHERE status IN ('pending', 'retryable_error');

CREATE INDEX IF NOT EXISTS article_documents_fetching_document_idx
    ON article_documents (document_id)
    INCLUDE (host_key, lease_expires_at)
    WHERE status = 'fetching';
