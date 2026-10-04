from pydantic import Field
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    
    model_config = SettingsConfigDict(env_file=".env",
                                    extra="ignore",
                                    env_file_encoding="utf-8")

    # Model Provider & name MUST be in .env Obviously an api key as well, but we won't to avoid 
    # initialization erros if we still have not gotten the key.
    MODEL_PROVIDER: str
    MODEL_NAME: str

    # OpenAI
    OPENAI_API_KEY: Optional[str] = None

    #Anthropic
    ANTHROPIC_API_KEY: Optional[str] = None

    # Gemini
    GEMINI_API_KEY: Optional[str] = None

    
    # Third party API keys

    COMET_API_KEY: str
    ELEVENLABS_API_KEY: str 

    # Elevenlabs
    ELEVENLABS_VOICE_ID: Optional[str] = "IKne3meq5aSn9XLyUdCD"
    ELEVENLABS_MODEL_ID: Optional[str] = "eleven_flash_v2_5"
    ELEVENLABS_WEBHOOK_SECRET: Optional[str] = None
    # Shared with the ElevenLabs `load_expert_knowledge` tool so captured
    # expertise is not readable by anyone holding a Process UUID. Server-only:
    # never expose it through a NEXT_PUBLIC_ variable or the browser.
    TEACHER_CONTEXT_SECRET: Optional[str] = None
    # Allow already-started visual analysis/persistence requests to settle before
    # post-call distillation takes its final evidence snapshot.
    BRAIN_EVIDENCE_SETTLEMENT_SECONDS: float = Field(default=5.0, ge=0, le=60)

    # Opik
    COMET_PROJECT: Optional[str] = Field(
        default="Metadosis",
        description="AI that learns from masters and passes on the knowledge to the next generation - metadosis.",
    )
    OPIK_CONFIG_PATH: Optional[str] = "/tmp/.opik.config"

    # MongoDB 
    MONGODB_CONNECTION_STRING: str

    # PostgreSQL
    DATABASE_URL: str = "postgresql://metadosis:metadosis@localhost:5432/metadosis"

    # Neo4j Aura. Optional so capture remains available when the derived graph
    # is not configured; all four values are server-only.
    NEO4J_URI: Optional[str] = None
    NEO4J_USERNAME: Optional[str] = None
    NEO4J_PASSWORD: Optional[str] = None
    NEO4J_DATABASE: str = "neo4j"

settings = Settings()