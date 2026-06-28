import wave

import pytest

from app.providers.tts import (
    ExternalVoiceProvider,
    PlaceholderVoiceProvider,
    RemoteCosyVoiceProvider,
    create_voice_provider,
)
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


def test_create_remote_cosyvoice_provider_without_api_key():
    provider = create_voice_provider(
        Settings(
            voice_provider="remote-cosyvoice",
            voice_base_url="http://127.0.0.1:16010",
            tts_api_key=None,
        )
    )

    assert isinstance(provider, RemoteCosyVoiceProvider)


def test_remote_cosyvoice_uploads_reference_and_writes_wav(tmp_path, monkeypatch):
    reference = tmp_path / "reference.wav"
    output = tmp_path / "voice.wav"
    PlaceholderVoiceProvider()._write_silent_wav(reference)
    expected = tmp_path / "expected.wav"
    PlaceholderVoiceProvider()._write_silent_wav(expected)

    class Response:
        ok = True
        content = expected.read_bytes()

    def fake_post(url, data, files, timeout):
        assert url == "http://voice.example/api/voice"
        assert data == {"text": "第一句\n第二句"}
        assert files["reference_file"][0] == "reference.wav"
        assert timeout == 321
        return Response()

    monkeypatch.setattr("app.providers.tts.requests.post", fake_post)
    provider = RemoteCosyVoiceProvider("http://voice.example/", timeout_seconds=321)

    provider.synthesize("第一句\n第二句", "custom:test", output, reference)

    assert_valid_placeholder_wav(output)
