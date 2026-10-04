-- PostgreSQL remains authoritative when the derived Neo4j projection is down.
ALTER TABLE knowledge_documents
    ADD COLUMN IF NOT EXISTS graph_projection_status TEXT NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS graph_projection_attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS graph_projection_error TEXT,
    ADD COLUMN IF NOT EXISTS graph_projected_at TIMESTAMPTZ;

DO $$
BEGIN
    ALTER TABLE knowledge_documents
        ADD CONSTRAINT knowledge_documents_graph_projection_status_check
        CHECK (graph_projection_status IN ('pending', 'projected', 'failed'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS knowledge_documents_graph_projection_retry_idx
    ON knowledge_documents (graph_projection_status, updated_at)
    WHERE process_id IS NOT NULL
      AND graph_projection_status IN ('pending', 'failed');
