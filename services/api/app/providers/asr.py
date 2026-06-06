from pathlib import Path
import re
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


def post_process_transcript(text: str) -> str:
    chunks = [
        chunk.strip(" ，,。.!！?？")
        for chunk in re.split(r"[，,。.!！?？；;\n]+", text)
        if chunk.strip(" ，,。.!！?？")
    ]
    cleaned: list[str] = []
    for chunk in chunks:
        if cleaned and cleaned[-1] == chunk:
            continue
        cleaned.append(chunk)

    while len(cleaned) > 3 and cleaned[-1] == cleaned[-2] == cleaned[-3]:
        repeated = cleaned[-1]
        while len(cleaned) > 1 and cleaned[-2] == repeated:
            cleaned.pop()

    return "，".join(cleaned)


class FasterWhisperAsrProvider:
    def __init__(self, model: str) -> None:
        self.model_name = model
        self._model = None  # lazy load on first use

    def _get_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            # Use CPU with int8 quantization for machines without NVIDIA GPU
            self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
        return self._model

    def transcribe(self, audio_path: Optional[Path], source_hint: str = "") -> str:
        if audio_path is None:
            return PlaceholderAsrProvider().transcribe(audio_path, source_hint)

        model = self._get_model()
        segments, info = model.transcribe(
            str(audio_path),
            language="zh",
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        text = post_process_transcript("".join(seg.text for seg in segments).strip())
        return text if text else f"（未识别到语音内容，来源：{source_hint}）"


def create_asr_provider(settings: Settings) -> SpeechRecognitionProvider:
    if settings.asr_provider == "faster-whisper":
        return FasterWhisperAsrProvider(settings.whisper_model)
    return PlaceholderAsrProvider()


AsrProvider = PlaceholderAsrProvider
