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

    async def create_training_session(
        self,
        *,
        conversation_id: str,
        transcript: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> tuple[UUID, bool]:
        """Insert once by conversation ID and return ``(id, was_created)``."""
        async with self.connection() as connection:
            result = await connection.execute(
                """
                INSERT INTO training_sessions (
                    conversation_id, status, raw_transcript, metadata
                )
                VALUES (%s, 'received', %s, %s)
                ON CONFLICT (conversation_id) DO NOTHING
                RETURNING id
                """,
                (conversation_id, Jsonb(transcript), Jsonb(metadata)),
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

    async def create_knowledge_document(
        self,
        *,
        training_session_id: UUID,
        title: str,
        structured_knowledge: dict[str, Any],
        markdown: str,
    ) -> None:
        async with self.connection() as connection:
            await connection.execute(
                """
                INSERT INTO knowledge_documents (
                    training_session_id, title, structured_knowledge, markdown
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (training_session_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    structured_knowledge = EXCLUDED.structured_knowledge,
                    markdown = EXCLUDED.markdown,
                    updated_at = NOW()
                """,
                (
                    training_session_id,
                    title,
                    Jsonb(structured_knowledge),
                    markdown,
                ),
            )
            await connection.commit()


def create_postgres_client() -> PostgresClient:
    return PostgresClient(settings.DATABASE_URL)
