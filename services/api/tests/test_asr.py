from app.providers.asr import FasterWhisperAsrProvider, PlaceholderAsrProvider, create_asr_provider
from app.settings import Settings


def test_create_asr_provider_defaults_to_placeholder():
    provider = create_asr_provider(Settings())

    assert isinstance(provider, PlaceholderAsrProvider)
    assert "识别出的口播内容示例" in provider.transcribe(None)


def test_create_asr_provider_uses_faster_whisper_config(tmp_path):
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"audio")

    provider = create_asr_provider(Settings(asr_provider="faster-whisper", whisper_model="medium"))
    result = provider.transcribe(audio)

    assert isinstance(provider, FasterWhisperAsrProvider)
    assert "faster-whisper:medium" in result
    assert "voice.wav" in result


def test_faster_whisper_provider_falls_back_for_link_only_tasks():
    provider = create_asr_provider(Settings(asr_provider="faster-whisper", whisper_model="small"))

    assert "来源：https://example.test/video" in provider.transcribe(None, "https://example.test/video")
