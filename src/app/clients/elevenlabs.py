from functools import lru_cache

from elevenlabs.client import AsyncElevenLabs

from src.config import settings


@lru_cache(maxsize=1)
def get_elevenlabs_client() -> AsyncElevenLabs:
    """Return the shared async client used for network-bound speech generation.

    This cache is an example convenience for the optional speech integration. The
    application lifespan exposes the resulting client to the HTTP adapter instead
    of recreating it for every response. The graph deliberately does not receive
    this client: speech bytes are transient transport data, not durable agent state.
    Remove this client and the route's audio branch when an inherited project does
    not need audio.
    """
    return AsyncElevenLabs(api_key=settings.ELEVENLABS_API_KEY)
