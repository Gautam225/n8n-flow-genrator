from pathlib import Path
from typing import List, Optional, Union
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class LLMSettings(BaseSettings):
    """LLM configuration settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=[".env", str(_PROJECT_ROOT / ".env")],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # OpenRouter API Keys (4-Key Pool)
    OPENROUTER_API_KEY_1: Optional[str] = None
    OPENROUTER_API_KEY_2: Optional[str] = None
    OPENROUTER_API_KEY_3: Optional[str] = None
    OPENROUTER_API_KEY_4: Optional[str] = None

    # OpenRouter Model Selection Strategy
    OPENROUTER_MODEL: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    OPENROUTER_FALLBACK_MODELS: Union[List[str], str] = Field(
        default_factory=lambda: [
            "liquid/lfm-2.5-2.6b:free",
            "nvidia/nemotron-3.5-lightning:free",
            "cohere/north-mini-code:free",
            "google/gemma-4-26b-a4b-it:free",
            "google/gemma-4-31b-it:free",
        ]
    )

    # OpenRouter Header Metadata
    OPENROUTER_SITE_URL: str = "http://localhost:5678"
    OPENROUTER_APP_NAME: str = "n8n-workflow-ai-generator"

    # Groq API Configuration (Optional Fallback)
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_FALLBACK_MODELS: Union[List[str], str] = Field(
        default_factory=lambda: [
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
        ]
    )

    # Operational Parameters
    LLM_REQUEST_TIMEOUT: float = 55.0
    LLM_MAX_RETRIES: int = 2
    LLM_BASE_BACKOFF_SEC: float = 1.0
    TOTAL_GENERATION_DEADLINE: float = 95.0

    @field_validator("OPENROUTER_FALLBACK_MODELS", mode="after")
    @classmethod
    def parse_fallback_models(cls, v) -> List[str]:
        if isinstance(v, str):
            return [m.strip() for m in v.split(",") if m.strip()]
        return v

    @field_validator("GROQ_FALLBACK_MODELS", mode="after")
    @classmethod
    def parse_groq_fallback_models(cls, v) -> List[str]:
        if isinstance(v, str):
            return [m.strip() for m in v.split(",") if m.strip()]
        return v

    def get_openrouter_keys(self) -> List[tuple[str, str]]:
        """Returns list of (alias, key_value) for all non-empty configured OpenRouter keys."""
        candidates = [
            ("OPENROUTER_KEY_1", self.OPENROUTER_API_KEY_1),
            ("OPENROUTER_KEY_2", self.OPENROUTER_API_KEY_2),
            ("OPENROUTER_KEY_3", self.OPENROUTER_API_KEY_3),
            ("OPENROUTER_KEY_4", self.OPENROUTER_API_KEY_4),
        ]
        return [(alias, key.strip()) for alias, key in candidates if key and key.strip()]
