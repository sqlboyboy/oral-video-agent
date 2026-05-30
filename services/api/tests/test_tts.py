import pytest

from app.providers.tts import ExternalVoiceProvider, PlaceholderVoiceProvider, create_voice_provider
from app.settings import Settings


def test_create_voice_provider_defaults_to_placeholder(tmp_path):
    provider = create_voice_provider(Settings())
    output = tmp_path / "voice.wav"

    provider.synthesize("测试文案", "default-female", output)

    assert isinstance(provider, PlaceholderVoiceProvider)
    assert output.read_bytes() == b"PLACEHOLDER_AUDIO_WAV"


def test_external_voice_provider_requires_api_key():
    with pytest.raises(RuntimeError, match="TTS_API_KEY"):
        create_voice_provider(Settings(voice_provider="cosyvoice", tts_api_key=None))


def test_external_voice_provider_writes_provider_placeholder(tmp_path):
    provider = create_voice_provider(Settings(voice_provider="cosyvoice", tts_api_key="test-key"))
    output = tmp_path / "voice.wav"

    provider.synthesize("测试文案", "custom:voice", output)

    assert isinstance(provider, ExternalVoiceProvider)
    assert output.read_bytes() == b"PLACEHOLDER_COSYVOICE_AUDIO"
