import pytest
import wave

from app.providers.tts import ExternalVoiceProvider, PlaceholderVoiceProvider, create_voice_provider
from app.settings import Settings


def assert_valid_placeholder_wav(path):
    with wave.open(str(path), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getframerate() == 16000
        assert wav.getnframes() > 0


def test_create_voice_provider_defaults_to_placeholder(tmp_path):
    provider = create_voice_provider(Settings())
    output = tmp_path / "voice.wav"

    provider.synthesize("测试文案", "default-female", output)

    assert isinstance(provider, PlaceholderVoiceProvider)
    assert_valid_placeholder_wav(output)


def test_external_voice_provider_requires_api_key():
    with pytest.raises(RuntimeError, match="TTS_API_KEY"):
        create_voice_provider(Settings(voice_provider="cosyvoice", tts_api_key=None))


def test_external_voice_provider_writes_provider_placeholder(tmp_path):
    provider = create_voice_provider(Settings(voice_provider="cosyvoice", tts_api_key="test-key"))
    output = tmp_path / "voice.wav"

    provider.synthesize("测试文案", "custom:voice", output)

    assert isinstance(provider, ExternalVoiceProvider)
    assert_valid_placeholder_wav(output)
