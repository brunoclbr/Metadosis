# Application Clients

This package owns adapters for external services used by the application. Backend and agent modules consume these clients; provider-specific connection and request details stay here.

## Current clients

- `model_providers.py` — creates and caches LangChain chat models for Anthropic, OpenAI, and Gemini. Models are selected by provider and model name.
- `vision.py` — compares transient BEFORE/AFTER screen frames with a configured multimodal model and returns a structured `ScreenChange`. Images are encoded only for the provider request and are not persisted here.
- `mongodb.py` — creates the MongoDB client used by the FastAPI application. The application lifespan owns this connection pool and closes it during shutdown.
- `elevenlabs.py` — provides the shared asynchronous ElevenLabs client used for transient speech generation. Audio bytes remain transport data and are not agent state.

## Boundaries

- Credentials and connection strings come from `src.config.settings`; never hardcode them.
- Clients handle external-service communication, not domain or workflow decisions.
- Resource-owning clients must be created and closed by the application lifespan.
- Screen images, generated audio, and provider request payloads must not be logged or persisted by this package.
