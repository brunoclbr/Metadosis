"""Source-preserving contracts and deterministic rendering for Brain documents."""

import math
from datetime import datetime, timezone
from typing import Annotated, Any, Iterable, Literal
from uuid import UUID, NAMESPACE_URL, uuid5

from pydantic import BaseModel, Field, model_validator


class TranscriptTurnEvidence(BaseModel):
    source: Literal["transcript_turn"]
    turn: int = Field(ge=1)
    # Documents created before provenance v2 identify a turn only by its original
    # array position. New documents also carry this globally scoped identity.
    source_id: UUID | None = None


class VisualObservationEvidence(BaseModel):
    """One cited visual observation, from the shared screen or the camera."""

    source: Literal["screen_observation", "camera_observation"]
    event_id: UUID


EvidenceReference = Annotated[
    TranscriptTurnEvidence | VisualObservationEvidence,
    Field(discriminator="source"),
]


class KnowledgeStep(BaseModel):
    id: str
    action: str
    why: str
    evidence: list[EvidenceReference] = Field(min_length=1)


class KnowledgeDecision(BaseModel):
    condition: str
    if_true: str
    if_false: str
    evidence: list[EvidenceReference] = Field(default_factory=list)


class KnowledgeClaim(BaseModel):
    """A non-step claim whose text remains inseparable from its sources."""

    statement: str = Field(min_length=1)
    evidence: list[EvidenceReference] = Field(min_length=1)


class StructuredKnowledge(BaseModel):
    """The stored Work Map contract.

    Version 1 is the deployed step-level provenance shape. Version 2 adds stable
    transcript identities and expert-transcript support for reasoning, decisions,
    exceptions, and guardrails. Missing versions intentionally parse as v1 so
    existing documents remain readable without pretending they meet v2.
    """

    provenance_version: Literal[1, 2] = 1
    title: str
    objective: str
    steps: list[KnowledgeStep] = Field(default_factory=list)
    decisions: list[KnowledgeDecision] = Field(default_factory=list)
    exceptions: list[str | KnowledgeClaim] = Field(default_factory=list)
    never_do: list[str | KnowledgeClaim] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_claim_level_provenance(self) -> "StructuredKnowledge":
        if self.provenance_version != 2:
            return self

        for step in self.steps:
            if step.why.strip() and not _has_transcript_evidence(step.evidence):
                raise ValueError(
                    f"Step {step.id} reasoning requires expert transcript evidence"
                )
        for index, decision in enumerate(self.decisions, start=1):
            if not _has_transcript_evidence(decision.evidence):
                raise ValueError(
                    f"Decision {index} requires expert transcript evidence"
                )
        for label, claims in (("Exception", self.exceptions), ("Never-do", self.never_do)):
            for index, claim in enumerate(claims, start=1):
                if not isinstance(claim, KnowledgeClaim):
                    raise ValueError(
                        f"{label} {index} must be an evidence-bearing claim in provenance v2"
                    )
                if not _has_transcript_evidence(claim.evidence):
                    raise ValueError(
                        f"{label} {index} requires expert transcript evidence"
                    )
        return self


def _has_transcript_evidence(evidence: Iterable[EvidenceReference]) -> bool:
    return any(isinstance(item, TranscriptTurnEvidence) for item in evidence)


def transcript_source_id(conversation_id: str, turn: int) -> UUID:
    """Return the stable global identity of one original provider transcript item."""
    return uuid5(NAMESPACE_URL, f"metadosis:{conversation_id}:transcript:{turn}")


def _claim_text(claim: str | KnowledgeClaim) -> str:
    return claim.statement if isinstance(claim, KnowledgeClaim) else claim


def _bullet_section(title: str, values: list[str | KnowledgeClaim]) -> list[str]:
    lines = [f"## {title}", ""]
    if not values:
        return [*lines, "_None captured._", ""]
    for value in values:
        lines.append(f"- {_claim_text(value)}")
        if isinstance(value, KnowledgeClaim):
            lines.extend(
                f"  - **Evidence:** {render_evidence_reference(item)}"
                for item in value.evidence
            )
    return [*lines, ""]


def render_knowledge_markdown(knowledge: StructuredKnowledge) -> str:
    """Render only validated source-derived fields in a stable order."""
    lines = [f"# {knowledge.title}", "", "## Objective", "", knowledge.objective, ""]

    lines.extend(["## Steps", ""])
    if not knowledge.steps:
        lines.extend(["_No steps captured._", ""])
    for index, step in enumerate(knowledge.steps, start=1):
        lines.extend(
            [
                f"### {index}. {step.action}",
                "",
                f"**Why:** {step.why}",
                "",
                "**Evidence:**",
                "",
                *[f"- {render_evidence_reference(item)}" for item in step.evidence],
                "",
            ]
        )

    lines.extend(["## Decisions", ""])
    if not knowledge.decisions:
        lines.extend(["_No decisions captured._", ""])
    for decision in knowledge.decisions:
        lines.extend(
            [
                f"- **When:** {decision.condition}",
                f"  - **If true:** {decision.if_true}",
                f"  - **If false:** {decision.if_false}",
            ]
        )
        if decision.evidence:
            lines.extend(
                f"  - **Evidence:** {render_evidence_reference(item)}"
                for item in decision.evidence
            )
    if knowledge.decisions:
        lines.append("")

    lines.extend(_bullet_section("Exceptions", knowledge.exceptions))
    lines.extend(_bullet_section("Never Do", knowledge.never_do))
    lines.extend(_bullet_section("Tools", knowledge.tools))
    lines.extend(_bullet_section("Artifacts", knowledge.artifacts))
    return "\n".join(lines).rstrip() + "\n"


def render_evidence_reference(evidence: EvidenceReference) -> str:
    if isinstance(evidence, TranscriptTurnEvidence):
        stable_id = f" (`{evidence.source_id}`)" if evidence.source_id else ""
        return f"Transcript turn {evidence.turn}{stable_id}"
    label = (
        "Camera observation"
        if evidence.source == "camera_observation"
        else "Screen observation"
    )
    return f"{label} `{evidence.event_id}`"


def _valid_relative_time(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        return None
    return normalized


def _start_time(metadata: dict[str, Any]) -> float | None:
    value = metadata.get("start_time_unix_secs")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    normalized = float(value)
    return normalized if math.isfinite(normalized) and normalized >= 0 else None


def format_relative_time(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, remaining_seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{remaining_seconds:02d}"
    return f"{minutes:02d}:{remaining_seconds:02d}"


def transcript_as_text(
    transcript: list[dict[str, Any]],
    *,
    conversation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Create source text while retaining the immutable original JSON.

    The optional arguments preserve the v1 rendering for legacy callers. The
    ingestion path always supplies them and therefore exposes v2 identity and
    timing to the distiller.
    """
    lines: list[str] = []
    start = _start_time(metadata or {})
    for turn, item in enumerate(transcript, start=1):
        role = str(item.get("role") or item.get("speaker") or "unknown")
        message = item.get("message") or item.get("text") or item.get("content")
        if not isinstance(message, str) or not message.strip():
            continue
        if conversation_id is None:
            lines.append(f"turn_{turn} | {role}: {message.strip()}")
            continue

        relative_time = _valid_relative_time(item.get("time_in_call_secs"))
        relative_label = (
            f"at {format_relative_time(relative_time)}"
            if relative_time is not None
            else "at unknown_time"
        )
        absolute_label = ""
        if start is not None and relative_time is not None:
            occurred_at = datetime.fromtimestamp(
                start + relative_time, tz=timezone.utc
            ).isoformat()
            absolute_label = f" | utc {occurred_at}"
        lines.append(
            f"transcript_turn {transcript_source_id(conversation_id, turn)} "
            f"| turn_{turn} | {relative_label}{absolute_label} | "
            f"{role}: {message.strip()}"
        )
    return "\n".join(lines)


def visual_observations_as_text(observations: list[dict[str, Any]]) -> str:
    """Render ordered textual observations with immutable IDs and timing."""
    lines: list[str] = []
    for item in observations:
        relative_time = _valid_relative_time(item.get("time_in_call_secs"))
        relative_label = (
            f" | approx_call_time {format_relative_time(relative_time)}"
            if relative_time is not None
            else ""
        )
        lines.append(
            f"{observation_evidence_source(item)} {item['event_id']} "
            f"| browser_utc {item['occurred_at'].isoformat()}"
            f"{relative_label}: {item['summary']}"
        )
    return "\n".join(lines)


def observation_evidence_source(observation: dict[str, Any]) -> str:
    return (
        "camera_observation"
        if str(observation.get("source") or "screen") == "camera"
        else "screen_observation"
    )


def iter_evidence_references(
    knowledge: StructuredKnowledge,
) -> Iterable[tuple[str, EvidenceReference]]:
    for step in knowledge.steps:
        for evidence in step.evidence:
            yield f"Step {step.id}", evidence
    for index, decision in enumerate(knowledge.decisions, start=1):
        for evidence in decision.evidence:
            yield f"Decision {index}", evidence
    for label, claims in (("Exception", knowledge.exceptions), ("Never-do", knowledge.never_do)):
        for index, claim in enumerate(claims, start=1):
            if isinstance(claim, KnowledgeClaim):
                for evidence in claim.evidence:
                    yield f"{label} {index}", evidence


def validate_evidence_references(
    knowledge: StructuredKnowledge,
    transcript: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    *,
    conversation_id: str | None = None,
) -> None:
    """Reject nonexistent, cross-session, mistyped, or invalidly timed sources."""
    transcript_turns = {
        turn: item
        for turn, item in enumerate(transcript, start=1)
        if isinstance(
            item.get("message") or item.get("text") or item.get("content"), str
        )
        and (item.get("message") or item.get("text") or item.get("content")).strip()
    }
    observation_by_id = {UUID(str(item["event_id"])): item for item in observations}

    for owner, evidence in iter_evidence_references(knowledge):
        if isinstance(evidence, TranscriptTurnEvidence):
            item = transcript_turns.get(evidence.turn)
            if item is None:
                raise ValueError(
                    f"{owner} references missing transcript turn {evidence.turn}"
                )
            if knowledge.provenance_version == 2:
                if conversation_id is None:
                    raise ValueError("Conversation ID is required for provenance v2")
                expected_id = transcript_source_id(conversation_id, evidence.turn)
                if evidence.source_id != expected_id:
                    raise ValueError(
                        f"{owner} references an invalid or cross-session transcript source ID"
                    )
                if _valid_relative_time(item.get("time_in_call_secs")) is None:
                    raise ValueError(
                        f"{owner} references transcript turn {evidence.turn} with invalid timing"
                    )
                role = str(item.get("role") or item.get("speaker") or "").lower()
                if role not in {"user", "human"}:
                    raise ValueError(
                        f"{owner} requires expert transcript evidence, not role {role or 'unknown'}"
                    )
            continue

        observation = observation_by_id.get(evidence.event_id)
        if observation is None:
            raise ValueError(
                f"{owner} references missing visual observation {evidence.event_id}"
            )
        if (
            knowledge.provenance_version == 2
            and observation_evidence_source(observation) != evidence.source
        ):
            raise ValueError(f"{owner} references a visual observation under the wrong type")
        relative_time = observation.get("time_in_call_secs")
        if relative_time is not None and _valid_relative_time(relative_time) is None:
            raise ValueError(f"{owner} references a visual observation with invalid timing")


class ResolvedEvidence(BaseModel):
    """One cited source rendered as readable, timestamped text for the tutor."""

    id: str
    type: Literal["transcript", "screen_observation", "camera_observation"]
    time_in_call_secs: float | None = None
    display_time: str | None = None
    occurred_at: datetime | None = None
    timing_origin: Literal[
        "elevenlabs",
        "browser_connection_approximation",
        "browser_wall_clock",
    ]
    speaker: str | None = None
    content: str


class TeacherContext(BaseModel):
    process_id: UUID
    provenance_version: Literal[1, 2]
    evidence_cutoff: datetime | None = None
    title: str
    objective: str
    steps: list[KnowledgeStep] = Field(default_factory=list)
    decisions: list[KnowledgeDecision] = Field(default_factory=list)
    exceptions: list[str | KnowledgeClaim] = Field(default_factory=list)
    never_do: list[str | KnowledgeClaim] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    evidence: list[ResolvedEvidence] = Field(default_factory=list)


def _transcript_turns(transcript: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    turns: dict[int, dict[str, Any]] = {}
    for turn, item in enumerate(transcript, start=1):
        message = item.get("message") or item.get("text") or item.get("content")
        if isinstance(message, str) and message.strip():
            turns[turn] = {
                "speaker": str(item.get("role") or item.get("speaker") or "unknown"),
                "content": message.strip(),
                "time_in_call_secs": _valid_relative_time(
                    item.get("time_in_call_secs")
                ),
            }
    return turns


def build_teacher_context(
    *,
    process_id: UUID,
    knowledge: StructuredKnowledge,
    transcript: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    conversation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    evidence_cutoff: datetime | None = None,
) -> TeacherContext:
    """Resolve every citation; fail closed if any stored reference is unavailable."""
    validate_evidence_references(
        knowledge,
        transcript,
        observations,
        conversation_id=conversation_id,
    )
    turns = _transcript_turns(transcript)
    start = _start_time(metadata or {})
    resolved_observations = {
        str(item["event_id"]): item for item in observations
    }

    resolved: list[ResolvedEvidence] = []
    seen: set[str] = set()
    for _owner, evidence in iter_evidence_references(knowledge):
        if isinstance(evidence, TranscriptTurnEvidence):
            turn = turns[evidence.turn]
            stable_id = evidence.source_id
            if stable_id is None and conversation_id is not None:
                stable_id = transcript_source_id(conversation_id, evidence.turn)
            identifier = str(stable_id) if stable_id else f"turn_{evidence.turn}"
            if identifier in seen:
                continue
            seen.add(identifier)
            relative_time = turn["time_in_call_secs"]
            occurred_at = None
            if start is not None and relative_time is not None:
                occurred_at = datetime.fromtimestamp(
                    start + relative_time, tz=timezone.utc
                )
            resolved.append(
                ResolvedEvidence(
                    id=identifier,
                    type="transcript",
                    time_in_call_secs=relative_time,
                    display_time=(
                        format_relative_time(relative_time)
                        if relative_time is not None
                        else None
                    ),
                    occurred_at=occurred_at,
                    timing_origin="elevenlabs",
                    speaker=turn["speaker"],
                    content=turn["content"],
                )
            )
            continue

        identifier = str(evidence.event_id)
        if identifier in seen:
            continue
        seen.add(identifier)
        observation = resolved_observations[identifier]
        relative_time = _valid_relative_time(observation.get("time_in_call_secs"))
        resolved.append(
            ResolvedEvidence(
                id=identifier,
                type=observation_evidence_source(observation),
                time_in_call_secs=relative_time,
                display_time=(
                    format_relative_time(relative_time)
                    if relative_time is not None
                    else None
                ),
                occurred_at=observation["occurred_at"],
                timing_origin=(
                    "browser_connection_approximation"
                    if relative_time is not None
                    else "browser_wall_clock"
                ),
                content=str(observation["summary"]),
            )
        )

    return TeacherContext(
        process_id=process_id,
        provenance_version=knowledge.provenance_version,
        evidence_cutoff=evidence_cutoff,
        title=knowledge.title,
        objective=knowledge.objective,
        steps=knowledge.steps,
        decisions=knowledge.decisions,
        exceptions=knowledge.exceptions,
        never_do=knowledge.never_do,
        tools=knowledge.tools,
        artifacts=knowledge.artifacts,
        evidence=resolved,
    )
