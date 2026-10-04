"""Source-preserving contracts and deterministic rendering for Brain documents."""

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class TranscriptTurnEvidence(BaseModel):
    source: Literal["transcript_turn"]
    turn: int = Field(ge=1)


class VisualObservationEvidence(BaseModel):
    """One cited visual observation, from the shared screen or the camera.

    Both spellings resolve to the same event ID, which is what makes the
    reference checkable. ``screen_observation`` is kept because documents already
    distilled in production cite it, and rejecting those would make previously
    teachable Processes unteachable. ``camera_observation`` exists so the
    distiller can name what it actually saw without a tag the schema refuses.
    """

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


class StructuredKnowledge(BaseModel):
    title: str
    objective: str
    steps: list[KnowledgeStep] = Field(default_factory=list)
    decisions: list[KnowledgeDecision] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    never_do: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)


def _bullet_section(title: str, values: list[str]) -> list[str]:
    lines = [f"## {title}", ""]
    lines.extend([f"- {value}" for value in values] or ["_None captured._"])
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
    if knowledge.decisions:
        lines.append("")

    lines.extend(_bullet_section("Exceptions", knowledge.exceptions))
    lines.extend(_bullet_section("Never Do", knowledge.never_do))
    lines.extend(_bullet_section("Tools", knowledge.tools))
    lines.extend(_bullet_section("Artifacts", knowledge.artifacts))
    return "\n".join(lines).rstrip() + "\n"


def render_evidence_reference(evidence: EvidenceReference) -> str:
    if isinstance(evidence, TranscriptTurnEvidence):
        return f"Transcript turn {evidence.turn}"
    label = "Camera observation" if evidence.source == "camera_observation" else (
        "Screen observation"
    )
    return f"{label} `{evidence.event_id}`"


def transcript_as_text(transcript: list[dict[str, Any]]) -> str:
    """Create numbered source text while retaining the original JSON in PostgreSQL."""
    lines: list[str] = []
    for turn, item in enumerate(transcript, start=1):
        role = str(item.get("role") or item.get("speaker") or "unknown")
        message = item.get("message") or item.get("text") or item.get("content")
        if isinstance(message, str) and message.strip():
            lines.append(f"turn_{turn} | {role}: {message.strip()}")
    return "\n".join(lines)


def visual_observations_as_text(observations: list[dict[str, Any]]) -> str:
    """Render ordered textual observations with their immutable source IDs.

    The leading tag is the exact evidence ``source`` the distiller must cite for
    that event, so a camera observation is never filed as a screen one.
    """
    return "\n".join(
        f"{observation_evidence_source(item)} {item['event_id']} "
        f"at {item['occurred_at'].isoformat()}: {item['summary']}"
        for item in observations
    )


def observation_evidence_source(observation: dict[str, Any]) -> str:
    """Map a stored observation row to its evidence tag."""
    return (
        "camera_observation"
        if str(observation.get("source") or "screen") == "camera"
        else "screen_observation"
    )


def validate_evidence_references(
    knowledge: StructuredKnowledge,
    transcript: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> None:
    """Reject model references that do not exist in the persisted source material."""
    transcript_turns = {
        turn
        for turn, item in enumerate(transcript, start=1)
        if isinstance(
            item.get("message") or item.get("text") or item.get("content"),
            str,
        )
        and (item.get("message") or item.get("text") or item.get("content")).strip()
    }
    observation_ids = {UUID(str(item["event_id"])) for item in observations}

    for step in knowledge.steps:
        for evidence in step.evidence:
            if (
                isinstance(evidence, TranscriptTurnEvidence)
                and evidence.turn not in transcript_turns
            ):
                raise ValueError(
                    f"Step {step.id} references missing transcript turn {evidence.turn}"
                )
            if (
                isinstance(evidence, VisualObservationEvidence)
                and evidence.event_id not in observation_ids
            ):
                raise ValueError(
                    f"Step {step.id} references missing visual observation "
                    f"{evidence.event_id}"
                )


class ResolvedEvidence(BaseModel):
    """One cited source rendered as readable text for the live tutor.

    The tutor reasons over text, not database rows, so evidence is flattened to a
    stable ID, its origin, and the words actually captured. Screenshots are never
    included: only the vision model's textual observation was ever persisted.
    """

    id: str
    type: Literal["transcript", "screen_observation", "camera_observation"]
    speaker: str | None = None
    content: str


class TeacherContext(BaseModel):
    """The complete Brain payload one tutor session teaches from.

    This is the read-side counterpart of ``StructuredKnowledge``. It inlines the
    resolved evidence so the tutor needs exactly one tool call per session, and it
    carries ``process_id`` so a transcript of the call shows which Process was
    taught.
    """

    process_id: UUID
    title: str
    objective: str
    steps: list[KnowledgeStep] = Field(default_factory=list)
    decisions: list[KnowledgeDecision] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    never_do: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    evidence: list[ResolvedEvidence] = Field(default_factory=list)


def _transcript_turn_texts(transcript: list[dict[str, Any]]) -> dict[int, dict[str, str]]:
    """Index the turn numbering that ``transcript_as_text`` showed the distiller.

    Evidence turn numbers are only meaningful against that same enumeration, so
    both functions must skip identical entries. Keep them changing together.
    """
    turns: dict[int, dict[str, str]] = {}
    for turn, item in enumerate(transcript, start=1):
        message = item.get("message") or item.get("text") or item.get("content")
        if isinstance(message, str) and message.strip():
            turns[turn] = {
                "speaker": str(item.get("role") or item.get("speaker") or "unknown"),
                "content": message.strip(),
            }
    return turns


def build_teacher_context(
    *,
    process_id: UUID,
    knowledge: StructuredKnowledge,
    transcript: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> TeacherContext:
    """Resolve every cited reference in one document into readable evidence.

    Only evidence the steps actually cite is included. Returning the full
    transcript would reintroduce the unfiltered source the distillation step
    exists to compress, and would let the tutor teach from material no expert
    reasoning was attached to.

    References that cannot be resolved are dropped rather than invented. A step
    keeps its action and reasoning; the tutor simply has no quotable source for
    it, which is the honest outcome.
    """
    turns = _transcript_turn_texts(transcript)
    # The stored row decides whether an observation was screen or camera, not the
    # tag the distiller happened to cite it under. A miscited event still reaches
    # the tutor describing the input it truly came from.
    resolved_observations = {
        str(item["event_id"]): (
            observation_evidence_source(item),
            str(item["summary"]),
        )
        for item in observations
    }

    resolved: list[ResolvedEvidence] = []
    seen: set[str] = set()
    for step in knowledge.steps:
        for evidence in step.evidence:
            if isinstance(evidence, TranscriptTurnEvidence):
                turn = turns.get(evidence.turn)
                identifier = f"turn_{evidence.turn}"
                if turn is None or identifier in seen:
                    continue
                seen.add(identifier)
                resolved.append(
                    ResolvedEvidence(
                        id=identifier,
                        type="transcript",
                        speaker=turn["speaker"],
                        content=turn["content"],
                    )
                )
                continue

            identifier = str(evidence.event_id)
            observation = resolved_observations.get(identifier)
            if observation is None or identifier in seen:
                continue
            seen.add(identifier)
            observation_source, summary = observation
            resolved.append(
                ResolvedEvidence(
                    id=identifier,
                    type=observation_source,
                    content=summary,
                )
            )

    return TeacherContext(
        process_id=process_id,
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
