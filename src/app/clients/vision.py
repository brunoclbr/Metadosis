"""Provider-neutral multimodal screen-change client."""

import base64

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, model_validator


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


class ScreenChange(BaseModel):
    """The only editorial judgment delegated to the vision model."""

    meaningful_change: bool
    summary: str | None = None

    @model_validator(mode="after")
    def validate_summary(self) -> "ScreenChange":
        if self.meaningful_change:
            if not self.summary or not self.summary.strip():
                raise ValueError("A meaningful screen change requires a summary")
            self.summary = self.summary.strip()
        else:
            self.summary = None
        return self


class VisionObservationClient:
    """Compare two transient screen images with an already-configured chat model."""

    def __init__(
        self,
        model: BaseChatModel,
        *,
        provider_name: str,
        model_name: str,
    ) -> None:
        self._comparison_model = model.with_structured_output(
            ScreenChange,
            method="json_schema",
        )
        self.provider_name = provider_name
        self.model_name = model_name

    async def compare(
        self,
        previous_image: bytes,
        current_image: bytes,
        mime_type: str,
    ) -> ScreenChange:
        message = HumanMessage(
            content=[
                {"type": "text", "text": _SCREEN_CHANGE_PROMPT},
                {"type": "text", "text": "BEFORE screenshot:"},
                _image_block(previous_image, mime_type),
                {"type": "text", "text": "AFTER screenshot:"},
                _image_block(current_image, mime_type),
            ]
        )
        result = await self._comparison_model.ainvoke([message])
        if isinstance(result, ScreenChange):
            return result
        return ScreenChange.model_validate(result)


def _image_block(image: bytes, mime_type: str) -> dict[str, str]:
    return {
        "type": "image",
        "source_type": "base64",
        "mime_type": mime_type,
        "data": base64.b64encode(image).decode("ascii"),
    }
