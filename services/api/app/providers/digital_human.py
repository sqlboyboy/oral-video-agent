import os
import json
import shutil
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Protocol

import requests
from imageio_ffmpeg import get_ffmpeg_exe

from ..models import RenderOptions
from ..settings import Settings


def _run_command(
    command,
    *,
    cwd: Path | None = None,
    shell: bool = False,
    cancel_event: threading.Event | None = None,
) -> None:
    env = os.environ.copy()
    env.setdefault("IMAGEIO_FFMPEG_EXE", get_ffmpeg_exe())
    env.setdefault("FFMPEG_BINARY", get_ffmpeg_exe())
    process = subprocess.Popen(
        command,
        cwd=cwd,
        shell=shell,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output_lines: list[str] = []
    while process.poll() is None:
        if process.stdout is not None:
            line = process.stdout.readline()
            if line:
                output_lines.append(line.rstrip())
                output_lines = output_lines[-80:]
        if cancel_event is not None and cancel_event.is_set():
            process.terminate()
            time.sleep(0.5)
            if process.poll() is None:
                process.kill()
            raise RuntimeError("用户已停止生成")
        time.sleep(0.2)
    if process.stdout is not None:
        for line in process.stdout.readlines():
            output_lines.append(line.rstrip())
        output_lines = output_lines[-80:]
    if process.returncode != 0:
        detail = "\n".join(output_lines[-20:])
        raise RuntimeError(f"高清模式执行失败，退出码 {process.returncode}:\n{detail}")


class DigitalHumanProvider(Protocol):
    def render(
        self,
        *,
        reference_video: Path | None,
        driving_audio: Path,
        script: str,
        options: RenderOptions,
        output_path: Path,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        ...


class HighQualityDigitalHumanProvider:
    def __init__(
        self,
        *,
        repo_dir: str,
        python_executable: str,
        detector: str,
        detector_model: str | None = None,
        command_template: str | None = None,
    ) -> None:
        self.repo_dir = Path(repo_dir)
        self.python_executable = python_executable
        self.detector = detector.strip().lower()
        self.detector_model = Path(detector_model) if detector_model else None
        self.command_template = command_template

    def _quote(self, value: str | Path) -> str:
        text = str(value)
        if sys.platform == "win32":
            return '"' + text.replace('"', r'\"') + '"'
        return shlex.quote(text)

    def render(
        self,
        *,
        reference_video: Path | None,
        driving_audio: Path,
        script: str,
        options: RenderOptions,
        output_path: Path,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        if reference_video is None:
            raise RuntimeError("高清模式需要先选择一条真人参考视频。")
        if self.detector in {"yunet", "opencv-yunet"} and (
            self.detector_model is None or not self.detector_model.exists()
        ):
            raise RuntimeError("OpenCV YuNet 模式需要配置检测模型路径。")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        if self.command_template:
            script_path = output_path.with_suffix(".script.txt")
            script_path.write_text(script, encoding="utf-8")
            command = self.command_template.format(
                repo=self._quote(self.repo_dir),
                reference=self._quote(reference_video),
                audio=self._quote(driving_audio),
                script=self._quote(script_path),
                output=self._quote(output_path),
                detector=self._quote(self.detector),
                detector_model=self._quote(self.detector_model or ""),
                motion=self._quote(options.motion_mode),
                expression=self._quote(options.expression_mode),
            )
            _run_command(command, shell=True, cancel_event=cancel_event)
        else:
            adapter = Path(__file__).resolve().parents[2] / "tools" / "liveportrait_commercial.py"
            command = [
                self.python_executable,
                str(adapter),
                "--repo",
                str(self.repo_dir),
                "--reference",
                str(reference_video),
                "--audio",
                str(driving_audio),
                "--output",
                str(output_path),
                "--detector",
                self.detector,
            ]
            if self.detector_model is not None:
                command.extend(["--detector-model", str(self.detector_model)])
            _run_command(command, cwd=adapter.parent, cancel_event=cancel_event)

        if not output_path.exists():
            raise RuntimeError("高清模式未生成输出视频。")
        return output_path


class SimpleMouthSyncProvider:
    def __init__(self, *, python_executable: str | None = None) -> None:
        self.python_executable = python_executable or sys.executable

    def render(
        self,
        *,
        reference_video: Path | None,
        driving_audio: Path,
        script: str,
        options: RenderOptions,
        output_path: Path,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        if reference_video is None:
            raise RuntimeError("轻量口型模式需要先选择一条真人参考视频。")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(reference_video, output_path)

        if not output_path.exists():
            raise RuntimeError("轻量口型模式未生成输出视频。")
        return output_path


class Wav2LipOnnxProvider:
    def __init__(
        self,
        *,
        model_path: str | None,
        command_template: str | None = None,
        fallback: DigitalHumanProvider | None = None,
        python_executable: str | None = None,
        blend_enabled: bool = True,
        blend_preset: str = "balanced",
        aperture_atlas_source: str | None = None,
        aperture_atlas_strength: float = 0.5,
        aperture_energy_threshold: float = 0.24,
        aperture_min_ratio: float = 0.07,
        aperture_max_ratio: float = 0.36,
        aperture_attack: float = 1.0,
        aperture_release: float = 1.0,
        quality_diagnostics_enabled: bool = True,
        quality_diagnostics_sample_stride: int = 2,
        quality_diagnostics_max_frames: int = 240,
    ) -> None:
        self.model_path = Path(model_path) if model_path else None
        self.command_template = command_template
        self.fallback = fallback or SimpleMouthSyncProvider(python_executable=python_executable)
        self.python_executable = python_executable or sys.executable
        self.blend_enabled = blend_enabled
        self.blend_preset = blend_preset.strip().lower()
        self.aperture_atlas_source = Path(aperture_atlas_source) if aperture_atlas_source else None
        self.aperture_atlas_strength = max(0.0, min(float(aperture_atlas_strength), 1.0))
        self.aperture_energy_threshold = max(0.0, min(float(aperture_energy_threshold), 0.85))
        self.aperture_min_ratio = max(0.0, min(float(aperture_min_ratio), 0.8))
        self.aperture_max_ratio = max(self.aperture_min_ratio, min(float(aperture_max_ratio), 0.8))
        self.aperture_attack = max(0.0, min(float(aperture_attack), 1.0))
        self.aperture_release = max(0.0, min(float(aperture_release), 1.0))
        self.quality_diagnostics_enabled = quality_diagnostics_enabled
        self.quality_diagnostics_sample_stride = max(1, int(quality_diagnostics_sample_stride))
        self.quality_diagnostics_max_frames = max(0, int(quality_diagnostics_max_frames))

    def _quote(self, value: str | Path) -> str:
        text = str(value)
        if sys.platform == "win32":
            return '"' + text.replace('"', r'\"') + '"'
        return shlex.quote(text)

    def has_model(self) -> bool:
        return bool(self.model_path and self.model_path.exists() and self.model_path.is_file())

    def render(
        self,
        *,
        reference_video: Path | None,
        driving_audio: Path,
        script: str,
        options: RenderOptions,
        output_path: Path,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        if not self.has_model():
            return self.fallback.render(
                reference_video=reference_video,
                driving_audio=driving_audio,
                script=script,
                options=options,
                output_path=output_path,
                cancel_event=cancel_event,
            )
        if reference_video is None:
            raise RuntimeError("Wav2Lip-ONNX 模式需要先选择一条真人参考视频。")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        wav2lip_output = (
            output_path.with_name(f"{output_path.stem}_wav2lip_raw{output_path.suffix}")
            if self.blend_enabled
            else output_path
        )
        if self.command_template:
            command = self.command_template.format(
                model=self._quote(self.model_path or ""),
                reference=self._quote(reference_video),
                audio=self._quote(driving_audio),
                output=self._quote(wav2lip_output),
            )
            _run_command(command, shell=True, cancel_event=cancel_event)
        else:
            adapter = Path(__file__).resolve().parents[2] / "tools" / "wav2lip_onnx.py"
            command = [
                self.python_executable,
                str(adapter),
                "--model",
                str(self.model_path),
                "--reference",
                str(reference_video),
                "--audio",
                str(driving_audio),
                "--output",
                str(wav2lip_output),
            ]
            _run_command(command, cwd=adapter.parent, cancel_event=cancel_event)

        if self.blend_enabled:
            self._blend_mouth_only(
                reference_video=reference_video,
                generated_video=wav2lip_output,
                driving_audio=driving_audio,
                options=options,
                output_path=output_path,
                cancel_event=cancel_event,
            )
            if self.quality_diagnostics_enabled:
                self._diagnose_mouth_quality(
                    driving_audio=driving_audio,
                    output_path=output_path,
                    cancel_event=cancel_event,
                )

        if not output_path.exists():
            raise RuntimeError("Wav2Lip-ONNX 模式未生成输出视频。")
        return output_path

    def _mouth_state_debug_path(self, output_path: Path) -> Path:
        return output_path.with_suffix(".mouth_state.json")

    def _mouth_diagnosis_path(self, output_path: Path) -> Path:
        return output_path.with_suffix(".mouth_diagnosis.json")

    def _blend_mouth_only(
        self,
        *,
        reference_video: Path,
        generated_video: Path,
        driving_audio: Path,
        options: RenderOptions | None,
        output_path: Path,
        cancel_event: threading.Event | None,
    ) -> None:
        blender = Path(__file__).resolve().parents[2] / "tools" / "blend_wav2lip_result.py"
        command = [
            self.python_executable,
            str(blender),
            "--source",
            str(reference_video),
            "--generated",
            str(generated_video),
            "--audio",
            str(driving_audio),
            "--dynamic-preserve",
            "--open-closed-priority",
            "--open-shape-trigger",
            "0.250",
            "--open-shape-openness",
            "0.780",
            "--open-generated-priority",
            "--output",
            str(output_path),
            "--mouth-state-debug-output",
            str(self._mouth_state_debug_path(output_path)),
        ]
        if self.blend_preset in {"seamless", "natural", "edge"}:
            command.append("--seamless-edge")
        if self.blend_preset in {"detail", "detailed", "commercial"}:
            command.extend(["--seamless-edge", "--detail-restore"])
        if self.blend_preset in {"soft-cavity", "least-black"}:
            command.append("--soft-cavity")
        if self.blend_preset in {"upper-cavity", "upper-lift"}:
            command.append("--upper-cavity-lift")
        aperture_enabled = getattr(options, "mouth_aperture_enabled", None)
        aperture_strength = self._option_float(
            getattr(options, "mouth_aperture_strength", None),
            self.aperture_atlas_strength,
            0.0,
            1.0,
        )
        if aperture_enabled is False:
            aperture_strength = 0.0
        elif aperture_enabled is True and aperture_strength <= 0:
            aperture_strength = 0.5
        aperture_energy_threshold = self._option_float(
            getattr(options, "mouth_aperture_energy_threshold", None),
            self.aperture_energy_threshold,
            0.0,
            0.85,
        )
        aperture_min_ratio = self._option_float(
            getattr(options, "mouth_aperture_min_ratio", None),
            self.aperture_min_ratio,
            0.0,
            0.8,
        )
        aperture_max_ratio = self._option_float(
            getattr(options, "mouth_aperture_max_ratio", None),
            self.aperture_max_ratio,
            aperture_min_ratio,
            0.8,
        )
        aperture_attack = self._option_float(
            getattr(options, "mouth_aperture_attack", None),
            self.aperture_attack,
            0.0,
            1.0,
        )
        aperture_release = self._option_float(
            getattr(options, "mouth_aperture_release", None),
            self.aperture_release,
            0.0,
            1.0,
        )
        aperture_atlas_source = self.aperture_atlas_source
        if aperture_atlas_source is None and aperture_strength > 0:
            aperture_atlas_source = reference_video
        if aperture_atlas_source is not None and aperture_strength > 0:
            command.extend([
                "--aperture-atlas-source",
                str(aperture_atlas_source),
                "--aperture-atlas-strength",
                f"{aperture_strength:.3f}",
                "--aperture-energy-threshold",
                f"{aperture_energy_threshold:.3f}",
                "--aperture-min-ratio",
                f"{aperture_min_ratio:.3f}",
                "--aperture-max-ratio",
                f"{aperture_max_ratio:.3f}",
                "--aperture-attack",
                f"{aperture_attack:.3f}",
                "--aperture-release",
                f"{aperture_release:.3f}",
            ])
        _run_command(command, cwd=blender.parent, cancel_event=cancel_event)

    def _diagnose_mouth_quality(
        self,
        *,
        driving_audio: Path,
        output_path: Path,
        cancel_event: threading.Event | None,
    ) -> None:
        diagnoser = Path(__file__).resolve().parents[2] / "tools" / "diagnose_mouth_naturalness.py"
        diagnosis_path = self._mouth_diagnosis_path(output_path)
        command = [
            self.python_executable,
            str(diagnoser),
            "--video",
            str(output_path),
            "--audio",
            str(driving_audio),
            "--mouth-state",
            str(self._mouth_state_debug_path(output_path)),
            "--sample-stride",
            str(self.quality_diagnostics_sample_stride),
            "--max-frames",
            str(self.quality_diagnostics_max_frames),
            "--output",
            str(diagnosis_path),
        ]
        try:
            _run_command(command, cwd=diagnoser.parent, cancel_event=cancel_event)
        except RuntimeError as exc:
            if cancel_event is not None and cancel_event.is_set():
                raise
            self._write_mouth_diagnosis_failure(diagnosis_path, str(exc))

    def _write_mouth_diagnosis_failure(self, diagnosis_path: Path, error: str) -> None:
        diagnosis_path.parent.mkdir(parents=True, exist_ok=True)
        diagnosis_path.write_text(
            json.dumps(
                {
                    "verdict": "diagnostics_unavailable",
                    "warnings": ["Internal mouth naturalness diagnostics did not complete."],
                    "error": error,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _option_float(self, value: float | None, fallback: float, minimum: float, maximum: float) -> float:
        if value is None:
            value = fallback
        return max(minimum, min(float(value), maximum))


class HeyGemProvider:
    def __init__(
        self,
        *,
        base_url: str,
        data_dir: str,
        timeout_seconds: int,
        fallback: DigitalHumanProvider | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.data_dir = Path(data_dir)
        self.timeout_seconds = max(30, timeout_seconds)
        self.fallback = fallback

    def _copy_inputs(self, reference_video: Path, driving_audio: Path, output_path: Path) -> tuple[Path, Path, Path]:
        task_dir = self.data_dir / output_path.stem
        task_dir.mkdir(parents=True, exist_ok=True)
        video_path = task_dir / f"input{reference_video.suffix.lower() or '.mp4'}"
        audio_path = task_dir / f"audio{driving_audio.suffix.lower() or '.wav'}"
        result_path = task_dir / "result.mp4"
        shutil.copy2(reference_video, video_path)
        shutil.copy2(driving_audio, audio_path)
        return video_path, audio_path, result_path

    def _submit_payload(self, video_path: Path, audio_path: Path, result_path: Path) -> dict:
        return {
            "audio_url": str(audio_path),
            "video_url": str(video_path),
            "code": result_path.stem,
            "chaofen": 0,
            "watermark_switch": 0,
            "pn": 1,
        }

    def render(
        self,
        *,
        reference_video: Path | None,
        driving_audio: Path,
        script: str,
        options: RenderOptions,
        output_path: Path,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        if reference_video is None:
            raise RuntimeError("HeyGem 模式需要先选择一条真人参考视频。")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        video_path, audio_path, result_path = self._copy_inputs(reference_video, driving_audio, output_path)

        try:
            response = requests.post(
                f"{self.base_url}/submit",
                json=self._submit_payload(video_path, audio_path, result_path),
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            if self.fallback is not None:
                return self.fallback.render(
                    reference_video=reference_video,
                    driving_audio=driving_audio,
                    script=script,
                    options=options,
                    output_path=output_path,
                    cancel_event=cancel_event,
                )
            raise RuntimeError(f"HeyGem 服务不可用，请先启动本地 HeyGem 服务：{exc}") from exc

        code = str(data.get("code") or data.get("data", {}).get("code") or result_path.stem)
        deadline = time.time() + self.timeout_seconds
        last_response = data
        while time.time() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("用户已停止生成")
            time.sleep(2)
            try:
                query = requests.get(f"{self.base_url}/query", params={"code": code}, timeout=10)
                query.raise_for_status()
                last_response = query.json()
            except Exception:
                continue

            text = str(last_response).lower()
            if "fail" in text or "error" in text:
                raise RuntimeError(f"HeyGem 生成失败：{last_response}")

            candidates = [
                last_response.get("data", {}).get("result"),
                last_response.get("data", {}).get("result_url"),
                last_response.get("data", {}).get("video_url"),
                last_response.get("result"),
                last_response.get("result_url"),
                str(result_path),
            ]
            for candidate in candidates:
                if not candidate:
                    continue
                candidate_path = Path(str(candidate))
                if candidate_path.exists() and candidate_path.suffix.lower() == ".mp4":
                    shutil.copy2(candidate_path, output_path)
                    return output_path

        raise RuntimeError(f"HeyGem 生成超时：{last_response}")


def create_digital_human_provider(settings: Settings) -> DigitalHumanProvider:
    provider = settings.digital_human_provider.strip().lower()
    wav2lip_provider = Wav2LipOnnxProvider(
        model_path=settings.wav2lip_onnx_model,
        command_template=settings.wav2lip_onnx_command,
        blend_enabled=settings.wav2lip_blend_enabled,
        blend_preset=settings.wav2lip_blend_preset,
        aperture_atlas_source=settings.wav2lip_aperture_atlas_source,
        aperture_atlas_strength=settings.wav2lip_aperture_atlas_strength,
        aperture_energy_threshold=settings.wav2lip_aperture_energy_threshold,
        aperture_min_ratio=settings.wav2lip_aperture_min_ratio,
        aperture_max_ratio=settings.wav2lip_aperture_max_ratio,
        aperture_attack=settings.wav2lip_aperture_attack,
        aperture_release=settings.wav2lip_aperture_release,
        quality_diagnostics_enabled=settings.wav2lip_quality_diagnostics_enabled,
        quality_diagnostics_sample_stride=settings.wav2lip_quality_diagnostics_sample_stride,
        quality_diagnostics_max_frames=settings.wav2lip_quality_diagnostics_max_frames,
    )
    if provider in {"heygem", "heygem-local", "duix-heygem"}:
        return HeyGemProvider(
            base_url=settings.heygem_base_url,
            data_dir=settings.heygem_data_dir,
            timeout_seconds=settings.heygem_timeout_seconds,
            fallback=wav2lip_provider,
        )
    if provider in {"wav2lip-onnx", "wav2lip"}:
        return wav2lip_provider
    if provider in {"placeholder", "simple-mouth-sync", "simple-mouth", "lightweight-mouth", "liveportrait-commercial"}:
        return SimpleMouthSyncProvider()
    return HighQualityDigitalHumanProvider(
        repo_dir=settings.liveportrait_repo,
        python_executable=settings.liveportrait_python,
        detector=settings.liveportrait_detector,
        detector_model=settings.liveportrait_detector_model,
        command_template=settings.liveportrait_command,
    )

