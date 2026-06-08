from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import av
import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

try:
    from blend_wav2lip_result import mouth_open_ratio
    from wav2lip_onnx import (
        detect_mouth_points,
        estimate_face_box,
        frame_audio_levels,
        read_audio,
    )
except ModuleNotFoundError:  # pragma: no cover - used when imported in tests.
    from .blend_wav2lip_result import mouth_open_ratio
    from .wav2lip_onnx import (
        detect_mouth_points,
        estimate_face_box,
        frame_audio_levels,
        read_audio,
    )


@dataclass(frozen=True)
class MouthFrameMetric:
    index: int
    ratio: float
    dark_share: float
    audio_energy: float
    shadow_share: float = 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose mouth aperture naturalness for rendered talking-head videos.")
    parser.add_argument("--video", required=True, help="Rendered video to inspect.")
    parser.add_argument("--audio", help="Driving audio. If omitted, audio sync metrics are skipped.")
    parser.add_argument("--mouth-state", help="Optional internal mouth-state JSON from blend/analyze tools.")
    parser.add_argument("--atlas", action="store_true", help="Diagnose whether a same-identity reference video has enough closed/micro-open mouth coverage.")
    parser.add_argument("--output", help="Optional JSON output path.")
    parser.add_argument("--sample-stride", type=int, default=1, help="Analyze every Nth frame.")
    parser.add_argument("--max-frames", type=int, default=0, help="Optional cap after stride sampling; 0 means no cap.")
    parser.add_argument("--low-energy-threshold", type=float, default=0.22)
    parser.add_argument("--closed-ratio-threshold", type=float, default=0.14)
    parser.add_argument("--high-energy-threshold", type=float, default=0.62)
    parser.add_argument("--open-ratio-threshold", type=float, default=0.24)
    parser.add_argument("--consonant-open-threshold", type=float, default=0.18)
    return parser.parse_args()


def summarize_atlas_coverage(
    metrics: Iterable[MouthFrameMetric],
    *,
    total_frames: int,
    closed_threshold: float = 0.12,
    micro_open_threshold: float = 0.22,
    open_threshold: float = 0.30,
) -> dict:
    rows = list(metrics)
    detected = len(rows)
    if detected == 0:
        return {
            "total_frames": total_frames,
            "detected_frames": 0,
            "detection_rate": 0.0,
            "verdict": "insufficient_landmarks",
            "warnings": ["No mouth landmarks were detected."],
        }

    ratios = np.array([row.ratio for row in rows], dtype=np.float32)
    dark = np.array([row.dark_share for row in rows], dtype=np.float32)
    detection_rate = detected / max(total_frames, 1)
    closed = ratios <= float(closed_threshold)
    micro_open = (ratios > float(closed_threshold)) & (ratios <= float(micro_open_threshold))
    open_frames = ratios >= float(open_threshold)
    closed_share = float(np.mean(closed))
    micro_open_share = float(np.mean(micro_open))
    open_share = float(np.mean(open_frames))
    usable_closed = closed & (dark <= 0.25)
    usable_closed_count = int(np.sum(usable_closed))

    warnings: list[str] = []
    min_ratio = float(np.min(ratios))
    p10_ratio = float(np.percentile(ratios, 10))
    max_ratio = float(np.max(ratios))
    if detection_rate < 0.55:
        warnings.append("Landmark detection is weak; atlas coverage may be unreliable.")
    if min_ratio > 0.12 or usable_closed_count < 3:
        warnings.append("Reference video lacks reliable closed-mouth frames.")
    if micro_open_share < 0.12:
        warnings.append("Reference video has weak micro-open coverage for natural transitions.")
    if max_ratio < 0.28 or open_share < 0.04:
        warnings.append("Reference video lacks open-mouth range; large vowels may look muted.")
    if float(np.percentile(dark, 95)) > 0.42:
        warnings.append("Reference mouth frames contain frequent dark cavities.")

    return {
        "total_frames": total_frames,
        "detected_frames": detected,
        "detection_rate": round(detection_rate, 4),
        "ratio": {
            "min": round(min_ratio, 4),
            "p10": round(p10_ratio, 4),
            "median": round(float(np.median(ratios)), 4),
            "p90": round(float(np.percentile(ratios, 90)), 4),
            "max": round(max_ratio, 4),
        },
        "coverage": {
            "closed_share": round(closed_share, 4),
            "usable_closed_count": usable_closed_count,
            "micro_open_share": round(micro_open_share, 4),
            "open_share": round(open_share, 4),
        },
        "dark_cavity": {
            "mean": round(float(np.mean(dark)), 4),
            "p95": round(float(np.percentile(dark, 95)), 4),
        },
        "verdict": "needs_better_reference" if warnings else "ok",
        "warnings": warnings,
    }


def summarize_mouth_metrics(
    metrics: Iterable[MouthFrameMetric],
    *,
    total_frames: int,
    low_energy_threshold: float = 0.22,
    closed_ratio_threshold: float = 0.14,
    high_energy_threshold: float = 0.62,
    open_ratio_threshold: float = 0.24,
) -> dict:
    rows = list(metrics)
    detected = len(rows)
    if detected == 0:
        return {
            "total_frames": total_frames,
            "detected_frames": 0,
            "detection_rate": 0.0,
            "verdict": "insufficient_landmarks",
            "warnings": ["No mouth landmarks were detected."],
        }

    ratios = np.array([row.ratio for row in rows], dtype=np.float32)
    dark = np.array([row.dark_share for row in rows], dtype=np.float32)
    shadow = np.array([max(row.shadow_share, row.dark_share) for row in rows], dtype=np.float32)
    energy = np.array([row.audio_energy for row in rows], dtype=np.float32)
    deltas = np.abs(np.diff(ratios)) if ratios.size > 1 else np.zeros(1, dtype=np.float32)
    low_energy_mask = energy <= float(low_energy_threshold)
    leak_ratio = 0.0
    if np.any(low_energy_mask):
        leak_ratio = float(np.mean(ratios[low_energy_mask] > float(closed_ratio_threshold)))
    visible_gap_ratio = 0.0
    if np.any(low_energy_mask):
        visible_gap_ratio = float(np.mean((ratios[low_energy_mask] > float(closed_ratio_threshold)) & (shadow[low_energy_mask] > 0.03)))
    high_energy_mask = energy >= float(high_energy_threshold)
    muted_open_ratio = 0.0
    high_energy_mean_ratio = None
    if np.any(high_energy_mask):
        muted_open_ratio = float(np.mean(ratios[high_energy_mask] < float(open_ratio_threshold)))
        high_energy_mean_ratio = float(np.mean(ratios[high_energy_mask]))

    correlation = None
    if ratios.size > 2 and float(np.std(ratios)) > 1e-5 and float(np.std(energy)) > 1e-5:
        correlation = float(np.corrcoef(ratios, energy)[0, 1])

    warnings: list[str] = []
    detection_rate = detected / max(total_frames, 1)
    mean_abs_delta = float(np.mean(deltas))
    p95_abs_delta = float(np.percentile(deltas, 95))
    dark_p95 = float(np.percentile(dark, 95))
    if detection_rate < 0.55:
        warnings.append("Landmark detection is weak; inspect face crop or model availability.")
    if visible_gap_ratio > 0.20:
        warnings.append("Mouth has visible inner gaps on low-energy audio; closed-mouth drift is likely.")
    if muted_open_ratio > 0.35:
        warnings.append("Mouth opening is muted on high-energy audio; vowel articulation may look weak.")
    if p95_abs_delta > 0.075:
        warnings.append("Mouth aperture changes abruptly; visible jitter is likely.")
    if dark_p95 > 0.42:
        warnings.append("Inner mouth is frequently very dark; black-cavity artifacts are likely.")
    if correlation is not None and correlation < 0.12:
        warnings.append("Mouth opening has weak correlation with audio energy.")

    return {
        "total_frames": total_frames,
        "detected_frames": detected,
        "detection_rate": round(detection_rate, 4),
        "ratio": {
            "min": round(float(np.min(ratios)), 4),
            "median": round(float(np.median(ratios)), 4),
            "p95": round(float(np.percentile(ratios, 95)), 4),
            "max": round(float(np.max(ratios)), 4),
        },
        "jitter": {
            "mean_abs_delta": round(mean_abs_delta, 4),
            "p95_abs_delta": round(p95_abs_delta, 4),
        },
        "low_energy_closed_leak_ratio": round(leak_ratio, 4),
        "low_energy_visible_gap_ratio": round(visible_gap_ratio, 4),
        "high_energy_muted_open_ratio": round(muted_open_ratio, 4),
        "high_energy_mean_ratio": None if high_energy_mean_ratio is None else round(high_energy_mean_ratio, 4),
        "dark_cavity": {
            "mean": round(float(np.mean(dark)), 4),
            "p95": round(dark_p95, 4),
        },
        "inner_shadow": {
            "mean": round(float(np.mean(shadow)), 4),
            "p95": round(float(np.percentile(shadow, 95)), 4),
        },
        "audio_energy_correlation": None if correlation is None else round(correlation, 4),
        "verdict": "needs_review" if warnings else "ok",
        "warnings": warnings,
    }


def summarize_mouth_state_alignment(
    metrics: Iterable[MouthFrameMetric],
    mouth_state_frames: Iterable[dict],
    *,
    closed_ratio_threshold: float = 0.14,
    consonant_open_threshold: float = 0.18,
    vowel_open_threshold: float = 0.24,
) -> dict:
    rows = list(metrics)
    frames_by_index = {
        int(frame.get("index", -1)): frame
        for frame in mouth_state_frames
        if "index" in frame
    }
    matched = [(row, frames_by_index[row.index]) for row in rows if row.index in frames_by_index]
    if not matched:
        return {
            "matched_frames": 0,
            "state_counts": {},
            "verdict": "insufficient_state_overlap",
            "warnings": ["No analyzed mouth frames overlapped the mouth-state timeline."],
        }

    state_counts: dict[str, int] = {}
    for _, frame in matched:
        state = str(frame.get("state") or "")
        state_counts[state] = state_counts.get(state, 0) + 1

    def ratios_for(*state_names: str) -> np.ndarray:
        values = [row.ratio for row, frame in matched if str(frame.get("state") or "") in state_names]
        return np.array(values, dtype=np.float32)

    def visible_gap_for(*state_names: str) -> float:
        selected = [row for row, frame in matched if str(frame.get("state") or "") in state_names]
        if not selected:
            return 0.0
        return float(
            np.mean([
                row.ratio > closed_ratio_threshold and max(row.shadow_share, row.dark_share) > 0.03
                for row in selected
            ])
        )

    consonant_ratios = ratios_for("consonant", "consonant_closed")
    vowel_rows = [
        row
        for row, frame in matched
        if str(frame.get("state") or "") == "vowel"
        and _state_expected_open(frame, vowel_open_threshold)
    ]
    vowel_ratios = np.array([row.ratio for row in vowel_rows], dtype=np.float32)
    medium_vowel_rows = [
        row
        for row, frame in matched
        if str(frame.get("state") or "") == "vowel"
        and _state_open_value(frame) >= 0.25
    ]
    medium_vowel_ratios = np.array([row.ratio for row in medium_vowel_rows], dtype=np.float32)
    closed_ratios = ratios_for("silence", "consonant_closed")

    consonant_over_open_ratio = 0.0
    consonant_mean_ratio = None
    if consonant_ratios.size:
        consonant_over_open_ratio = float(np.mean(consonant_ratios > consonant_open_threshold))
        consonant_mean_ratio = float(np.mean(consonant_ratios))

    vowel_muted_ratio = 0.0
    vowel_mean_ratio = None
    if vowel_ratios.size:
        vowel_muted_ratio = float(np.mean(vowel_ratios < vowel_open_threshold))
        vowel_mean_ratio = float(np.mean(vowel_ratios))
    medium_vowel_muted_ratio = 0.0
    medium_vowel_mean_ratio = None
    if medium_vowel_ratios.size:
        medium_vowel_muted_ratio = float(np.mean(medium_vowel_ratios < vowel_open_threshold))
        medium_vowel_mean_ratio = float(np.mean(medium_vowel_ratios))

    warnings: list[str] = []
    closed_visible_gap_ratio = visible_gap_for("silence", "consonant_closed")
    if closed_visible_gap_ratio > 0.20:
        warnings.append("Closed mouth-state frames show visible inner gaps.")
    if consonant_ratios.size >= 3 and consonant_over_open_ratio > 0.35:
        warnings.append("Consonant mouth-state frames are opening too widely.")
    if vowel_ratios.size >= 3 and vowel_muted_ratio > 0.35:
        warnings.append("Vowel mouth-state frames are muted.")
    if medium_vowel_ratios.size >= 3 and medium_vowel_muted_ratio > 0.35:
        warnings.append("Medium vowel mouth-state frames are muted.")

    return {
        "matched_frames": len(matched),
        "state_counts": state_counts,
        "closed_state_visible_gap_ratio": round(closed_visible_gap_ratio, 4),
        "consonant_frames": int(consonant_ratios.size),
        "consonant_over_open_ratio": round(consonant_over_open_ratio, 4),
        "consonant_mean_ratio": None if consonant_mean_ratio is None else round(consonant_mean_ratio, 4),
        "vowel_expected_open_frames": int(vowel_ratios.size),
        "vowel_muted_ratio": round(vowel_muted_ratio, 4),
        "vowel_mean_ratio": None if vowel_mean_ratio is None else round(vowel_mean_ratio, 4),
        "medium_vowel_frames": int(medium_vowel_ratios.size),
        "medium_vowel_muted_ratio": round(medium_vowel_muted_ratio, 4),
        "medium_vowel_mean_ratio": None if medium_vowel_mean_ratio is None else round(medium_vowel_mean_ratio, 4),
        "closed_state_mean_ratio": None if closed_ratios.size == 0 else round(float(np.mean(closed_ratios)), 4),
        "verdict": "needs_review" if warnings else "ok",
        "warnings": warnings,
    }


def _state_expected_open(frame: dict, vowel_open_threshold: float) -> bool:
    control = frame.get("control")
    if isinstance(control, dict):
        try:
            return float(control.get("target_ratio", 0.0)) >= vowel_open_threshold
        except (TypeError, ValueError):
            pass
    if "openness" not in frame:
        return True
    try:
        return float(frame.get("openness", 0.0)) >= 0.45
    except (TypeError, ValueError):
        return False


def _state_open_value(frame: dict) -> float:
    values: list[float] = []
    for key in ("openness", "energy"):
        try:
            values.append(float(frame.get(key, 0.0)))
        except (TypeError, ValueError):
            pass
    control = frame.get("control")
    if isinstance(control, dict):
        try:
            values.append(float(control.get("target_ratio", 0.0)))
        except (TypeError, ValueError):
            pass
    return max(values) if values else 0.0


def load_mouth_state_frames(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    frames = data.get("frames", [])
    if not isinstance(frames, list):
        return []
    return [frame for frame in frames if isinstance(frame, dict)]


def analyze_video(
    video_path: Path,
    *,
    audio_path: Path | None = None,
    mouth_state_path: Path | None = None,
    sample_stride: int = 1,
    max_frames: int = 0,
    low_energy_threshold: float = 0.22,
    closed_ratio_threshold: float = 0.14,
    high_energy_threshold: float = 0.62,
    open_ratio_threshold: float = 0.24,
    consonant_open_threshold: float = 0.18,
) -> dict:
    metrics, analyzed_frames = collect_mouth_frame_metrics(
        video_path,
        audio_path=audio_path,
        sample_stride=sample_stride,
        max_frames=max_frames,
    )
    result = summarize_mouth_metrics(
        metrics,
        total_frames=analyzed_frames,
        low_energy_threshold=low_energy_threshold,
        closed_ratio_threshold=closed_ratio_threshold,
        high_energy_threshold=high_energy_threshold,
        open_ratio_threshold=open_ratio_threshold,
    )
    if mouth_state_path is not None:
        result["mouth_state_alignment"] = summarize_mouth_state_alignment(
            metrics,
            load_mouth_state_frames(mouth_state_path),
            closed_ratio_threshold=closed_ratio_threshold,
            consonant_open_threshold=consonant_open_threshold,
            vowel_open_threshold=open_ratio_threshold,
        )
    return result


def analyze_atlas_video(
    video_path: Path,
    *,
    sample_stride: int = 1,
    max_frames: int = 0,
) -> dict:
    metrics, analyzed_frames = collect_mouth_frame_metrics(
        video_path,
        sample_stride=sample_stride,
        max_frames=max_frames,
    )
    return summarize_atlas_coverage(metrics, total_frames=analyzed_frames)


def collect_mouth_frame_metrics(
    video_path: Path,
    *,
    audio_path: Path | None = None,
    sample_stride: int = 1,
    max_frames: int = 0,
) -> tuple[list[MouthFrameMetric], int]:
    if cv2 is None:
        raise RuntimeError("OpenCV is required for mouth naturalness diagnostics.")
    container = av.open(str(video_path))
    stream = next(item for item in container.streams if item.type == "video")
    fps = float(stream.average_rate or 25)
    total_frames = int(stream.frames or 0)
    if total_frames <= 0:
        total_frames = int((float(stream.duration or 0) * float(stream.time_base or 0)) * fps)

    audio_levels = np.zeros(max(total_frames, 1), dtype=np.float32)
    if audio_path is not None:
        samples, sample_rate = read_audio(audio_path)
        audio_levels = frame_audio_levels(samples, sample_rate, fps, max(total_frames, 1))

    metrics: list[MouthFrameMetric] = []
    previous_box: tuple[int, int, int, int] | None = None
    stride = max(1, int(sample_stride))
    sampled = 0
    for index, frame in enumerate(container.decode(stream)):
        if index % stride != 0:
            continue
        if max_frames > 0 and sampled >= max_frames:
            break
        sampled += 1
        image = frame.to_ndarray(format="rgb24")
        face_box = estimate_face_box(image, previous_box)
        previous_box = face_box
        mouth_points = detect_mouth_points(image, face_box)
        if mouth_points is None:
            continue
        ratio = mouth_open_ratio(mouth_points)
        dark_share = inner_mouth_dark_share(image, mouth_points)
        shadow_share = inner_mouth_shadow_share(image, mouth_points)
        audio_energy = float(audio_levels[min(index, audio_levels.size - 1)])
        metrics.append(MouthFrameMetric(index, ratio, dark_share, audio_energy, shadow_share))
    container.close()
    return metrics, sampled if sampled else total_frames


def inner_mouth_dark_share(frame: np.ndarray, mouth_points: np.ndarray) -> float:
    if cv2 is None:
        return 0.0
    inner = mouth_points[12:20].astype(np.float32)
    if inner.shape[0] < 3:
        return 0.0
    height, width = frame.shape[:2]
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillConvexPoly(mask, cv2.convexHull(inner.astype(np.int32)), 255)
    pixels = frame[mask > 0].astype(np.float32)
    if pixels.size == 0:
        return 0.0
    luma = pixels.mean(axis=1)
    return float(np.mean(luma < 34.0))


def inner_mouth_shadow_share(frame: np.ndarray, mouth_points: np.ndarray) -> float:
    if cv2 is None:
        return 0.0
    inner = mouth_points[12:20].astype(np.float32)
    if inner.shape[0] < 3:
        return 0.0
    height, width = frame.shape[:2]
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillConvexPoly(mask, cv2.convexHull(inner.astype(np.int32)), 255)
    pixels = frame[mask > 0].astype(np.float32)
    if pixels.size == 0:
        return 0.0
    luma = pixels.mean(axis=1)
    return float(np.mean(luma < 75.0))


def main() -> None:
    args = parse_args()
    if args.atlas:
        result = analyze_atlas_video(
            Path(args.video),
            sample_stride=args.sample_stride,
            max_frames=args.max_frames,
        )
    else:
        result = analyze_video(
            Path(args.video),
            audio_path=Path(args.audio) if args.audio else None,
            mouth_state_path=Path(args.mouth_state) if args.mouth_state else None,
            sample_stride=args.sample_stride,
            max_frames=args.max_frames,
            low_energy_threshold=args.low_energy_threshold,
            closed_ratio_threshold=args.closed_ratio_threshold,
            high_energy_threshold=args.high_energy_threshold,
            open_ratio_threshold=args.open_ratio_threshold,
            consonant_open_threshold=args.consonant_open_threshold,
        )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
