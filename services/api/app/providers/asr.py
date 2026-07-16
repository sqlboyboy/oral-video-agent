from pathlib import Path
import re
from typing import Optional, Protocol

from ..pipeline.speech_timing import TimedSpeechToken
from ..settings import Settings


class SpeechRecognitionProvider(Protocol):
    def transcribe(self, audio_path: Optional[Path], source_hint: str = "") -> str:
        ...

    def transcribe_timed(
        self, audio_path: Optional[Path]
    ) -> list[TimedSpeechToken]:
        ...


class PlaceholderAsrProvider:
    def transcribe(self, audio_path: Optional[Path], source_hint: str = "") -> str:
        if source_hint:
            return f"这是从视频中识别出的口播内容示例。来源：{source_hint}。"
        return "这是从视频中识别出的口播内容示例：开头抓住用户注意力，中间讲清楚痛点和解决方案，结尾引导行动。"

    def transcribe_timed(
        self, audio_path: Optional[Path]
    ) -> list[TimedSpeechToken]:
        del audio_path
        return []


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
        self._timing_cache: dict[
            tuple[str, int, int], list[TimedSpeechToken]
        ] = {}

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
            vad_filter=False,
        )
        text = post_process_transcript("".join(seg.text for seg in segments).strip())
        return text if text else f"（未识别到语音内容，来源：{source_hint}）"

    def transcribe_timed(
        self, audio_path: Optional[Path]
    ) -> list[TimedSpeechToken]:
        if audio_path is None:
            return []
        path = Path(audio_path)
        if not path.exists() or not path.is_file():
            return []

        stat = path.stat()
        cache_key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
        cached = self._timing_cache.get(cache_key)
        if cached is not None:
            return list(cached)

        model = self._get_model()
        segments, _ = model.transcribe(
            str(path),
            language="zh",
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 250},
            word_timestamps=True,
            condition_on_previous_text=False,
        )
        tokens: list[TimedSpeechToken] = []
        for segment in segments:
            words = getattr(segment, "words", None) or []
            if words:
                for word in words:
                    start = getattr(word, "start", None)
                    end = getattr(word, "end", None)
                    text = str(getattr(word, "word", "") or "").strip()
                    if start is None or end is None or not text:
                        continue
                    start_value = max(0.0, float(start))
                    end_value = max(start_value, float(end))
                    if end_value > start_value:
                        tokens.append(
                            TimedSpeechToken(start_value, end_value, text)
                        )
                continue

            text = str(getattr(segment, "text", "") or "").strip()
            start = getattr(segment, "start", None)
            end = getattr(segment, "end", None)
            if start is None or end is None or not text:
                continue
            start_value = max(0.0, float(start))
            end_value = max(start_value, float(end))
            if end_value > start_value:
                tokens.append(TimedSpeechToken(start_value, end_value, text))

        tokens.sort(key=lambda item: (item.start, item.end))
        self._timing_cache[cache_key] = tokens
        while len(self._timing_cache) > 8:
            self._timing_cache.pop(next(iter(self._timing_cache)))
        return list(tokens)


def create_asr_provider(settings: Settings) -> SpeechRecognitionProvider:
    if settings.asr_provider == "faster-whisper":
        return FasterWhisperAsrProvider(settings.whisper_model)
    return PlaceholderAsrProvider()


AsrProvider = PlaceholderAsrProvider
