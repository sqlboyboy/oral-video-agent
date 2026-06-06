from pathlib import Path
from unittest.mock import MagicMock, patch

from app.providers.asr import FasterWhisperAsrProvider, PlaceholderAsrProvider, create_asr_provider, post_process_transcript
from app.settings import Settings


def test_create_asr_provider_defaults_to_placeholder():
    provider = create_asr_provider(Settings(asr_provider="placeholder"))

    assert isinstance(provider, PlaceholderAsrProvider)
    assert "识别出的口播内容示例" in provider.transcribe(None)


def test_create_asr_provider_uses_faster_whisper_config(tmp_path):
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"audio")

    provider = create_asr_provider(Settings(asr_provider="faster-whisper", whisper_model="medium"))

    assert isinstance(provider, FasterWhisperAsrProvider)
    assert provider.model_name == "medium"


def test_faster_whisper_provider_falls_back_for_link_only_tasks():
    provider = create_asr_provider(Settings(asr_provider="faster-whisper", whisper_model="small"))

    result = provider.transcribe(None, "https://example.test/video")
    assert "来源：https://example.test/video" in result


def test_faster_whisper_transcribes_real_audio(tmp_path):
    """FasterWhisperAsrProvider calls WhisperModel.transcribe with the audio path."""
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"fake-audio")

    mock_segment = MagicMock()
    mock_segment.text = "测试识别结果"
    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([mock_segment], MagicMock())

    provider = FasterWhisperAsrProvider("small")
    with patch("faster_whisper.WhisperModel", return_value=mock_model):
        provider._model = mock_model
        result = provider.transcribe(audio, "voice.wav")

    assert "测试识别结果" in result
    mock_model.transcribe.assert_called_once()


def test_post_process_transcript_removes_adjacent_repeats():
    text = (
        "大家好,这是我的第一条口播视频,我妈非让我拍的,"
        "我妈非让我拍的,说是可以提高语言表达能力,"
        "说是可以提高语言表达能力,加油,加油,加油,加油"
    )

    result = post_process_transcript(text)

    assert result == "大家好，这是我的第一条口播视频，我妈非让我拍的，说是可以提高语言表达能力，加油"
