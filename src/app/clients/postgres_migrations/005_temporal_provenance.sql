-- Additive provenance v2 fields. Browser-relative time is approximate and kept
-- alongside the original browser UTC timestamp rather than replacing it.
ALTER TABLE screen_observations
    ADD COLUMN IF NOT EXISTS time_in_call_secs DOUBLE PRECISION;

DO $$
BEGIN
    ALTER TABLE screen_observations
        ADD CONSTRAINT screen_observations_time_in_call_secs_check
        CHECK (time_in_call_secs IS NULL OR time_in_call_secs >= 0);
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

ALTER TABLE knowledge_documents
    ADD COLUMN IF NOT EXISTS provenance_version INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS evidence_cutoff TIMESTAMPTZ;

DO $$
BEGIN
    ALTER TABLE knowledge_documents
        ADD CONSTRAINT knowledge_documents_provenance_version_check
        CHECK (provenance_version IN (1, 2));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;
