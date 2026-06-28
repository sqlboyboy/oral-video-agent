r"""Local CosyVoice zero-shot voice clone wrapper.

Expected engine layout:
  <workspace>\engines\CosyVoice          # cloned CosyVoice repository
  <workspace>\models\CosyVoice-300M-25Hz # downloaded model directory

The script accepts an audio or video reference. Video/audio decoding is done
with PyAV so the main app does not require a system ffmpeg binary.
"""

from __future__ import annotations

import argparse
import os
import sys
import wave
from pathlib import Path

import av
import numpy as np


DIRECT_WAV_SUFFIXES = {".wav"}
TRANSCODE_SUFFIXES = {".mp3", ".m4a", ".aac", ".flac", ".mp4", ".mov", ".mkv", ".webm"}
TTS_PUNCTUATION = "，。！？；："


def _read_script(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise SystemExit("script is empty")
    return text


def _prepare_tts_text(text: str) -> str:
    lines = ["".join(line.split()) for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        raise SystemExit("script is empty")
    # The user-facing script contains no punctuation. Add only pause markers
    # between lines for TTS prosody without changing any spoken characters.
    return "，".join(lines)


def _collect_speech(outputs) -> np.ndarray:
    chunks: list[np.ndarray] = []
    for output in outputs:
        speech = output.get("tts_speech")
        if speech is None:
            continue
        chunks.append(speech.detach().cpu().numpy().reshape(-1).astype(np.float32))
    if not chunks:
        raise SystemExit("CosyVoice produced no audio")
    return np.concatenate(chunks)


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    samples = np.clip(samples, -1.0, 1.0)
    pcm = (samples * 32767.0).astype(np.int16)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())


def _extract_reference_wav(reference: Path, output_dir: Path) -> Path:
    output = output_dir / f"{reference.stem}_16k.wav"
    suffix = reference.suffix.lower()
    if suffix in DIRECT_WAV_SUFFIXES:
        return reference
    if suffix not in TRANSCODE_SUFFIXES:
        raise SystemExit(f"unsupported reference format: {reference.suffix}")

    container = av.open(str(reference))
    audio_stream = next((stream for stream in container.streams if stream.type == "audio"), None)
    if audio_stream is None:
        raise SystemExit("reference file has no audio stream")

    resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
    chunks: list[np.ndarray] = []
    for frame in container.decode(audio_stream):
        resampled = resampler.resample(frame)
        frames = resampled if isinstance(resampled, list) else [resampled]
        for audio_frame in frames:
            array = audio_frame.to_ndarray()
            chunks.append(array.reshape(-1).astype(np.float32) / 32768.0)
    container.close()
    if not chunks:
        raise SystemExit("reference video audio decode produced no samples")
    _write_wav(output, np.concatenate(chunks), 16000)
    return output


def _import_cosyvoice(repo: Path):
    if not repo.exists():
        raise SystemExit(f"CosyVoice repo not found: {repo}")
    sys.path.insert(0, str(repo))
    sys.path.insert(0, str(repo / "third_party" / "Matcha-TTS"))
    from cosyvoice.cli.cosyvoice import CosyVoice

    return CosyVoice


def _load_cosyvoice(CosyVoice, model_path: Path):
    if not model_path.exists():
        raise SystemExit(f"CosyVoice model not found: {model_path}")
    try:
        return CosyVoice(str(model_path), load_jit=False, load_trt=False, fp16=False)
    except TypeError:
        return CosyVoice(str(model_path))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--script", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path(os.getenv("COSYVOICE_REPO", r"<workspace>\engines\CosyVoice")),
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=Path(os.getenv("COSYVOICE_MODEL", r"<workspace>\models\CosyVoice-300M-25Hz")),
    )
    args = parser.parse_args()

    text = _prepare_tts_text(_read_script(args.script))
    work_dir = args.output.parent / "_cosyvoice_refs"
    reference_wav = _extract_reference_wav(args.reference, work_dir)

    CosyVoice = _import_cosyvoice(args.repo)
    cosyvoice = _load_cosyvoice(CosyVoice, args.model)
    speech = _collect_speech(
        cosyvoice.inference_cross_lingual(
            f"<|zh|>{text}", str(reference_wav), stream=False
        )
    )
    sample_rate = int(getattr(cosyvoice, "sample_rate", 22050))
    _write_wav(args.output, speech, sample_rate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
