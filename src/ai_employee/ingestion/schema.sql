-- Idempotent schema for the document store. Applied by ai_employee.db.init_schema().

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_path   TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL,
    mime_type     TEXT NOT NULL,
    -- SHA-256 of the raw bytes; lets re-ingestion skip unchanged files.
    content_hash  TEXT NOT NULL,
    page_count    INTEGER,
    -- Entra ID principals allowed to see this document. Empty means unrestricted.
    acl_principals TEXT[] NOT NULL DEFAULT '{}',
    metadata      JSONB NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id   UUID NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    chunk_index   INTEGER NOT NULL,
    content       TEXT NOT NULL,
    char_count    INTEGER NOT NULL,
    page_number   INTEGER,
    embedding     vector(768) NOT NULL,
    -- Lexical half of the planned hybrid search.
    content_tsv   TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    metadata      JSONB NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS chunks_document_id_idx ON chunks (document_id);
CREATE INDEX IF NOT EXISTS chunks_content_tsv_idx ON chunks USING GIN (content_tsv);
CREATE INDEX IF NOT EXISTS documents_acl_principals_idx ON documents USING GIN (acl_principals);

-- HNSW over cosine distance: the embeddings are L2-normalised, and unlike IVFFlat
-- it needs no training pass on an empty table.
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);