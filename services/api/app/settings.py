import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    rewrite_provider: str = os.getenv("REWRITE_PROVIDER", "placeholder")
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-6")
    voice_provider: str = os.getenv("VOICE_PROVIDER", "placeholder")
    tts_api_key: str | None = os.getenv("TTS_API_KEY")


def get_settings() -> Settings:
    return Settings()
