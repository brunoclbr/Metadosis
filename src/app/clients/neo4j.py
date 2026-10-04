"""Lifecycle-owned Neo4j Aura adapter for the Metadosis knowledge graph."""

from collections import defaultdict
from typing import Any
from uuid import UUID

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncManagedTransaction

from src.config import settings
from src.domain.knowledge_graph import GraphProjection, ProcessGraph, GraphWorkflow

LABELS = {
    "process": "Process",
    "session": "Session",
    "step": "Step",
    "decision": "Decision",
    "reason": "Reason",
    "guardrail": "Guardrail",
    "exception": "Exception",
    "tool": "Tool",
    "artifact": "Artifact",
    "evidence": "Evidence",
}
RELATIONSHIPS = {
    "HAS_STEP",
    "LEARNED_FROM",
    "CONTRIBUTED",
    "HAS_DECISION",
    "HAS_REASON",
    "HAS_GUARDRAIL",
    "HAS_EXCEPTION",
    "USES",
    "USES_ARTIFACT",
    "SUPPORTED_BY",
    "FROM_SESSION",
}


class Neo4jClient:
    def __init__(self, uri: str, username: str, password: str, database: str) -> None:
        self.database = database
        self.driver: AsyncDriver = AsyncGraphDatabase.driver(
            uri,
            auth=(username, password),
        )

    async def initialize(self) -> None:
        await self.driver.verify_connectivity()
        async with self.driver.session(database=self.database) as session:
            for node_type, label in LABELS.items():
                constraint = await session.run(
                    f"CREATE CONSTRAINT metadosis_{node_type}_id_unique IF NOT EXISTS "
                    f"FOR (n:{label}) REQUIRE n.id IS UNIQUE"
                )
                await constraint.consume()
                index = await session.run(
                    f"CREATE INDEX metadosis_{node_type}_process_id IF NOT EXISTS "
                    f"FOR (n:{label}) ON (n.process_id)"
                )
                await index.consume()

    async def close(self) -> None:
        await self.driver.close()

    async def project(self, projection: GraphProjection) -> None:
        payload = projection.model_dump(mode="json")
        async with self.driver.session(database=self.database) as session:
            await session.execute_write(self._project_transaction, payload)

    @staticmethod
    async def _project_transaction(
        transaction: AsyncManagedTransaction,
        projection: dict[str, Any],
    ) -> None:
        process_id = str(projection["process_id"])
        all_nodes = [projection["process"], *projection["nodes"]]
        identifiers = [node["id"] for node in all_nodes]
        conflict = await transaction.run(
            """
            MATCH (n)
            WHERE n.id IN $ids AND n.process_id IS NOT NULL
              AND n.process_id <> $process_id
            RETURN n.id AS id LIMIT 1
            """,
            ids=identifiers,
            process_id=process_id,
        )
        if await conflict.single() is not None:
            raise ValueError("A graph identity is already owned by another Process")

        grouped_nodes: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for node in all_nodes:
            grouped_nodes[node["type"]].append(
                {
                    "id": node["id"],
                    "label": node["label"],
                    "properties": {
                        key: value
                        for key, value in node.get("properties", {}).items()
                        if value is not None
                    },
                }
            )
        for node_type, nodes in grouped_nodes.items():
            label = LABELS[node_type]
            await transaction.run(
                f"""
                UNWIND $nodes AS row
                MERGE (n:{label} {{id: row.id}})
                ON CREATE SET n.process_id = $process_id
                SET n.label = row.label, n += row.properties
                """,
                nodes=nodes,
                process_id=process_id,
            )

        grouped_edges: dict[str, list[dict[str, str]]] = defaultdict(list)
        for edge in projection["edges"]:
            if edge["type"] not in RELATIONSHIPS:
                raise ValueError(f"Unsupported graph relationship {edge['type']}")
            grouped_edges[edge["type"]].append(edge)
        for relationship, edges in grouped_edges.items():
            await transaction.run(
                f"""
                UNWIND $edges AS row
                MATCH (source {{id: row.source, process_id: $process_id}})
                MATCH (target {{id: row.target, process_id: $process_id}})
                MERGE (source)-[:{relationship}]->(target)
                """,
                edges=edges,
                process_id=process_id,
            )

    async def get_process_graph(self, process_id: UUID) -> ProcessGraph | None:
        process_value = str(process_id)
        async with self.driver.session(database=self.database) as session:
            process_result = await session.run(
                """
                MATCH (p:Process {id: $process_id, process_id: $process_id})
                RETURN p.id AS id, p.label AS label, properties(p) AS properties
                """,
                process_id=process_value,
            )
            process_record = await process_result.single()
            if process_record is None:
                return None
            node_result = await session.run(
                """
                MATCH (n {process_id: $process_id})
                WHERE NOT n:Process
                RETURN n.id AS id, labels(n)[0] AS type, n.label AS label,
                       properties(n) AS properties
                ORDER BY type, id
                """,
                process_id=process_value,
            )
            edge_result = await session.run(
                """
                MATCH (source {process_id: $process_id})-[r]->
                      (target {process_id: $process_id})
                RETURN source.id AS source, target.id AS target, type(r) AS type
                ORDER BY type, source, target
                """,
                process_id=process_value,
            )
            nodes = [
                {
                    "id": record["id"],
                    "type": str(record["type"]).lower(),
                    "label": record["label"],
                    "properties": {
                        key: value
                        for key, value in dict(record["properties"]).items()
                        if key not in {"id", "label", "process_id"}
                    },
                }
                async for record in node_result
            ]
            edges = [dict(record) async for record in edge_result]
            properties = dict(process_record["properties"])
            return ProcessGraph.model_validate(
                {
                    "process": {
                        "id": process_record["id"],
                        "type": "process",
                        "label": process_record["label"],
                        "properties": {
                            key: value
                            for key, value in properties.items()
                            if key not in {"id", "label", "process_id"}
                        },
                    },
                    "nodes": nodes,
                    "edges": edges,
                }
            )

    async def get_workflow(self, process_id: UUID) -> GraphWorkflow | None:
        graph = await self.get_process_graph(process_id)
        if graph is None:
            return None
        sessions = [node for node in graph.nodes if node.type == "session"]
        return GraphWorkflow(
            process_id=process_id,
            knowledge_document_ids=[
                UUID(str(node.properties["knowledge_document_id"]))
                for node in sessions
            ],
            entity_ids=[
                node.id
                for node in graph.nodes
                if node.type not in {"session", "evidence"}
            ],
            evidence_ids=[
                node.id for node in graph.nodes if node.type == "evidence"
            ],
        )


def create_neo4j_client() -> Neo4jClient | None:
    configured = (
        settings.NEO4J_URI,
        settings.NEO4J_USERNAME,
        settings.NEO4J_PASSWORD,
    )
    if not all(configured):
        return None
    return Neo4jClient(
        settings.NEO4J_URI,
        settings.NEO4J_USERNAME,
        settings.NEO4J_PASSWORD,
        settings.NEO4J_DATABASE,
    )
