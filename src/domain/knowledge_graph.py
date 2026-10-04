"""Deterministic projection contracts for the Process-isolated Knowledge Brain."""

from typing import Any, Literal
from uuid import UUID, NAMESPACE_URL, uuid5

from pydantic import BaseModel, Field

from src.domain.brain import (
    KnowledgeClaim,
    StructuredKnowledge,
    TranscriptTurnEvidence,
    validate_evidence_references,
)

GraphNodeType = Literal[
    "process",
    "session",
    "step",
    "decision",
    "reason",
    "guardrail",
    "exception",
    "tool",
    "artifact",
    "evidence",
]


class GraphNode(BaseModel):
    id: str
    type: GraphNodeType
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str


class ProcessGraph(BaseModel):
    process: GraphNode
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


class GraphProjection(ProcessGraph):
    process_id: UUID
    session_id: UUID
    knowledge_document_id: UUID
    conversation_id: str


class GraphWorkflow(BaseModel):
    process_id: UUID
    knowledge_document_ids: list[UUID] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)

    @property
    def vector_scope(self) -> dict[str, Any]:
        """The graph-first scope a future pgvector retriever can consume."""
        return {
            "process_id": str(self.process_id),
            "entity_ids": self.entity_ids,
            "evidence_ids": self.evidence_ids,
        }


def graph_entity_id(
    process_id: UUID,
    knowledge_document_id: UUID,
    entity_type: str,
    local_id: str,
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"metadosis:{process_id}:{knowledge_document_id}:{entity_type}:{local_id}",
        )
    )


def build_graph_projection(
    *,
    process: dict[str, Any],
    session_id: UUID,
    knowledge_document_id: UUID,
    conversation_id: str,
    knowledge: StructuredKnowledge,
    transcript: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> GraphProjection:
    """Convert only a provenance-valid Work Map into deterministic graph data."""
    if knowledge.provenance_version != 2:
        raise ValueError("Only provenance-v2 Work Maps can enter the knowledge graph")
    validate_evidence_references(
        knowledge,
        transcript,
        observations,
        conversation_id=conversation_id,
    )

    process_id = UUID(str(process["id"]))
    process_node = GraphNode(
        id=str(process_id),
        type="process",
        label=str(process["title"]),
        properties={"description": process.get("description") or ""},
    )
    session_node = GraphNode(
        id=str(session_id),
        type="session",
        label=conversation_id,
        properties={
            "conversation_id": conversation_id,
            "knowledge_document_id": str(knowledge_document_id),
        },
    )
    nodes: list[GraphNode] = [session_node]
    edges = [GraphEdge(source=process_node.id, target=session_node.id, type="LEARNED_FROM")]

    observation_by_id = {str(item["event_id"]): item for item in observations}
    transcript_by_turn = {
        index: item for index, item in enumerate(transcript, start=1)
    }
    evidence_nodes: dict[str, GraphNode] = {}

    def evidence_id(reference: Any) -> str:
        if isinstance(reference, TranscriptTurnEvidence):
            if reference.source_id is None:
                raise ValueError("Graph transcript evidence requires a stable source_id")
            identifier = str(reference.source_id)
            source = transcript_by_turn[reference.turn]
            properties = {
                "source_type": "transcript_turn",
                "conversation_id": conversation_id,
                "turn": reference.turn,
                "time_in_call_secs": source.get("time_in_call_secs"),
            }
        else:
            identifier = str(reference.event_id)
            source = observation_by_id[identifier]
            properties = {
                "source_type": reference.source,
                "conversation_id": conversation_id,
                "time_in_call_secs": source.get("time_in_call_secs"),
            }
        evidence_nodes.setdefault(
            identifier,
            GraphNode(
                id=identifier,
                type="evidence",
                label=str(properties["source_type"]),
                properties=properties,
            ),
        )
        return identifier

    def add_entity(
        entity_type: GraphNodeType,
        local_id: str,
        label: str,
        relationship: str,
        evidence: list[Any] | None = None,
        *,
        parent: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> str:
        identifier = graph_entity_id(
            process_id, knowledge_document_id, entity_type, local_id
        )
        nodes.append(
            GraphNode(
                id=identifier,
                type=entity_type,
                label=label,
                properties={
                    "knowledge_document_id": str(knowledge_document_id),
                    **(properties or {}),
                },
            )
        )
        edges.append(
            GraphEdge(
                source=parent or process_node.id,
                target=identifier,
                type=relationship,
            )
        )
        edges.append(
            GraphEdge(source=session_node.id, target=identifier, type="CONTRIBUTED")
        )
        for reference in evidence or []:
            edges.append(
                GraphEdge(
                    source=identifier,
                    target=evidence_id(reference),
                    type="SUPPORTED_BY",
                )
            )
        return identifier

    for index, step in enumerate(knowledge.steps, start=1):
        step_id = add_entity(
            "step",
            step.id,
            step.action,
            "HAS_STEP",
            step.evidence,
            properties={"order": index, "local_id": step.id},
        )
        if step.why.strip():
            add_entity(
                "reason",
                f"{step.id}:reason",
                step.why,
                "HAS_REASON",
                step.evidence,
                parent=step_id,
            )

    for index, decision in enumerate(knowledge.decisions, start=1):
        add_entity(
            "decision",
            str(index),
            decision.condition,
            "HAS_DECISION",
            decision.evidence,
            properties={"if_true": decision.if_true, "if_false": decision.if_false},
        )

    for entity_type, relationship, claims in (
        ("exception", "HAS_EXCEPTION", knowledge.exceptions),
        ("guardrail", "HAS_GUARDRAIL", knowledge.never_do),
    ):
        for index, claim in enumerate(claims, start=1):
            if not isinstance(claim, KnowledgeClaim):
                raise ValueError(f"Graph {entity_type} requires claim-level provenance")
            add_entity(
                entity_type,
                str(index),
                claim.statement,
                relationship,
                claim.evidence,
            )

    for index, tool in enumerate(knowledge.tools, start=1):
        add_entity("tool", str(index), tool, "USES")
    for index, artifact in enumerate(knowledge.artifacts, start=1):
        add_entity("artifact", str(index), artifact, "USES_ARTIFACT")

    nodes.extend(evidence_nodes.values())
    edges.extend(
        GraphEdge(source=evidence.id, target=session_node.id, type="FROM_SESSION")
        for evidence in evidence_nodes.values()
    )
    return GraphProjection(
        process=process_node,
        nodes=nodes,
        edges=edges,
        process_id=process_id,
        session_id=session_id,
        knowledge_document_id=knowledge_document_id,
        conversation_id=conversation_id,
    )
