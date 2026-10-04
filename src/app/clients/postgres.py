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

    async def get_current_process_knowledge(
        self,
        process_id: UUID,
    ) -> dict[str, Any] | None:
        """Return the newest completed document for one Process with its sources.

        Teacher v0 teaches a single document rather than merging several. The
        session's transcript and conversation ID travel with it so evidence
        references can be resolved without a second round trip. Ordering by
        ``updated_at`` means a re-distilled session supersedes its older form.
        """
        async with self.connection() as connection:
            result = await connection.execute(
                """
                SELECT
                    kd.id AS knowledge_document_id,
                    kd.structured_knowledge,
                    kd.updated_at,
                    ts.id AS training_session_id,
                    ts.conversation_id,
                    ts.raw_transcript
                FROM knowledge_documents kd
                JOIN training_sessions ts ON ts.id = kd.training_session_id
                WHERE kd.process_id = %s AND ts.status = 'completed'
                ORDER BY kd.updated_at DESC
                LIMIT 1
                """,
                (process_id,),
            )
            row = await result.fetchone()
            return dict(row) if row is not None else None

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
    ) -> bool:
        """Persist a meaningful observation once by its backend-issued event ID."""
        async with self.connection() as connection:
            result = await connection.execute(
                """
                INSERT INTO screen_observations (
                    event_id,
                    conversation_id,
                    screen_session_id,
                    previous_frame_id,
                    current_frame_id,
                    occurred_at,
                    change_score,
                    summary
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_id) DO NOTHING
                RETURNING event_id
                """,
                (
                    event_id,
                    conversation_id,
                    screen_session_id,
                    previous_frame_id,
                    current_frame_id,
                    occurred_at,
                    change_score,
                    summary,
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
    ) -> list[dict[str, Any]]:
        """Return textual observations in their source-event order."""
        async with self.connection() as connection:
            result = await connection.execute(
                """
                SELECT event_id, occurred_at, summary
                FROM screen_observations
                WHERE conversation_id = %s
                ORDER BY occurred_at, created_at, event_id
                """,
                (conversation_id,),
            )
            return [dict(row) async for row in result]

    async def create_knowledge_document(
        self,
        *,
        training_session_id: UUID,
        title: str,
        structured_knowledge: dict[str, Any],
        markdown: str,
        process_id: UUID | None = None,
    ) -> None:
        async with self.connection() as connection:
            await connection.execute(
                """
                INSERT INTO knowledge_documents (
                    training_session_id,
                    title,
                    structured_knowledge,
                    markdown,
                    process_id
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (training_session_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    structured_knowledge = EXCLUDED.structured_knowledge,
                    markdown = EXCLUDED.markdown,
                    process_id = EXCLUDED.process_id,
                    updated_at = NOW()
                """,
                (
                    training_session_id,
                    title,
                    Jsonb(structured_knowledge),
                    markdown,
                    process_id,
                ),
            )
            await connection.commit()


def create_postgres_client() -> PostgresClient:
    return PostgresClient(settings.DATABASE_URL)
