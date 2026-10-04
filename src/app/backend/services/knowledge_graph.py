"""Projection and constrained retrieval for the Process knowledge graph."""

import logging
from uuid import UUID

from src.app.clients.neo4j import Neo4jClient
from src.app.clients.postgres import PostgresClient
from src.domain.brain import StructuredKnowledge
from src.domain.knowledge_graph import (
    GraphNode,
    GraphWorkflow,
    ProcessGraph,
    build_graph_projection,
)

logger = logging.getLogger(__name__)


class KnowledgeGraphService:
    def __init__(self, postgres: PostgresClient, neo4j: Neo4jClient) -> None:
        self.postgres = postgres
        self.neo4j = neo4j

    async def project_document(self, knowledge_document_id: UUID) -> bool:
        """Project one authoritative document; retain it in Postgres on failure."""
        try:
            source = await self.postgres.get_graph_projection_source(
                knowledge_document_id
            )
            if source is None:
                raise ValueError("Document is not a completed Process Work Map")
            knowledge = StructuredKnowledge.model_validate(
                source["structured_knowledge"]
            )
            observations = await self.postgres.list_screen_observations(
                source["conversation_id"],
                created_before=source.get("evidence_cutoff"),
            )
            projection = build_graph_projection(
                process={
                    "id": source["process_id"],
                    "title": source["process_title"],
                    "description": source["process_description"],
                },
                session_id=source["training_session_id"],
                knowledge_document_id=source["knowledge_document_id"],
                conversation_id=source["conversation_id"],
                knowledge=knowledge,
                transcript=source["raw_transcript"],
                observations=observations,
            )
            await self.neo4j.project(projection)
        except Exception as exc:
            await self.postgres.set_graph_projection_status(
                knowledge_document_id,
                "failed",
                error=str(exc)[:2_000],
            )
            logger.exception(
                "knowledge_graph_projection_failed knowledge_document_id=%s",
                knowledge_document_id,
            )
            return False

        await self.postgres.set_graph_projection_status(
            knowledge_document_id,
            "projected",
        )
        logger.info(
            "knowledge_graph_projection_completed knowledge_document_id=%s",
            knowledge_document_id,
        )
        return True

    async def retry_process(self, process_id: UUID) -> dict[str, int]:
        document_ids = await self.postgres.list_retryable_graph_document_ids(process_id)
        projected = 0
        for document_id in document_ids:
            projected += int(await self.project_document(document_id))
        return {"attempted": len(document_ids), "projected": projected}

    async def get_process_graph(self, process_id: UUID) -> ProcessGraph | None:
        return await self.neo4j.get_process_graph(process_id)

    async def get_workflow(self, process_id: UUID) -> GraphWorkflow | None:
        return await self.neo4j.get_workflow(process_id)

    async def get_guardrails(self, process_id: UUID) -> list[GraphNode]:
        return await self._nodes_of_type(process_id, "guardrail")

    async def get_decisions(self, process_id: UUID) -> list[GraphNode]:
        return await self._nodes_of_type(process_id, "decision")

    async def get_exceptions(self, process_id: UUID) -> list[GraphNode]:
        return await self._nodes_of_type(process_id, "exception")

    async def get_supporting_evidence(
        self,
        process_id: UUID,
        entity_id: str,
    ) -> list[GraphNode]:
        graph = await self.neo4j.get_process_graph(process_id)
        if graph is None or entity_id not in {node.id for node in graph.nodes}:
            return []
        evidence_ids = {
            edge.target
            for edge in graph.edges
            if edge.source == entity_id and edge.type == "SUPPORTED_BY"
        }
        return [
            node
            for node in graph.nodes
            if node.type == "evidence" and node.id in evidence_ids
        ]

    async def _nodes_of_type(
        self,
        process_id: UUID,
        node_type: str,
    ) -> list[GraphNode]:
        graph = await self.neo4j.get_process_graph(process_id)
        if graph is None:
            return []
        return [node for node in graph.nodes if node.type == node_type]
