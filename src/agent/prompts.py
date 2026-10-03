import opik
from loguru import logger

from src.config import settings


class Prompt:
    def __init__(self, name: str, prompt: str) -> None:
        self.name = name

        try:
            client = opik.Opik(project_name=settings.COMET_PROJECT)
            self.__prompt = client.create_prompt(name=name, prompt=prompt)
        except Exception:
            logger.warning(
                "Can't use Opik to version the prompt. Falling back to the local prompt."
            )
            self.__prompt = prompt

    @property
    def prompt(self) -> str:
        return getattr(self.__prompt, "prompt", self.__prompt)
    
    def __str__(self) -> str:
        return self.prompt

    def __repr__(self) -> str:
        return self.__str__()

# Raw Prompts

__SYSTEM_PROMPT = """
You are a helpful assistant that can help with a variety of tasks. Answer the user's questions to the best of your ability in a friendly manner.
"""

__ROUTER_SYSTEM_PROMPT = """
Your task is to analyze an incoming user message and determine the
expected format for the next reply, either 'text' or 'audio'.
"""

# Versioned Prompts

SYSTEM_PROMPT = Prompt(
    name="system_prompt",
    prompt=__SYSTEM_PROMPT,
)

ROUTER_SYSTEM_PROMPT = Prompt(
    name="router_system_prompt",
    prompt=__ROUTER_SYSTEM_PROMPT,
)
