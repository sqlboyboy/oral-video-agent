from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from blend_wav2lip_result import (
        aperture_control_from_mouth_state,
        aperture_ratio_from_energy,
        apply_vowel_release_floor,
        audio_mouth_state_controller,
        summarize_mouth_states,
    )
    from wav2lip_onnx import SAMPLE_RATE, read_audio, resample_linear
except ModuleNotFoundError:  # pragma: no cover - used when imported as a package in tests.
    from .blend_wav2lip_result import (
        aperture_control_from_mouth_state,
        aperture_ratio_from_energy,
        apply_vowel_release_floor,
        audio_mouth_state_controller,
        summarize_mouth_states,
    )
    from .wav2lip_onnx import SAMPLE_RATE, read_audio, resample_linear


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze internal audio-driven mouth states without rendering video.")
    parser.add_argument("--audio", required=True, help="Driving audio to inspect.")
    parser.add_argument("--fps", type=float, default=25.0, help="Frame rate used to sample mouth states.")
    parser.add_argument("--frame-count", type=int, default=0, help="Optional frame count. Defaults to audio duration * fps.")
    parser.add_argument("--close-threshold", type=float, default=0.24)
    parser.add_argument("--aperture-min-ratio", type=float, default=0.07)
    parser.add_argument("--aperture-max-ratio", type=float, default=0.36)
    parser.add_argument("--output", help="Optional JSON output path.")
    return parser.parse_args()


def analyze_audio_mouth_states(
    audio_path: Path,
    *,
    fps: float = 25.0,
    frame_count: int = 0,
    close_threshold: float = 0.24,
    aperture_min_ratio: float = 0.07,
    aperture_max_ratio: float = 0.36,
) -> dict:
    samples, sample_rate = read_audio(audio_path)
    samples = resample_linear(samples, sample_rate, SAMPLE_RATE)
    if frame_count <= 0:
        frame_count = max(1, int(round(samples.size / float(SAMPLE_RATE) * fps)))
    states = audio_mouth_state_controller(
        samples,
        SAMPLE_RATE,
        fps,
        frame_count,
        close_threshold=close_threshold,
    )
    summary = summarize_mouth_states(states)
    controls = summarize_aperture_controls(
        states,
        energy_threshold=close_threshold,
        min_ratio=aperture_min_ratio,
        max_ratio=aperture_max_ratio,
    )
    summary["aperture_control"] = controls["summary"]
    for frame, control in zip(summary["frames"], controls["frames"]):
        frame["control"] = control
    summary["audio"] = {
        "path": str(audio_path),
        "sample_rate": SAMPLE_RATE,
        "duration_seconds": round(samples.size / float(SAMPLE_RATE), 4),
        "fps": fps,
        "close_threshold": close_threshold,
        "aperture_min_ratio": aperture_min_ratio,
        "aperture_max_ratio": aperture_max_ratio,
    }
    return summary


def summarize_aperture_controls(
    states,
    *,
    energy_threshold: float,
    min_ratio: float,
    max_ratio: float,
) -> dict:
    frames = []
    target_lock_count = 0
    closed_lock_count = 0
    ratios = []
    drivers = []
    for state in states:
        driver, target_lock, closed_lock = aperture_control_from_mouth_state(
            state.energy,
            state,
            energy_threshold=energy_threshold,
        )
        target_ratio = aperture_ratio_from_energy(
            driver,
            energy_threshold=energy_threshold,
            min_ratio=min_ratio,
            max_ratio=max_ratio,
        )
        target_ratio = apply_vowel_release_floor(
            target_ratio,
            state,
            min_ratio=min_ratio,
            max_ratio=max_ratio,
            target_lock=target_lock,
            closed_lock=closed_lock,
        )
        target_lock_count += int(target_lock)
        closed_lock_count += int(closed_lock)
        ratios.append(target_ratio)
        drivers.append(driver)
        frames.append(
            {
                "aperture_driver": round(driver, 4),
                "target_ratio": round(target_ratio, 4),
                "target_lock": target_lock,
                "closed_lock": closed_lock,
            }
        )
    total = max(len(states), 1)
    return {
        "summary": {
            "target_lock_frames": target_lock_count,
            "closed_lock_frames": closed_lock_count,
            "target_lock_share": round(target_lock_count / total, 4),
            "closed_lock_share": round(closed_lock_count / total, 4),
            "aperture_driver": _range_summary(drivers),
            "target_ratio": _range_summary(ratios),
        },
        "frames": frames,
    }


def _range_summary(values: list[float]) -> dict:
    if not values:
        return {"min": 0.0, "mean": 0.0, "max": 0.0}
    return {
        "min": round(min(values), 4),
        "mean": round(sum(values) / len(values), 4),
        "max": round(max(values), 4),
    }


def main() -> None:
    args = parse_args()
    result = analyze_audio_mouth_states(
        Path(args.audio),
        fps=args.fps,
        frame_count=args.frame_count,
        close_threshold=args.close_threshold,
        aperture_min_ratio=args.aperture_min_ratio,
        aperture_max_ratio=args.aperture_max_ratio,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
