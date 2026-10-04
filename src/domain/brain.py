"""Source-preserving contracts and deterministic rendering for Brain documents."""

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class TranscriptTurnEvidence(BaseModel):
    source: Literal["transcript_turn"]
    turn: int = Field(ge=1)


class ScreenObservationEvidence(BaseModel):
    source: Literal["screen_observation"]
    event_id: UUID


EvidenceReference = Annotated[
    TranscriptTurnEvidence | ScreenObservationEvidence,
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
    return f"Screen observation `{evidence.event_id}`"


def transcript_as_text(transcript: list[dict[str, Any]]) -> str:
    """Create numbered source text while retaining the original JSON in PostgreSQL."""
    lines: list[str] = []
    for turn, item in enumerate(transcript, start=1):
        role = str(item.get("role") or item.get("speaker") or "unknown")
        message = item.get("message") or item.get("text") or item.get("content")
        if isinstance(message, str) and message.strip():
            lines.append(f"turn_{turn} | {role}: {message.strip()}")
    return "\n".join(lines)


def screen_observations_as_text(observations: list[dict[str, Any]]) -> str:
    """Render ordered textual observations with their immutable source IDs."""
    return "\n".join(
        f"screen_observation {item['event_id']} at {item['occurred_at'].isoformat()}: "
        f"{item['summary']}"
        for item in observations
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
                isinstance(evidence, ScreenObservationEvidence)
                and evidence.event_id not in observation_ids
            ):
                raise ValueError(
                    f"Step {step.id} references missing screen observation "
                    f"{evidence.event_id}"
                )
