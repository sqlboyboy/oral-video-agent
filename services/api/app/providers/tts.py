import shlex
import subprocess
import sys
import wave
from pathlib import Path
from typing import Protocol

import requests

from ..settings import Settings


class SpeechSynthesisProvider(Protocol):
    def synthesize(
        self,
        script: str,
        voice_id: str,
        output_path: Path,
        reference_audio: Path | None = None,
    ) -> Path:
        ...


class PlaceholderVoiceProvider:
    def _write_silent_wav(self, output_path: Path, duration_seconds: float = 1.0) -> None:
        sample_rate = 16000
        frame_count = int(sample_rate * duration_seconds)
        with wave.open(str(output_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(b"\x00\x00" * frame_count)

    def synthesize(
        self,
        script: str,
        voice_id: str,
        output_path: Path,
        reference_audio: Path | None = None,
    ) -> Path:
        self._write_silent_wav(output_path)
        return output_path


class ExternalVoiceProvider:
    def __init__(self, provider_name: str, api_key: str) -> None:
        self.provider_name = provider_name
        self.api_key = api_key

    def synthesize(
        self,
        script: str,
        voice_id: str,
        output_path: Path,
        reference_audio: Path | None = None,
    ) -> Path:
        # Provider SDK integration goes here (CosyVoice, MiniMax, Volcengine, etc.).
        PlaceholderVoiceProvider()._write_silent_wav(output_path)
        return output_path


class LocalCommandVoiceCloneProvider:
    def __init__(self, command_template: str) -> None:
        self.command_template = command_template

    def _quote(self, value: str | Path) -> str:
        text = str(value)
        if sys.platform == "win32":
            return '"' + text.replace('"', r'\"') + '"'
        return shlex.quote(text)

    def _decode_output(self, data: bytes | None) -> str:
        if not data:
            return ""
        for encoding in ("utf-8", "gbk", "mbcs"):
            try:
                return data.decode(encoding)
            except (LookupError, UnicodeDecodeError):
                continue
        return data.decode("utf-8", errors="replace")

    def _is_valid_wav(self, path: Path) -> bool:
        if not path.exists() or path.stat().st_size <= 44:
            return False
        try:
            with wave.open(str(path), "rb") as wav:
                return wav.getnframes() > 0 and wav.getframerate() > 0
        except wave.Error:
            return False

    def synthesize(
        self,
        script: str,
        voice_id: str,
        output_path: Path,
        reference_audio: Path | None = None,
    ) -> Path:
        if reference_audio is None:
            raise RuntimeError("声音克隆需要先上传并选择参考音色视频/音频")
        script_path = output_path.with_suffix(".txt")
        script_path.write_text(script, encoding="utf-8")
        command = self.command_template.format(
            script=self._quote(script_path),
            reference=self._quote(reference_audio),
            output=self._quote(output_path),
            voice_id=self._quote(voice_id),
        )
        result = subprocess.run(
            command,
            shell=True,
            check=False,
            capture_output=True,
        )
        if self._is_valid_wav(output_path):
            return output_path
        if result.returncode != 0:
            details = (
                self._decode_output(result.stderr)
                or self._decode_output(result.stdout)
                or ""
            ).strip()
            if len(details) > 1200:
                details = details[-1200:]
            raise RuntimeError(f"声音克隆引擎执行失败：{details or result.returncode}")
        if not self._is_valid_wav(output_path):
            raise RuntimeError("声音克隆引擎未生成输出音频")
        return output_path


class RemoteCosyVoiceProvider:
    def __init__(self, base_url: str, timeout_seconds: int = 1800) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def synthesize(
        self,
        script: str,
        voice_id: str,
        output_path: Path,
        reference_audio: Path | None = None,
    ) -> Path:
        if reference_audio is None:
            raise RuntimeError("声音克隆需要先上传并选择参考音色视频或音频")
        if not reference_audio.exists():
            raise RuntimeError(f"参考音色文件不存在: {reference_audio}")

        try:
            with reference_audio.open("rb") as reference_file:
                response = requests.post(
                    f"{self.base_url}/api/voice",
                    data={"text": script},
                    files={
                        "reference_file": (
                            reference_audio.name,
                            reference_file,
                            "audio/wav",
                        )
                    },
                    timeout=self.timeout_seconds,
                )
        except requests.RequestException as exc:
            raise RuntimeError(f"云端声音克隆服务连接失败: {exc}") from exc

        if not response.ok:
            details = response.text.strip()
            if len(details) > 1200:
                details = details[-1200:]
            raise RuntimeError(
                f"云端声音克隆失败 ({response.status_code}): {details or 'unknown error'}"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.content)
        if not LocalCommandVoiceCloneProvider("")._is_valid_wav(output_path):
            output_path.unlink(missing_ok=True)
            raise RuntimeError("云端声音克隆服务未返回有效 WAV 音频")
        return output_path


def create_voice_provider(settings: Settings) -> SpeechSynthesisProvider:
    if settings.voice_provider == "placeholder":
        return PlaceholderVoiceProvider()
    if settings.voice_provider in {"remote-cosyvoice", "cosyvoice-remote"}:
        return RemoteCosyVoiceProvider(
            settings.voice_base_url,
            settings.voice_timeout_seconds,
        )
    if settings.voice_provider in {"local-command", "voice-clone"}:
        if not settings.voice_clone_command:
            raise RuntimeError("VOICE_CLONE_COMMAND is required when VOICE_PROVIDER=local-command")
        return LocalCommandVoiceCloneProvider(settings.voice_clone_command)
    if not settings.tts_api_key:
        raise RuntimeError("TTS_API_KEY is required when VOICE_PROVIDER is not placeholder")
    return ExternalVoiceProvider(settings.voice_provider, settings.tts_api_key)


VoiceProvider = PlaceholderVoiceProvider
