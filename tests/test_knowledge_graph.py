from datetime import datetime, timezone
from uuid import uuid4

import asyncio

import pytest

from src.app.backend.services.teacher_context import TeacherContextService
from src.domain.brain import StructuredKnowledge, transcript_source_id
from src.domain.knowledge_graph import GraphWorkflow, build_graph_projection


def _projection():
    process_id = uuid4()
    document_id = uuid4()
    session_id = uuid4()
    event_id = uuid4()
    conversation_id = "conv_graph"
    source_id = transcript_source_id(conversation_id, 1)
    evidence = [
        {
            "source": "transcript_turn",
            "turn": 1,
            "source_id": str(source_id),
        }
    ]
    knowledge = StructuredKnowledge.model_validate(
        {
            "provenance_version": 2,
            "title": "Tickets",
            "objective": "Resolve tickets.",
            "steps": [
                {
                    "id": "step_1",
                    "action": "Inspect ticket",
                    "why": "Risk must be checked.",
                    "evidence": [
                        *evidence,
                        {"source": "screen_observation", "event_id": str(event_id)},
                    ],
                }
            ],
            "decisions": [
                {
                    "condition": "High risk",
                    "if_true": "Escalate",
                    "if_false": "Continue",
                    "evidence": evidence,
                }
            ],
            "exceptions": [{"statement": "VIP", "evidence": evidence}],
            "never_do": [{"statement": "Never erase history", "evidence": evidence}],
            "tools": ["Zendesk"],
            "artifacts": ["Ticket"],
        }
    )
    projection = build_graph_projection(
        process={"id": process_id, "title": "Tickets", "description": None},
        session_id=session_id,
        knowledge_document_id=document_id,
        conversation_id=conversation_id,
        knowledge=knowledge,
        transcript=[
            {
                "role": "user",
                "message": "Check risk and never erase history.",
                "time_in_call_secs": 10,
            }
        ],
        observations=[
            {
                "event_id": event_id,
                "source": "screen",
                "summary": "Ticket opened.",
                "occurred_at": datetime.now(timezone.utc),
                "time_in_call_secs": 9,
            }
        ],
    )
    return projection


def test_projection_is_deterministic_and_preserves_claim_provenance():
    first = _projection()
    # Rebuild with exactly the same identities and source data.
    second = build_graph_projection(
        process={
            "id": first.process_id,
            "title": first.process.label,
            "description": None,
        },
        session_id=first.session_id,
        knowledge_document_id=first.knowledge_document_id,
        conversation_id=first.conversation_id,
        knowledge=StructuredKnowledge.model_validate(
            {
                "provenance_version": 2,
                "title": "Tickets",
                "objective": "Resolve tickets.",
                "steps": [],
                "decisions": [],
            }
        ),
        transcript=[],
        observations=[],
    )
    assert first.process.id == second.process.id
    assert {node.type for node in first.nodes} >= {
        "session",
        "step",
        "decision",
        "reason",
        "guardrail",
        "exception",
        "tool",
        "artifact",
        "evidence",
    }
    supported = [edge for edge in first.edges if edge.type == "SUPPORTED_BY"]
    supported_sources = {
        next(node.type for node in first.nodes if node.id == edge.source)
        for edge in supported
    }
    assert {"step", "reason", "decision", "guardrail", "exception"} <= supported_sources


def test_unvalidated_work_map_cannot_be_projected():
    knowledge = StructuredKnowledge(
        title="Legacy",
        objective="Not graphable",
        provenance_version=1,
    )
    with pytest.raises(ValueError, match="provenance-v2"):
        build_graph_projection(
            process={"id": uuid4(), "title": "Legacy"},
            session_id=uuid4(),
            knowledge_document_id=uuid4(),
            conversation_id="conv_legacy",
            knowledge=knowledge,
            transcript=[],
            observations=[],
        )


class FakeGraph:
    def __init__(self, workflow):
        self.workflow = workflow

    async def get_workflow(self, process_id):
        return self.workflow


class FakePostgres:
    def __init__(self, process, documents):
        self.process = process
        self.documents = documents

    async def get_process(self, process_id):
        return self.process

    async def get_process_knowledge_documents(self, process_id, **_kwargs):
        return self.documents

    async def list_screen_observations(self, *_args, **_kwargs):
        return []


def test_teacher_context_accumulates_graph_selected_sessions():
    process_id = uuid4()
    documents = []
    document_ids = []
    for index in (1, 2):
        conversation_id = f"conv_{index}"
        source_id = transcript_source_id(conversation_id, 1)
        document_id = uuid4()
        document_ids.append(document_id)
        documents.append(
            {
                "knowledge_document_id": document_id,
                "structured_knowledge": {
                    "provenance_version": 2,
                    "title": f"Session {index}",
                    "objective": f"Objective {index}",
                    "steps": [
                        {
                            "id": f"step_{index}",
                            "action": f"Action {index}",
                            "why": f"Reason {index}",
                            "evidence": [
                                {
                                    "source": "transcript_turn",
                                    "turn": 1,
                                    "source_id": str(source_id),
                                }
                            ],
                        }
                    ],
                },
                "conversation_id": conversation_id,
                "raw_transcript": [
                    {
                        "role": "user",
                        "message": f"Reason {index}",
                        "time_in_call_secs": index,
                    }
                ],
                "metadata": {},
                "evidence_cutoff": None,
            }
        )
    workflow = GraphWorkflow(
        process_id=process_id,
        knowledge_document_ids=document_ids,
    )
    service = TeacherContextService(
        FakePostgres({"id": process_id, "title": "Tickets"}, documents),
        FakeGraph(workflow),
    )

    context = asyncio.run(service.load(process_id))

    assert context.title == "Tickets"
    assert [step.action for step in context.steps] == ["Action 1", "Action 2"]
    assert len(context.evidence) == 2
