-- Runs once, on first initialisation of the postgres data volume.
-- Enables PGVector so the ingestion pipeline can create vector columns/indexes.
CREATE EXTENSION IF NOT EXISTS vector;