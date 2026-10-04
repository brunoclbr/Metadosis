"""Provider-neutral multimodal client for screen and camera observation."""

import base64
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, model_validator

VisualSource = Literal["screen", "camera"]

_SCREEN_CHANGE_PROMPT = (
    "Compare the BEFORE and AFTER screenshots. Identify visible changes relevant "
    "to what the user is doing, including small ones: an object being added, "
    "moved, resized, or recolored, or text being edited. Name the changed object "
    "and state its relevant visible attributes, such as color, text, and "
    "position, for both before and after when they differ. Ignore only visual "
    "noise: cursor movement, animation, clock changes, and rendering artifacts. "
    "Do not infer hidden intent. If nothing task-related changed, return "
    "meaningful_change=false and summary=null. Otherwise return "
    "meaningful_change=true and describe the change in one concise factual "
    "sentence."
)

# A camera sees both physical work and non-verbal expertise. Pixels change
# constantly, so the model must retain deliberate hand/facial communication while
# rejecting incidental motion that conveys no stable visible signal.
_CAMERA_CHANGE_PROMPT = (
    "Compare the BEFORE and AFTER camera frames of a person demonstrating or "
    "explaining work. Report a meaningful visible change in either category. "
    "First, physical work: the person picking up, putting down, pointing to, or "
    "switching a tool or part; a component being removed, fitted, opened, closed, "
    "tightened, or loosened; an object changing state; a distinct action starting "
    "or finishing; or a visibly unsafe or out-of-order action. Second, non-verbal "
    "communication: a deliberate hand gesture such as pointing, counting, "
    "indicating direction or size, thumbs-up/down, or visibly connecting ideas; "
    "or a clear facial expression change such as beginning or ending a smile, "
    "frowning, raising the eyebrows, or furrowing the brow. "
    "Return meaningful_change=false and summary=null when the only differences "
    "are a blink, ordinary mouth movement while speaking, an indistinct hand "
    "movement, a posture shift, the same gesture or action continuing, camera "
    "shake or refocus, lighting or exposure changes, or background motion. "
    "Describe only what is visible. State the gesture or facial movement "
    "factually; do not infer emotion, intent, reasoning, or the name of a step. "
    "Do not describe the room, clothing, or background. If an object or gesture "
    "is unclear, say so rather than guessing. When the change is meaningful, "
    "return meaningful_change=true and one concise present-tense sentence "
    "suitable for reading aloud, such as \"The user points from left to right\" "
    "or \"The user begins smiling and raises both thumbs.\""
)

_PROMPTS: dict[VisualSource, str] = {
    "screen": _SCREEN_CHANGE_PROMPT,
    "camera": _CAMERA_CHANGE_PROMPT,
}

_FRAME_LABELS: dict[VisualSource, tuple[str, str]] = {
    "screen": ("BEFORE screenshot:", "AFTER screenshot:"),
    "camera": ("BEFORE camera frame:", "AFTER camera frame:"),
}


class VisualChange(BaseModel):
    """The only editorial judgment delegated to the vision model."""

    meaningful_change: bool
    summary: str | None = None

    @model_validator(mode="after")
    def validate_summary(self) -> "VisualChange":
        if self.meaningful_change:
            if not self.summary or not self.summary.strip():
                raise ValueError("A meaningful visual change requires a summary")
            self.summary = self.summary.strip()
        else:
            self.summary = None
        return self


class VisionObservationClient:
    """Compare two transient frames with an already-configured chat model."""

    def __init__(
        self,
        model: BaseChatModel,
        *,
        provider_name: str,
        model_name: str,
    ) -> None:
        self._comparison_model = model.with_structured_output(
            VisualChange,
            method="json_schema",
        )
        self.provider_name = provider_name
        self.model_name = model_name

    async def compare(
        self,
        previous_image: bytes,
        current_image: bytes,
        mime_type: str,
        source: VisualSource = "screen",
    ) -> VisualChange:
        """Compare one frame pair under the instructions its source deserves."""
        before_label, after_label = _FRAME_LABELS[source]
        message = HumanMessage(
            content=[
                {"type": "text", "text": _PROMPTS[source]},
                {"type": "text", "text": before_label},
                _image_block(previous_image, mime_type),
                {"type": "text", "text": after_label},
                _image_block(current_image, mime_type),
            ]
        )
        result = await self._comparison_model.ainvoke([message])
        if isinstance(result, VisualChange):
            return result
        return VisualChange.model_validate(result)


def _image_block(image: bytes, mime_type: str) -> dict[str, str]:
    return {
        "type": "image",
        "source_type": "base64",
        "mime_type": mime_type,
        "data": base64.b64encode(image).decode("ascii"),
    }
