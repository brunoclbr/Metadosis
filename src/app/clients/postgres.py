"""PostgreSQL adapter for durable Brain records."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator
from uuid import UUID

import psycopg
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from src.config import settings

MIGRATIONS_DIR = Path(__file__).with_name("postgres_migrations")


class PostgresClient:
    """Open short-lived async connections and expose Brain-specific persistence."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[Any]]:
        connection = await psycopg.AsyncConnection.connect(
            self.database_url,
            row_factory=dict_row,
        )
        try:
            yield connection
        finally:
            await connection.close()

    async def initialize(self) -> None:
        """Apply the small, idempotent SQL migrations used by this MVP."""
        async with self.connection() as connection:
            for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
                await connection.execute(migration.read_text(encoding="utf-8"))
            await connection.commit()

    async def create_process(
        self,
        *,
        title: str,
        description: str | None,
    ) -> tuple[dict[str, Any], bool]:
        """Insert once by title and return ``(process, was_created)``.

        Titles are the only name a user ever types, so a repeated title resolves
        to the existing Process instead of creating a second one that would split
        the same expertise across two teachable records.
        """
        async with self.connection() as connection:
            result = await connection.execute(
                """
                INSERT INTO processes (title, description)
                VALUES (%s, %s)
                ON CONFLICT (title) DO NOTHING
                RETURNING id, title, description, created_at, updated_at
                """,
                (title, description),
            )
            row = await result.fetchone()
            if row is not None:
                await connection.commit()
                return dict(row), True

            existing = await connection.execute(
                """
                SELECT id, title, description, created_at, updated_at
                FROM processes
                WHERE title = %s
                """,
                (title,),
            )
            existing_row = await existing.fetchone()
            if existing_row is None:
                raise RuntimeError("Process disappeared during idempotent insert")
            return dict(existing_row), False

    async def list_processes(self) -> list[dict[str, Any]]:
        """Return every Process newest first for selection in the UI."""
        async with self.connection() as connection:
            result = await connection.execute(
                """
                SELECT id, title, description, created_at, updated_at
                FROM processes
                ORDER BY created_at DESC
                """
            )
            return [dict(row) async for row in result]

    async def get_process(self, process_id: UUID) -> dict[str, Any] | None:
        async with self.connection() as connection:
            result = await connection.execute(
                """
                SELECT id, title, description, created_at, updated_at
                FROM processes
                WHERE id = %s
                """,
                (process_id,),
            )
            row = await result.fetchone()
            return dict(row) if row is not None else None

    async def get_process_knowledge_documents(
        self,
        process_id: UUID,
        *,
        knowledge_document_ids: list[UUID] | None = None,
    ) -> list[dict[str, Any]]:
        """Resolve authoritative sources for completed documents in one Process."""
        async with self.connection() as connection:
            result = await connection.execute(
                """
                SELECT
                    kd.id AS knowledge_document_id,
                    kd.structured_knowledge,
                    kd.provenance_version,
                    kd.evidence_cutoff,
                    kd.updated_at,
                    ts.id AS training_session_id,
                    ts.conversation_id,
                    ts.raw_transcript,
                    ts.metadata
                FROM knowledge_documents kd
                JOIN training_sessions ts ON ts.id = kd.training_session_id
                WHERE kd.process_id = %s
                  AND ts.process_id = %s
                  AND ts.status = 'completed'
                  AND (%s::uuid[] IS NULL OR kd.id = ANY(%s::uuid[]))
                ORDER BY kd.updated_at
                """,
                (
                    process_id,
                    process_id,
                    knowledge_document_ids,
                    knowledge_document_ids,
                ),
            )
            return [dict(row) async for row in result]

    async def get_current_process_knowledge(
        self,
        process_id: UUID,
    ) -> dict[str, Any] | None:
        """Compatibility read for the newest completed document."""
        rows = await self.get_process_knowledge_documents(process_id)
        return rows[-1] if rows else None

    async def create_training_session(
        self,
        *,
        conversation_id: str,
        transcript: list[dict[str, Any]],
        metadata: dict[str, Any],
        process_id: UUID | None = None,
    ) -> tuple[UUID, bool]:
        """Insert once by conversation ID and return ``(id, was_created)``."""
        async with self.connection() as connection:
            result = await connection.execute(
                """
                INSERT INTO training_sessions (
                    conversation_id, status, raw_transcript, metadata, process_id
                )
                VALUES (%s, 'received', %s, %s, %s)
                ON CONFLICT (conversation_id) DO NOTHING
                RETURNING id
                """,
                (conversation_id, Jsonb(transcript), Jsonb(metadata), process_id),
            )
            row = await result.fetchone()
            if row is not None:
                await connection.commit()
                return row["id"], True

            existing = await connection.execute(
                "SELECT id FROM training_sessions WHERE conversation_id = %s",
                (conversation_id,),
            )
            existing_row = await existing.fetchone()
            if existing_row is None:
                raise RuntimeError(
                    "Training session disappeared during idempotent insert"
                )
            return existing_row["id"], False

    async def set_training_session_status(self, session_id: UUID, status: str) -> None:
        async with self.connection() as connection:
            await connection.execute(
                """
                UPDATE training_sessions
                SET status = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (status, session_id),
            )
            await connection.commit()

    async def create_screen_observation(
        self,
        *,
        event_id: UUID,
        conversation_id: str,
        screen_session_id: UUID,
        previous_frame_id: int,
        current_frame_id: int,
        occurred_at: Any,
        change_score: float,
        summary: str,
        source: str = "screen",
        time_in_call_secs: float | None = None,
    ) -> bool:
        """Persist a meaningful observation once by its backend-issued event ID."""
        async with self.connection() as connection:
            result = await connection.execute(
                """
                INSERT INTO screen_observations (
                    event_id,
                    conversation_id,
                    screen_session_id,
                    source,
                    previous_frame_id,
                    current_frame_id,
                    occurred_at,
                    change_score,
                    summary,
                    time_in_call_secs
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_id) DO NOTHING
                RETURNING event_id
                """,
                (
                    event_id,
                    conversation_id,
                    screen_session_id,
                    source,
                    previous_frame_id,
                    current_frame_id,
                    occurred_at,
                    change_score,
                    summary,
                    time_in_call_secs,
                ),
            )
            inserted = await result.fetchone()
            if inserted is not None:
                await connection.commit()
                return True

            existing = await connection.execute(
                """
                SELECT conversation_id
                FROM screen_observations
                WHERE event_id = %s
                """,
                (event_id,),
            )
            existing_row = await existing.fetchone()
            if existing_row is None:
                raise RuntimeError("Screen observation disappeared during insert")
            if existing_row["conversation_id"] != conversation_id:
                raise ValueError("Screen event is already bound to another conversation")
            return False

    async def list_screen_observations(
        self,
        conversation_id: str,
        *,
        created_before: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Return textual observations in their source-event order.

        ``source`` says whether the frame pair came from the shared screen or
        the camera. Rows recorded before cameras existed default to ``screen``.
        """
        async with self.connection() as connection:
            result = await connection.execute(
                """
                SELECT event_id, occurred_at, time_in_call_secs, summary, source
                FROM screen_observations
                WHERE conversation_id = %s
                  AND (%s::timestamptz IS NULL OR created_at <= %s)
                ORDER BY occurred_at, created_at, event_id
                """,
                (conversation_id, created_before, created_before),
            )
            return [dict(row) async for row in result]

    async def list_retryable_graph_document_ids(
        self,
        process_id: UUID,
    ) -> list[UUID]:
        async with self.connection() as connection:
            result = await connection.execute(
                """
                SELECT id
                FROM knowledge_documents
                WHERE process_id = %s
                  AND graph_projection_status IN ('pending', 'failed')
                ORDER BY updated_at
                """,
                (process_id,),
            )
            return [row["id"] async for row in result]

    async def get_graph_projection_source(
        self,
        knowledge_document_id: UUID,
    ) -> dict[str, Any] | None:
        """Load one retryable Work Map with its authoritative Process/session."""
        async with self.connection() as connection:
            result = await connection.execute(
                """
                SELECT
                    kd.id AS knowledge_document_id,
                    kd.structured_knowledge,
                    kd.evidence_cutoff,
                    kd.process_id,
                    ts.id AS training_session_id,
                    ts.conversation_id,
                    ts.raw_transcript,
                    p.title AS process_title,
                    p.description AS process_description
                FROM knowledge_documents kd
                JOIN training_sessions ts ON ts.id = kd.training_session_id
                JOIN processes p ON p.id = kd.process_id
                WHERE kd.id = %s
                  AND kd.process_id = ts.process_id
                  AND ts.status = 'completed'
                """,
                (knowledge_document_id,),
            )
            row = await result.fetchone()
            return dict(row) if row is not None else None

    async def set_graph_projection_status(
        self,
        knowledge_document_id: UUID,
        status: str,
        *,
        error: str | None = None,
    ) -> None:
        async with self.connection() as connection:
            await connection.execute(
                """
                UPDATE knowledge_documents
                SET graph_projection_status = %s,
                    graph_projection_attempts = graph_projection_attempts + 1,
                    graph_projection_error = %s,
                    graph_projected_at = CASE WHEN %s = 'projected' THEN NOW()
                                              ELSE graph_projected_at END,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (status, error, status, knowledge_document_id),
            )
            await connection.commit()

    async def create_knowledge_document(
        self,
        *,
        training_session_id: UUID,
        title: str,
        structured_knowledge: dict[str, Any],
        markdown: str,
        process_id: UUID | None = None,
        evidence_cutoff: Any | None = None,
        provenance_version: int = 1,
    ) -> UUID:
        async with self.connection() as connection:
            result = await connection.execute(
                """
                INSERT INTO knowledge_documents (
                    training_session_id,
                    title,
                    structured_knowledge,
                    markdown,
                    process_id,
                    evidence_cutoff,
                    provenance_version
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (training_session_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    structured_knowledge = EXCLUDED.structured_knowledge,
                    markdown = EXCLUDED.markdown,
                    process_id = EXCLUDED.process_id,
                    evidence_cutoff = EXCLUDED.evidence_cutoff,
                    provenance_version = EXCLUDED.provenance_version,
                    graph_projection_status = 'pending',
                    graph_projection_error = NULL,
                    updated_at = NOW()
                RETURNING id
                """,
                (
                    training_session_id,
                    title,
                    Jsonb(structured_knowledge),
                    markdown,
                    process_id,
                    evidence_cutoff,
                    provenance_version,
                ),
            )
            row = await result.fetchone()
            if row is None:
                raise RuntimeError("Knowledge document upsert returned no identity")
            await connection.commit()
            return row["id"]


def create_postgres_client() -> PostgresClient:
    return PostgresClient(settings.DATABASE_URL)
