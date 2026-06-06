import wave
from pathlib import Path

import numpy as np

from tools.analyze_audio_mouth_states import analyze_audio_mouth_states


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int = 16000) -> None:
    samples_i16 = np.clip(samples, -1.0, 1.0)
    samples_i16 = (samples_i16 * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(samples_i16.tobytes())


def test_audio_mouth_state_analysis_separates_consonants_and_vowels(tmp_path):
    sample_rate = 16000
    rng = np.random.default_rng(11)
    silence_a = np.zeros(int(sample_rate * 0.24), dtype=np.float32)
    plosive = np.concatenate(
        [
            rng.normal(0.0, 0.75, int(sample_rate * 0.025)).astype(np.float32),
            np.zeros(int(sample_rate * 0.075), dtype=np.float32),
        ]
    )
    fricative = rng.normal(0.0, 0.16, int(sample_rate * 0.34)).astype(np.float32)
    t = np.arange(int(sample_rate * 0.36), dtype=np.float32) / sample_rate
    vowel = (np.sin(2.0 * np.pi * 220.0 * t) * 0.58).astype(np.float32)
    silence_b = np.zeros(int(sample_rate * 0.22), dtype=np.float32)
    audio = np.concatenate([silence_a, plosive, fricative, vowel, silence_b])
    audio_path = tmp_path / "plosive_fricative_vowel.wav"
    _write_wav(audio_path, audio, sample_rate)

    summary = analyze_audio_mouth_states(audio_path, fps=25.0, close_threshold=0.24)
    consonant_frames = [frame for frame in summary["frames"] if frame["state"] == "consonant"]
    vowel_frames = [frame for frame in summary["frames"] if frame["state"] == "vowel"]
    silence_frames = [frame for frame in summary["frames"] if frame["state"] == "silence"]

    assert summary["state_counts"]["silence"] >= 8
    assert len(consonant_frames) >= 4
    assert len(vowel_frames) >= 5
    assert max(frame["openness"] for frame in consonant_frames) < 0.32
    assert max(frame["openness"] for frame in vowel_frames) > 0.55
    assert silence_frames[0]["openness"] == 0.0
    assert summary["aperture_control"]["closed_lock_frames"] >= len(silence_frames)
    assert summary["aperture_control"]["target_lock_frames"] > summary["aperture_control"]["closed_lock_frames"]
    assert max(frame["control"]["target_ratio"] for frame in consonant_frames) < 0.08
    assert max(frame["control"]["target_ratio"] for frame in vowel_frames) > 0.32
    assert any(frame["control"]["target_lock"] and not frame["control"]["closed_lock"] for frame in consonant_frames)
