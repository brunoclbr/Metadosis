"""Provider-neutral multimodal observation client."""

import base64

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage


_SCREEN_OBSERVATION_PROMPT = (
    "Describe what is visibly happening on this shared screen in one concise "
    "factual sentence. Do not infer hidden intentions or information that is not "
    "visible. Return only that sentence."
)


class VisionObservationClient:
    """Send transient screen images to an already-configured chat model."""

    def __init__(
        self,
        model: BaseChatModel,
        *,
        provider_name: str,
        model_name: str,
    ) -> None:
        self._model = model
        self.provider_name = provider_name
        self.model_name = model_name

    async def describe(self, image: bytes, mime_type: str) -> str:
        encoded_image = base64.b64encode(image).decode("ascii")
        message = HumanMessage(
            content=[
                {"type": "text", "text": _SCREEN_OBSERVATION_PROMPT},
                {
                    "type": "image",
                    "source_type": "base64",
                    "mime_type": mime_type,
                    "data": encoded_image,
                },
            ]
        )
        response = await self._model.ainvoke([message])
        description = response.text.strip()
        if not description:
            raise ValueError("Vision model returned an empty observation")
        return description
