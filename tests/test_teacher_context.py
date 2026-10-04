"""Focused tests for the Teacher v0 read path."""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.backend.api.routers import brain as brain_router
from src.app.backend.services.teacher_context import (
    ProcessNotFoundError,
    ProcessNotTeachableError,
    TeacherContextService,
)
from src.domain.brain import build_teacher_context, StructuredKnowledge


def _knowledge(event_id):
    return {
        "title": "Ticket handling",
        "objective": "Resolve a customer ticket without breaking policy.",
        "steps": [
            {
                "id": "step_1",
                "action": "Open the ticket queue",
                "why": "Oldest tickets breach SLA first.",
                "evidence": [{"source": "transcript_turn", "turn": 2}],
            },
            {
                "id": "step_2",
                "action": "Check the account tier",
                "why": "Enterprise tickets escalate immediately.",
                "evidence": [
                    {"source": "transcript_turn", "turn": 2},
                    {"source": "screen_observation", "event_id": str(event_id)},
                ],
            },
        ],
        "decisions": [
            {
                "condition": "The account is enterprise",
                "if_true": "Escalate to the on-call lead",
                "if_false": "Handle it in the normal queue",
            }
        ],
        "exceptions": ["Billing disputes always go to finance."],
        "never_do": ["Never close a ticket without a written reason."],
        "tools": ["Zendesk"],
        "artifacts": ["Resolved ticket"],
    }


class FakePostgres:
    """Only the four reads the teacher path performs."""

    def __init__(self, *, process=None, current=None, observations=None):
        self._process = process
        self._current = current
        self._observations = observations or []

    async def get_process(self, process_id):
        return self._process

    async def get_current_process_knowledge(self, process_id):
        return self._current

    async def list_screen_observations(self, conversation_id):
        return self._observations


def _transcript():
    return [
        {"role": "agent", "message": ""},
        {"role": "user", "message": "I always start from the oldest ticket."},
        {"role": "agent", "message": "Why does the tier matter?"},
    ]


def test_build_teacher_context_resolves_only_cited_evidence():
    event_id = uuid4()
    knowledge = StructuredKnowledge.model_validate(_knowledge(event_id))
    observations = [
        {
            "event_id": event_id,
            "occurred_at": datetime.now(timezone.utc),
            "summary": "The expert opened the account tier panel.",
            "source": "screen",
        },
        {
            "event_id": uuid4(),
            "occurred_at": datetime.now(timezone.utc),
            "summary": "An unrelated window gained focus.",
            "source": "screen",
        },
    ]
    process_id = uuid4()

    context = build_teacher_context(
        process_id=process_id,
        knowledge=knowledge,
        transcript=_transcript(),
        observations=observations,
    )

    assert context.process_id == process_id
    assert context.title == "Ticket handling"
    # turn_2 is cited twice but resolved once; the uncited observation is absent.
    assert [item.id for item in context.evidence] == ["turn_2", str(event_id)]
    transcript_evidence = context.evidence[0]
    assert transcript_evidence.type == "transcript"
    assert transcript_evidence.speaker == "user"
    assert transcript_evidence.content == "I always start from the oldest ticket."
    assert context.evidence[1].type == "screen_observation"
    assert context.evidence[1].speaker is None


def test_camera_evidence_is_resolved_as_a_camera_observation():
    """The tutor must know a cited source was a physical action, not a screen."""
    event_id = uuid4()
    knowledge = StructuredKnowledge.model_validate(
        {
            "title": "Replace a bicycle wheel",
            "objective": "Swap a rear wheel without damaging the drivetrain.",
            "steps": [
                {
                    "id": "step_1",
                    "action": "Release the brake before pulling the wheel",
                    "why": "The pads catch the rim and bend it otherwise.",
                    "evidence": [
                        {"source": "camera_observation", "event_id": str(event_id)}
                    ],
                }
            ],
        }
    )

    context = build_teacher_context(
        process_id=uuid4(),
        knowledge=knowledge,
        transcript=_transcript(),
        observations=[
            {
                "event_id": event_id,
                "occurred_at": datetime.now(timezone.utc),
                "summary": "The user squeezed the brake arms and unhooked the cable.",
                "source": "camera",
            }
        ],
    )

    assert [item.type for item in context.evidence] == ["camera_observation"]
    assert context.evidence[0].content == (
        "The user squeezed the brake arms and unhooked the cable."
    )


def test_stored_source_overrides_a_miscited_evidence_tag():
    """The row is authoritative: a camera event stays camera even if miscited."""
    event_id = uuid4()
    knowledge = StructuredKnowledge.model_validate(
        {
            "title": "T",
            "objective": "O",
            "steps": [
                {
                    "id": "step_1",
                    "action": "A",
                    "why": "W",
                    # The distiller filed a camera event under the screen tag.
                    "evidence": [
                        {"source": "screen_observation", "event_id": str(event_id)}
                    ],
                }
            ],
        }
    )

    context = build_teacher_context(
        process_id=uuid4(),
        knowledge=knowledge,
        transcript=_transcript(),
        observations=[
            {
                "event_id": event_id,
                "occurred_at": datetime.now(timezone.utc),
                "summary": "The user lifted the wheel clear of the frame.",
                "source": "camera",
            }
        ],
    )

    assert context.evidence[0].type == "camera_observation"


def test_build_teacher_context_drops_unresolvable_references():
    """A missing source must not become invented evidence."""
    knowledge = StructuredKnowledge.model_validate(_knowledge(uuid4()))

    context = build_teacher_context(
        process_id=uuid4(),
        knowledge=knowledge,
        transcript=_transcript(),
        observations=[],
    )

    assert [item.id for item in context.evidence] == ["turn_2"]
    # The step itself survives with its reasoning intact.
    assert len(context.steps) == 2


def test_evidence_turn_numbering_matches_the_distiller_enumeration():
    """Blank turns are skipped identically on the write and read sides."""
    knowledge = StructuredKnowledge.model_validate(
        {
            "title": "T",
            "objective": "O",
            "steps": [
                {
                    "id": "step_1",
                    "action": "A",
                    "why": "W",
                    "evidence": [{"source": "transcript_turn", "turn": 1}],
                }
            ],
        }
    )

    context = build_teacher_context(
        process_id=uuid4(),
        knowledge=knowledge,
        transcript=[{"role": "agent", "message": "   "}, {"role": "user", "message": "x"}],
        observations=[],
    )

    # Turn 1 is the blank agent line, which carries no text to quote.
    assert context.evidence == []


def test_missing_process_is_distinguished_from_untrained_process():
    service = TeacherContextService(FakePostgres(process=None))
    with pytest.raises(ProcessNotFoundError):
        asyncio.run(service.load(uuid4()))


def test_process_without_completed_training_is_not_teachable():
    service = TeacherContextService(
        FakePostgres(process={"id": uuid4(), "title": "Ticket handling"}, current=None)
    )
    with pytest.raises(ProcessNotTeachableError):
        asyncio.run(service.load(uuid4()))


def test_pre_provenance_document_is_reported_as_not_teachable():
    """Old free-text evidence is never repaired by inventing references."""
    legacy = {
        "title": "Old",
        "objective": "O",
        "steps": [
            {
                "id": "step_1",
                "action": "A",
                "why": "W",
                "evidence": ["the expert said so"],
            }
        ],
    }
    service = TeacherContextService(
        FakePostgres(
            process={"id": uuid4(), "title": "Old"},
            current={
                "knowledge_document_id": uuid4(),
                "structured_knowledge": legacy,
                "conversation_id": "conv_legacy",
                "raw_transcript": _transcript(),
            },
        )
    )
    with pytest.raises(ProcessNotTeachableError):
        asyncio.run(service.load(uuid4()))


def test_teacher_context_is_served_for_a_trained_process():
    event_id = uuid4()
    process_id = uuid4()
    service = TeacherContextService(
        FakePostgres(
            process={"id": process_id, "title": "Ticket handling"},
            current={
                "knowledge_document_id": uuid4(),
                "structured_knowledge": _knowledge(event_id),
                "conversation_id": "conv_ok",
                "raw_transcript": _transcript(),
            },
            observations=[
                {
                    "event_id": event_id,
                    "occurred_at": datetime.now(timezone.utc),
                    "summary": "The expert opened the account tier panel.",
                    "source": "screen",
                }
            ],
        )
    )

    context = asyncio.run(service.load(process_id))

    assert context.process_id == process_id
    assert context.never_do == ["Never close a ticket without a written reason."]
    assert len(context.evidence) == 2


def _app(service):
    app = FastAPI()
    app.state.teacher_context = service
    app.include_router(brain_router.router)
    return app


def test_untrained_process_returns_409_not_404():
    """The tutor must be able to tell 'no such process' from 'not trained yet'."""
    service = TeacherContextService(
        FakePostgres(process={"id": uuid4(), "title": "Empty"}, current=None)
    )
    with TestClient(_app(service)) as client:
        response = client.get(f"/brain/processes/{uuid4()}/teacher-context")

    assert response.status_code == 409
    assert "has not established" in response.json()["detail"]


def test_unknown_process_returns_404():
    service = TeacherContextService(FakePostgres(process=None))
    with TestClient(_app(service)) as client:
        response = client.get(f"/brain/processes/{uuid4()}/teacher-context")

    assert response.status_code == 404


def test_invalid_process_id_is_rejected_before_the_service_runs():
    service = TeacherContextService(FakePostgres(process=None))
    with TestClient(_app(service)) as client:
        response = client.get("/brain/processes/not-a-uuid/teacher-context")

    assert response.status_code == 422


def test_teacher_context_requires_the_tool_secret_when_configured(monkeypatch):
    """Captured expertise must not be readable with only a Process UUID."""
    monkeypatch.setattr(
        brain_router.settings,
        "TEACHER_CONTEXT_SECRET",
        "shared-tool-secret",
        raising=False,
    )
    service = TeacherContextService(FakePostgres(process=None))
    process_id = uuid4()

    with TestClient(_app(service)) as client:
        missing = client.get(f"/brain/processes/{process_id}/teacher-context")
        wrong = client.get(
            f"/brain/processes/{process_id}/teacher-context",
            headers={"X-Metadosis-Tool-Secret": "guess"},
        )
        correct = client.get(
            f"/brain/processes/{process_id}/teacher-context",
            headers={"X-Metadosis-Tool-Secret": "shared-tool-secret"},
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    # Authorized, so the request reaches the service and gets its real answer.
    assert correct.status_code == 404


def test_teacher_context_stays_open_until_a_secret_is_configured(monkeypatch):
    """Backend and agent config are published separately; neither may break the other."""
    monkeypatch.setattr(
        brain_router.settings, "TEACHER_CONTEXT_SECRET", None, raising=False
    )
    service = TeacherContextService(FakePostgres(process=None))

    with TestClient(_app(service)) as client:
        response = client.get(f"/brain/processes/{uuid4()}/teacher-context")

    assert response.status_code == 404
