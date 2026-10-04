CREATE TABLE IF NOT EXISTS screen_observations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL UNIQUE,
    conversation_id TEXT NOT NULL,
    screen_session_id UUID NOT NULL,
    previous_frame_id BIGINT NOT NULL,
    current_frame_id BIGINT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    change_score DOUBLE PRECISION NOT NULL CHECK (
        change_score >= 0 AND change_score <= 1
    ),
    summary TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (previous_frame_id > 0),
    CHECK (current_frame_id > previous_frame_id),
    CHECK (length(summary) > 0)
);

CREATE INDEX IF NOT EXISTS screen_observations_conversation_id_idx
    ON screen_observations (conversation_id, occurred_at);
