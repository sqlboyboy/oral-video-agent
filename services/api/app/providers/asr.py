from pathlib import Path
from typing import Optional, Protocol

from ..settings import Settings


class SpeechRecognitionProvider(Protocol):
    def transcribe(self, audio_path: Optional[Path], source_hint: str = "") -> str:
        ...


class PlaceholderAsrProvider:
    def transcribe(self, audio_path: Optional[Path], source_hint: str = "") -> str:
        if source_hint:
            return f"这是从视频中识别出的口播内容示例。来源：{source_hint}。"
        return "这是从视频中识别出的口播内容示例：开头抓住用户注意力，中间讲清楚痛点和解决方案，结尾引导行动。"


class FasterWhisperAsrProvider:
    def __init__(self, model: str) -> None:
        self.model = model

    def transcribe(self, audio_path: Optional[Path], source_hint: str = "") -> str:
        if audio_path is None:
            return PlaceholderAsrProvider().transcribe(audio_path, source_hint)
        # Real faster-whisper integration will load the configured model and transcribe audio_path.
        return f"[faster-whisper:{self.model}] 待接入真实识别结果：{audio_path.name}"


def create_asr_provider(settings: Settings) -> SpeechRecognitionProvider:
    if settings.asr_provider == "faster-whisper":
        return FasterWhisperAsrProvider(settings.whisper_model)
    return PlaceholderAsrProvider()


AsrProvider = PlaceholderAsrProvider
