"""Source-preserving contracts and deterministic rendering for Brain documents."""

from typing import Any

from pydantic import BaseModel, Field


class KnowledgeStep(BaseModel):
    id: str
    action: str
    why: str
    evidence: list[str] = Field(default_factory=list)


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
                *([f"- {item}" for item in step.evidence] or ["- None captured."]),
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


def transcript_as_text(transcript: list[dict[str, Any]]) -> str:
    """Create a compact model input while retaining the original JSON in PostgreSQL."""
    lines: list[str] = []
    for item in transcript:
        role = str(item.get("role") or item.get("speaker") or "unknown")
        message = item.get("message") or item.get("text") or item.get("content")
        if isinstance(message, str) and message.strip():
            lines.append(f"{role}: {message.strip()}")
    return "\n".join(lines)
