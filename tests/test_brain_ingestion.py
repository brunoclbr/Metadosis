import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.backend.api.routers import webhooks
from src.app.backend.services import brain_ingestion as brain_ingestion_module
from src.app.backend.services.brain_ingestion import BrainIngestionService
from src.domain.brain import (
    KnowledgeDecision,
    KnowledgeStep,
    VisualObservationEvidence,
    StructuredKnowledge,
    TranscriptTurnEvidence,
    render_knowledge_markdown,
    transcript_as_text,
    transcript_source_id,
    validate_evidence_references,
)


class FakeBrain:
    def __init__(self) -> None:
        self.session_id = uuid4()
        self.conversations: set[str] = set()
        self.distilled: list[str] = []
        self.accepted_process_ids: list[object] = []
        self.distilled_process_ids: list[object] = []
        self.distilled_metadata: list[dict] = []
        self.skipped: list[object] = []

    async def accept_session(
        self, *, conversation_id, transcript, metadata, process_id=None
    ):
        created = conversation_id not in self.conversations
        self.conversations.add(conversation_id)
        self.accepted_process_ids.append(process_id)
        return self.session_id, created

    async def skip_distillation(self, session_id):
        self.skipped.append(session_id)

    async def distill_session(
        self, session_id, conversation_id, transcript, metadata, process_id=None
    ):
        await asyncio.sleep(0)
        self.distilled.append(conversation_id)
        self.distilled_metadata.append(metadata)
        self.distilled_process_ids.append(process_id)


class FakeWebhooks:
    def construct_event(self, **_kwargs):
        raise AssertionError("signature verification is disabled in this test")


def _app(brain: FakeBrain) -> FastAPI:
    app = FastAPI()
    app.state.brain = brain
    app.state.elevenlabs_client = SimpleNamespace(webhooks=FakeWebhooks())
    app.include_router(webhooks.router)
    return app


def test_post_call_is_idempotent_and_schedules_distillation_once(monkeypatch):
    monkeypatch.setattr(webhooks.settings, "ELEVENLABS_WEBHOOK_SECRET", None)
    brain = FakeBrain()
    payload = {
        "type": "post_call_transcription",
        "event_timestamp": 1739537297,
        "data": {
            "conversation_id": "conv_123",
            "agent_id": "agent_123",
            "status": "done",
            "transcript": [
                {"role": "agent", "message": "Why do you check the seal?"},
                {"role": "user", "message": "To prevent leaks."},
            ],
            "metadata": {
                "call_duration_secs": 42,
                "start_time_unix_secs": 1_739_537_255,
            },
        },
    }

    with TestClient(_app(brain)) as client:
        first = client.post("/webhooks/elevenlabs/post-call", json=payload)
        duplicate = client.post("/webhooks/elevenlabs/post-call", json=payload)

    assert first.status_code == 200
    assert first.json()["status"] == "accepted"
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "duplicate"
    assert brain.distilled == ["conv_123"]
    assert brain.distilled_metadata[0]["start_time_unix_secs"] == 1_739_537_255.0


def test_markdown_is_deterministically_rendered_from_structured_knowledge():
    knowledge = StructuredKnowledge(
        title="Inspect a seal",
        objective="Prevent leaks.",
        steps=[
            KnowledgeStep(
                id="step_1",
                action="Inspect the seal",
                why="Damage can cause leaks.",
                evidence=[
                    TranscriptTurnEvidence(source="transcript_turn", turn=2),
                    VisualObservationEvidence(
                        source="screen_observation",
                        event_id="12345678-1234-4234-8234-123456789abc",
                    ),
                ],
            )
        ],
        decisions=[
            KnowledgeDecision(
                condition="The seal is damaged",
                if_true="Replace it",
                if_false="Continue",
            )
        ],
        never_do=["Reuse a damaged seal"],
    )

    markdown = render_knowledge_markdown(knowledge)

    assert markdown.startswith("# Inspect a seal\n")
    assert "**Why:** Damage can cause leaks." in markdown
    assert "- Transcript turn 2" in markdown
    assert (
        "- Screen observation `12345678-1234-4234-8234-123456789abc`"
        in markdown
    )
    assert "**If true:** Replace it" in markdown
    assert "- Reuse a damaged seal" in markdown


def test_transcript_turns_preserve_original_source_positions():
    transcript = [
        {"role": "agent", "message": "First"},
        {"role": "user", "message": ""},
        {"role": "user", "message": "Third"},
    ]

    assert transcript_as_text(transcript) == (
        "turn_1 | agent: First\nturn_3 | user: Third"
    )


class FakeStructuredModel:
    def __init__(self, knowledge: StructuredKnowledge) -> None:
        self.knowledge = knowledge
        self.messages = []

    def with_structured_output(self, *_args, **_kwargs):
        return self

    async def ainvoke(self, messages):
        self.messages = messages
        return self.knowledge


class FakePostgres:
    def __init__(self, observations):
        self.observations = observations
        self.statuses = []
        self.document = None

    async def set_training_session_status(self, session_id, status):
        self.statuses.append((session_id, status))

    async def list_screen_observations(self, conversation_id, *, created_before=None):
        self.observation_conversation_id = conversation_id
        self.created_before = created_before
        return self.observations

    async def create_knowledge_document(self, **document):
        self.document = document


def test_distillation_uses_observations_and_validates_evidence():
    session_id = uuid4()
    event_id = uuid4()
    transcript = [
        {
            "role": "user",
            "message": "Place a blue circle.",
            "time_in_call_secs": 12.5,
        }
    ]
    observations = [
        {
            "event_id": event_id,
            "occurred_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
            "summary": "A blue circle appeared on the canvas.",
            "source": "screen",
        }
    ]
    knowledge = StructuredKnowledge(
        provenance_version=2,
        title="Canvas exercise",
        objective="Place a shape.",
        steps=[
            KnowledgeStep(
                id="step_1",
                action="Place a blue circle",
                why="The trainer requested it.",
                evidence=[
                    TranscriptTurnEvidence(
                        source="transcript_turn",
                        turn=1,
                        source_id=transcript_source_id("conv_sources", 1),
                    ),
                    VisualObservationEvidence(
                        source="screen_observation",
                        event_id=event_id,
                    ),
                ],
            )
        ],
    )
    postgres = FakePostgres(observations)
    model = FakeStructuredModel(knowledge)
    service = BrainIngestionService(postgres, model)

    asyncio.run(
        service.distill_session(
            session_id,
            "conv_sources",
            transcript,
            {"start_time_unix_secs": 1_735_000_000},
        )
    )

    assert postgres.statuses == [
        (session_id, "processing"),
        (session_id, "completed"),
    ]
    assert postgres.observation_conversation_id == "conv_sources"
    assert str(event_id) in model.messages[1].content
    source_id = str(transcript_source_id("conv_sources", 1))
    assert f"transcript_turn {source_id} | turn_1 | at 00:12" in model.messages[1].content
    assert postgres.created_before is not None
    assert postgres.document["provenance_version"] == 2
    assert postgres.document["structured_knowledge"]["steps"][0]["evidence"] == [
        {"source": "transcript_turn", "turn": 1, "source_id": source_id},
        {"source": "screen_observation", "event_id": str(event_id)},
    ]


def test_camera_observations_become_cited_evidence():
    """A physical demonstration must be distillable into an evidence-backed step."""
    session_id = uuid4()
    camera_event_id = uuid4()
    screen_event_id = uuid4()
    transcript = [
        {
            "role": "user",
            "message": "I always release the brake before pulling the wheel.",
            "time_in_call_secs": 4,
        }
    ]
    observations = [
        {
            "event_id": screen_event_id,
            "occurred_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
            "summary": "The maintenance log opened.",
            "source": "screen",
        },
        {
            "event_id": camera_event_id,
            "occurred_at": datetime(2026, 1, 2, 0, 1, tzinfo=timezone.utc),
            "summary": "The user unhooked the brake cable, then lifted the wheel out.",
            "source": "camera",
        },
    ]
    knowledge = StructuredKnowledge(
        provenance_version=2,
        title="Replace a bicycle wheel",
        objective="Remove a rear wheel without bending the rim.",
        steps=[
            KnowledgeStep(
                id="step_1",
                action="Release the brake before pulling the wheel out",
                why="The pads catch the rim and bend it otherwise.",
                evidence=[
                    TranscriptTurnEvidence(
                        source="transcript_turn",
                        turn=1,
                        source_id=transcript_source_id("conv_camera", 1),
                    ),
                    VisualObservationEvidence(
                        source="camera_observation",
                        event_id=camera_event_id,
                    ),
                ],
            )
        ],
    )
    postgres = FakePostgres(observations)
    model = FakeStructuredModel(knowledge)
    service = BrainIngestionService(postgres, model)

    asyncio.run(service.distill_session(session_id, "conv_camera", transcript, {}))

    assert postgres.statuses == [
        (session_id, "processing"),
        (session_id, "completed"),
    ]
    # Each observation is offered to the model under the tag it must cite.
    prompt = model.messages[1].content
    assert f"camera_observation {camera_event_id}" in prompt
    assert f"screen_observation {screen_event_id}" in prompt
    assert postgres.document["structured_knowledge"]["steps"][0]["evidence"] == [
        {
            "source": "transcript_turn",
            "turn": 1,
            "source_id": str(transcript_source_id("conv_camera", 1)),
        },
        {"source": "camera_observation", "event_id": str(camera_event_id)},
    ]


def test_distillation_rejects_a_camera_reference_to_a_missing_event():
    """A camera tag is not a licence to invent an event ID."""
    session_id = uuid4()
    knowledge = StructuredKnowledge(
        title="Invalid",
        objective="Reject fabricated camera evidence.",
        steps=[
            KnowledgeStep(
                id="step_1",
                action="Invent a physical action",
                why="Unsupported",
                evidence=[
                    VisualObservationEvidence(
                        source="camera_observation",
                        event_id=uuid4(),
                    )
                ],
            )
        ],
    )
    postgres = FakePostgres([])
    service = BrainIngestionService(postgres, FakeStructuredModel(knowledge))

    asyncio.run(
        service.distill_session(
            session_id,
            "conv_invalid_camera",
            [
                {
                    "role": "user",
                    "message": "Something happened.",
                    "time_in_call_secs": 1,
                }
            ],
            {},
        )
    )

    assert postgres.statuses == [
        (session_id, "processing"),
        (session_id, "failed"),
    ]
    assert postgres.document is None


def test_distillation_rejects_fabricated_evidence_reference():
    knowledge = StructuredKnowledge(
        title="Invalid",
        objective="Reject fabricated evidence.",
        steps=[
            KnowledgeStep(
                id="step_1",
                action="Invent a step",
                why="Unsupported",
                evidence=[
                    TranscriptTurnEvidence(source="transcript_turn", turn=99)
                ],
            )
        ],
    )

    with pytest.raises(ValueError, match="missing transcript turn 99"):
        validate_evidence_references(
            knowledge,
            [{"role": "user", "message": "Only turn"}],
            [],
        )


def test_transcript_source_ids_are_deterministic_and_globally_scoped():
    first = transcript_source_id("conv_a", 7)

    assert first == transcript_source_id("conv_a", 7)
    assert first != transcript_source_id("conv_a", 8)
    assert first != transcript_source_id("conv_b", 7)


def test_provenance_v2_rejects_visual_only_reasoning():
    with pytest.raises(ValueError, match="reasoning requires expert transcript"):
        StructuredKnowledge(
            provenance_version=2,
            title="Invalid",
            objective="O",
            steps=[
                KnowledgeStep(
                    id="step_1",
                    action="Observed action",
                    why="An unsupported reason",
                    evidence=[
                        VisualObservationEvidence(
                            source="screen_observation",
                            event_id=uuid4(),
                        )
                    ],
                )
            ],
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "decisions",
            [
                {
                    "condition": "Risk is high",
                    "if_true": "Escalate",
                    "if_false": "Continue",
                    "evidence": [
                        {
                            "source": "screen_observation",
                            "event_id": str(uuid4()),
                        }
                    ],
                }
            ],
            "Decision 1 requires expert transcript evidence",
        ),
        (
            "exceptions",
            [
                {
                    "statement": "An exception",
                    "evidence": [
                        {
                            "source": "screen_observation",
                            "event_id": str(uuid4()),
                        }
                    ],
                }
            ],
            "Exception 1 requires expert transcript evidence",
        ),
        (
            "never_do",
            [
                {
                    "statement": "A guardrail",
                    "evidence": [
                        {
                            "source": "camera_observation",
                            "event_id": str(uuid4()),
                        }
                    ],
                }
            ],
            "Never-do 1 requires expert transcript evidence",
        ),
    ],
)
def test_provenance_v2_rejects_uncited_claims(field, value, message):
    with pytest.raises(ValueError, match=message):
        StructuredKnowledge.model_validate(
            {
                "provenance_version": 2,
                "title": "Invalid",
                "objective": "O",
                field: value,
            }
        )


def test_provenance_v2_rejects_cross_session_transcript_identity():
    knowledge = StructuredKnowledge(
        provenance_version=2,
        title="Invalid",
        objective="O",
        steps=[
            KnowledgeStep(
                id="step_1",
                action="A",
                why="W",
                evidence=[
                    TranscriptTurnEvidence(
                        source="transcript_turn",
                        turn=1,
                        source_id=transcript_source_id("conv_other", 1),
                    )
                ],
            )
        ],
    )

    with pytest.raises(ValueError, match="cross-session transcript source ID"):
        validate_evidence_references(
            knowledge,
            [
                {
                    "role": "user",
                    "message": "Expert reason",
                    "time_in_call_secs": 9,
                }
            ],
            [],
            conversation_id="conv_current",
        )


def test_settlement_delay_precedes_final_observation_query(monkeypatch):
    order: list[str] = []

    async def fake_sleep(_seconds):
        order.append("sleep")

    class OrderedPostgres(FakePostgres):
        async def list_screen_observations(self, conversation_id, *, created_before=None):
            order.append("query")
            return await super().list_screen_observations(
                conversation_id,
                created_before=created_before,
            )

    conversation_id = "conv_settlement"
    transcript = [
        {
            "role": "user",
            "message": "Because this is the safe order.",
            "time_in_call_secs": 3,
        }
    ]
    knowledge = StructuredKnowledge(
        provenance_version=2,
        title="T",
        objective="O",
        steps=[
            KnowledgeStep(
                id="step_1",
                action="A",
                why="W",
                evidence=[
                    TranscriptTurnEvidence(
                        source="transcript_turn",
                        turn=1,
                        source_id=transcript_source_id(conversation_id, 1),
                    )
                ],
            )
        ],
    )
    postgres = OrderedPostgres([])
    monkeypatch.setattr(brain_ingestion_module.asyncio, "sleep", fake_sleep)
    service = BrainIngestionService(
        postgres,
        FakeStructuredModel(knowledge),
        settlement_delay_seconds=2,
    )

    asyncio.run(
        service.distill_session(uuid4(), conversation_id, transcript, {})
    )

    assert order == ["sleep", "query"]
    assert postgres.document["evidence_cutoff"] is not None


def test_post_call_carries_the_trained_process_through_ingestion(monkeypatch):
    """The Process must come from initiation data, never be inferred later."""
    monkeypatch.setattr(webhooks.settings, "ELEVENLABS_WEBHOOK_SECRET", None)
    brain = FakeBrain()
    process_id = uuid4()
    payload = {
        "type": "post_call_transcription",
        "event_timestamp": 1739537297,
        "data": {
            "conversation_id": "conv_with_process",
            "status": "done",
            "transcript": [{"role": "user", "message": "Here is my flow."}],
            "metadata": {},
            "conversation_initiation_client_data": {
                "dynamic_variables": {
                    "session_mode": "learning",
                    "process_id": str(process_id),
                }
            },
        },
    }

    with TestClient(_app(brain)) as client:
        response = client.post("/webhooks/elevenlabs/post-call", json=payload)

    assert response.status_code == 200
    assert brain.accepted_process_ids == [process_id]
    assert brain.distilled_process_ids == [process_id]


def test_post_call_without_a_process_is_still_ingested(monkeypatch):
    """A session started before a Process was chosen stays stored, just unteachable."""
    monkeypatch.setattr(webhooks.settings, "ELEVENLABS_WEBHOOK_SECRET", None)
    brain = FakeBrain()
    payload = {
        "type": "post_call_transcription",
        "data": {
            "conversation_id": "conv_no_process",
            "transcript": [{"role": "user", "message": "Anything."}],
            "metadata": {},
            "conversation_initiation_client_data": {
                "dynamic_variables": {"session_mode": "learning"}
            },
        },
    }

    with TestClient(_app(brain)) as client:
        response = client.post("/webhooks/elevenlabs/post-call", json=payload)

    assert response.status_code == 200
    assert brain.accepted_process_ids == [None]


def test_malformed_process_id_does_not_reject_the_training_session(monkeypatch):
    monkeypatch.setattr(webhooks.settings, "ELEVENLABS_WEBHOOK_SECRET", None)
    brain = FakeBrain()
    payload = {
        "type": "post_call_transcription",
        "data": {
            "conversation_id": "conv_bad_process",
            "transcript": [{"role": "user", "message": "Anything."}],
            "metadata": {},
            "conversation_initiation_client_data": {
                "dynamic_variables": {"process_id": "not-a-uuid"}
            },
        },
    }

    with TestClient(_app(brain)) as client:
        response = client.post("/webhooks/elevenlabs/post-call", json=payload)

    assert response.status_code == 200
    assert brain.accepted_process_ids == [None]


def _post_call(conversation_id, dynamic_variables):
    return {
        "type": "post_call_transcription",
        "data": {
            "conversation_id": conversation_id,
            "transcript": [{"role": "user", "message": "Something was said."}],
            "metadata": {},
            "conversation_initiation_client_data": {
                "dynamic_variables": dynamic_variables
            },
        },
    }


def test_teaching_sessions_are_never_distilled(monkeypatch):
    """A tutoring session must not become training for the Process it taught.

    Distilling it would store the learner's own session against that Process,
    and because the newest document wins it would replace the expert's.
    """
    monkeypatch.setattr(webhooks.settings, "ELEVENLABS_WEBHOOK_SECRET", None)
    brain = FakeBrain()
    process_id = uuid4()

    with TestClient(_app(brain)) as client:
        response = client.post(
            "/webhooks/elevenlabs/post-call",
            json=_post_call(
                "conv_teaching",
                {"session_mode": "teaching", "process_id": str(process_id)},
            ),
        )

    assert response.status_code == 200
    assert brain.distilled == []
    assert brain.skipped == [brain.session_id]
    # The session is still recorded against its Process as a learning record.
    assert brain.accepted_process_ids == [process_id]


def test_learning_sessions_are_still_distilled(monkeypatch):
    monkeypatch.setattr(webhooks.settings, "ELEVENLABS_WEBHOOK_SECRET", None)
    brain = FakeBrain()

    with TestClient(_app(brain)) as client:
        client.post(
            "/webhooks/elevenlabs/post-call",
            json=_post_call("conv_learning", {"session_mode": "learning"}),
        )

    assert brain.distilled == ["conv_learning"]
    assert brain.skipped == []


def test_missing_session_mode_is_treated_as_training(monkeypatch):
    """Losing a real expert demonstration is worse than one stray document."""
    monkeypatch.setattr(webhooks.settings, "ELEVENLABS_WEBHOOK_SECRET", None)
    brain = FakeBrain()

    with TestClient(_app(brain)) as client:
        client.post(
            "/webhooks/elevenlabs/post-call",
            json=_post_call("conv_no_mode", {}),
        )

    assert brain.distilled == ["conv_no_mode"]
    assert brain.skipped == []
