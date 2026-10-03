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

    # Opik
    COMET_PROJECT: Optional[str] = Field(
        default="Metadosis",
        description="AI that learns from masters and passes on the knowledge to the next generation - metadosis.",
    )
    OPIK_CONFIG_PATH: Optional[str] = "/tmp/.opik.config"

    # MongoDB 
    MONGODB_CONNECTION_STRING: str

settings = Settings()