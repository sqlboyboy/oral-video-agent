from pathlib import Path
from typing import Protocol

from ..settings import Settings


class SpeechSynthesisProvider(Protocol):
    def synthesize(self, script: str, voice_id: str, output_path: Path) -> Path:
        ...


class PlaceholderVoiceProvider:
    def synthesize(self, script: str, voice_id: str, output_path: Path) -> Path:
        output_path.write_bytes(b"PLACEHOLDER_AUDIO_WAV")
        return output_path


class ExternalVoiceProvider:
    def __init__(self, provider_name: str, api_key: str) -> None:
        self.provider_name = provider_name
        self.api_key = api_key

    def synthesize(self, script: str, voice_id: str, output_path: Path) -> Path:
        # Provider SDK integration goes here (CosyVoice, MiniMax, Volcengine, etc.).
        output_path.write_bytes(f"PLACEHOLDER_{self.provider_name.upper()}_AUDIO".encode("utf-8"))
        return output_path


def create_voice_provider(settings: Settings) -> SpeechSynthesisProvider:
    if settings.voice_provider == "placeholder":
        return PlaceholderVoiceProvider()
    if not settings.tts_api_key:
        raise RuntimeError("TTS_API_KEY is required when VOICE_PROVIDER is not placeholder")
    return ExternalVoiceProvider(settings.voice_provider, settings.tts_api_key)


VoiceProvider = PlaceholderVoiceProvider
