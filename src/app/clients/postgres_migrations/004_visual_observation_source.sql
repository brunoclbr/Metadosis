-- Camera becomes a second visual source alongside the shared screen.
--
-- The table keeps its original name: renaming it would rewrite rows the Work
-- Maps in production already cite by event ID, and the frontend proxy path is
-- deployed independently of this backend, so an additive column is the only
-- change that is safe in both directions during a rollout.
--
-- 'screen' is the default so every row recorded before cameras existed keeps
-- describing exactly what it described.
ALTER TABLE screen_observations
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'screen';

DO $$
BEGIN
    ALTER TABLE screen_observations
        ADD CONSTRAINT screen_observations_source_check
        CHECK (source IN ('screen', 'camera'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;
