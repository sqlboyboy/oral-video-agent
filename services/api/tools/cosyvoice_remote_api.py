from __future__ import annotations

import os
import sys
import tempfile
import threading
import wave
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask


REPO = Path(os.getenv("COSYVOICE_REPO", "/root/autodl-tmp/cosyvoice/CosyVoice"))
MODEL = Path(
    os.getenv(
        "COSYVOICE_MODEL",
        "/root/autodl-tmp/cosyvoice/models/CosyVoice-300M-25Hz",
    )
)

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "third_party" / "Matcha-TTS"))

from cosyvoice.cli.cosyvoice import CosyVoice  # noqa: E402


def _load_model() -> CosyVoice:
    try:
        return CosyVoice(str(MODEL), load_jit=False, load_trt=False, fp16=False)
    except TypeError:
        return CosyVoice(str(MODEL))


def _prepare_text(text: str) -> str:
    lines = ["".join(line.split()) for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        raise ValueError("text is empty")
    return "，".join(lines)


def _validate_reference(path: Path) -> None:
    try:
        with wave.open(str(path), "rb") as wav:
            if wav.getnframes() <= 0:
                raise ValueError("reference WAV contains no audio")
    except wave.Error as exc:
        raise ValueError("reference_file must be a valid WAV file") from exc


def _collect_speech(outputs) -> np.ndarray:
    chunks: list[np.ndarray] = []
    for output in outputs:
        speech = output.get("tts_speech")
        if speech is not None:
            chunks.append(
                speech.detach().cpu().numpy().reshape(-1).astype(np.float32)
            )
    if not chunks:
        raise RuntimeError("CosyVoice produced no audio")
    return np.concatenate(chunks)


app = FastAPI(title="CosyVoice Remote API", version="1.0.0")
model = _load_model()
inference_lock = threading.Lock()


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "gpu_available": torch.cuda.is_available(),
        "model": MODEL.name,
        "sample_rate": int(getattr(model, "sample_rate", 22050)),
    }


@app.post("/api/voice")
def synthesize_voice(
    text: str = Form(...),
    reference_file: UploadFile = File(...),
):
    work_dir = Path(tempfile.mkdtemp(prefix="cosyvoice-api-"))
    reference_path = work_dir / "reference.wav"
    output_path = work_dir / "result.wav"
    try:
        reference_path.write_bytes(reference_file.file.read())
        _validate_reference(reference_path)
        tts_text = _prepare_text(text)
        with inference_lock:
            speech = _collect_speech(
                model.inference_cross_lingual(
                    f"<|zh|>{tts_text}",
                    str(reference_path),
                    stream=False,
                )
            )
        sf.write(
            output_path,
            speech,
            int(getattr(model, "sample_rate", 22050)),
            subtype="PCM_16",
        )
    except (ValueError, RuntimeError) as exc:
        for path in work_dir.glob("*"):
            path.unlink(missing_ok=True)
        work_dir.rmdir()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    def cleanup() -> None:
        for path in work_dir.glob("*"):
            path.unlink(missing_ok=True)
        work_dir.rmdir()

    return FileResponse(
        output_path,
        media_type="audio/wav",
        filename="voice.wav",
        background=BackgroundTask(cleanup),
    )
