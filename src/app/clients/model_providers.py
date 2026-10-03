from ast import Call
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI

from src.config import settings

@lru_cache(maxsize=1)
def get_openai_client():

    from openai import OpenAI
    """
    Get or create the OpenAI client singleton. The client is created once and cached for subsequent calls.
    This was an older implementation where I had just one model provider. At first I mapped this function as an instance method,
    but @lru_cache on an instance method works by chance (default object hash = identity). It silently keeps every 
    ModelProvider instance alive forever (cache never releases the self reference). It turns into a memory leak in long-running 
    processes. Used functools.cached_property instead, which caches per-instance and doesn't leak.
    """
    return OpenAI(api_key=settings.OPENAI_API_KEY)

@dataclass(frozen=True)
class ProviderConfig:
    """
    Why not use Pydantic's `BaseModel` here for variable definition? In other words why `dataclass(frozen=True)` and not Pydantic?

        1. **No validation is happening here that Pydantic would help with.** 
        `ProviderConfig` holds a class reference (`Callable`) and two strings. Pydantic's value is runtime validation/coercion 
        of *external, untrusted input* (API payloads, env vars, user input) into typed data. This isn't that — `PROVIDER_REGISTRY` 
        is hardcoded by you, at import time, in Python. There's nothing to validate; if you typo a key it's a Python bug you'll 
        catch immediately, not bad data from the outside world.

        2. **`Callable` fields are awkward in Pydantic.** Storing a class (`ChatOpenAI`, `ChatAnthropic`) as a field value works 
        in Pydantic v2 but requires `arbitrary_types_allowed=True` or careful type annotation — it's fighting the tool a bit, since 
        Pydantic is oriented around serializable data, not holding references to classes/callables. Dataclasses don't care, since 
        it's just a plain attribute.

        3. **`frozen=True` gives immutability for near-zero cost.** These configs are set once at module load and should never change
        during the app's life — freezing them means if someone later writes `PROVIDER_REGISTRY["openai"].api_key = "oops"` somewhere
        in a debugging session, it raises `FrozenInstanceError` instead of silently corrupting shared state that every node in your 
        graph reads from. Pydantic models are mutable by default too (you'd need `model_config = ConfigDict(frozen=True)` to match)
         — so this isn't actually a dataclass-exclusive advantage, just the default I reached for without extra config.

    **Where Pydantic would actually be better:** if `PROVIDER_REGISTRY` were ever built from something external — a 
    `providers.yaml` file, environment-variable-driven config, or user-uploaded settings — then yes, Pydantic's validation (catching
    a missing `api_key` or malformed URL at load time with a clear error) would earn its weight. Right now that's not your setup, 
    but if you're heading toward config-driven provider registration rather than hardcoded, say so and I'll switch it — that's a real 
    design fork, not a style preference.

    So: dataclass was the leaner tool for "hardcoded internal shape with no external input," not a reflexive choice. If you already 
    use Pydantic everywhere else in the codebase for consistency, that's a legitimate reason to override my pick — consistency has 
    real value too."""

    chat_cls: Callable[..., BaseChatModel] # this typehint is not going to type-check the exact constructor arguments here and will return `BaseChatModel`
    api_key: Optional[str]
    base_url: Optional[str] = None

# Main dictionary container with different providers
PROVIDER_REGISTRY: dict[str, ProviderConfig] = {
    "anthropic": ProviderConfig(
        ChatAnthropic, 
        settings.ANTHROPIC_API_KEY),
    "openai": ProviderConfig(
        ChatOpenAI, 
        settings.OPENAI_API_KEY),
    "gemini": ProviderConfig(
        ChatGoogleGenerativeAI,
        settings.GEMINI_API_KEY
    ),    
    "oss": ProviderConfig(
        chat_cls=ChatOpenAI, 
        api_key="not-needed",
        base_url=settings.OPEN_SOURCE_BASE_URL
    )
}

@lru_cache(maxsize=1)
def _build_chat_model(model_provider: str, model_name: str) -> BaseChatModel:
    """Module-level cache keyed on (provider, model) strings only —
    no self-reference held, so this can't leak instances like lru_cache
    on a method would."""
    config = PROVIDER_REGISTRY[model_provider]
    kwargs = {"model": model_name, "api_key": config.api_key}
    if config.base_url:
        kwargs["base_url"] = config.base_url
    return config.chat_cls(**kwargs)


class ModelProvider:

    def __init__(
        self, model_provider: str, model_name: str):
        if model_provider not in PROVIDER_REGISTRY:
            raise ValueError(
                f"Unknown provider '{model_provider}'. Available: {list(PROVIDER_REGISTRY)}"
            )

        self.model_provider = model_provider
        self.model_name = model_name

    def get_llm_client(self) -> BaseChatModel:
        return _build_chat_model(self.model_provider, self.model_name)

            