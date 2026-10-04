-- A Process is the durable thing being taught and learned. One Process
-- accumulates knowledge across one or more expert training sessions, so the
-- learner selects a Process rather than a single past conversation.
CREATE TABLE IF NOT EXISTS processes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (length(btrim(title)) > 0)
);

-- Nullable on purpose: sessions and documents captured before Processes existed
-- keep their evidence and remain readable, they are simply not teachable.
ALTER TABLE training_sessions
    ADD COLUMN IF NOT EXISTS process_id UUID
        REFERENCES processes(id) ON DELETE SET NULL;

ALTER TABLE knowledge_documents
    ADD COLUMN IF NOT EXISTS process_id UUID
        REFERENCES processes(id) ON DELETE SET NULL;

-- Teacher context resolves the newest completed document for one Process.
CREATE INDEX IF NOT EXISTS training_sessions_process_id_idx
    ON training_sessions (process_id, created_at DESC);

CREATE INDEX IF NOT EXISTS knowledge_documents_process_id_idx
    ON knowledge_documents (process_id, updated_at DESC);
