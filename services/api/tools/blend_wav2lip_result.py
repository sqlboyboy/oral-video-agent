import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

try:
    from wav2lip_onnx import (
        SAMPLE_RATE,
        detect_mouth_points,
        estimate_face_box,
        frame_audio_levels,
        read_audio,
        resample_linear,
    )
except ModuleNotFoundError:  # pragma: no cover - used when imported as a package in tests.
    from .wav2lip_onnx import (
        SAMPLE_RATE,
        detect_mouth_points,
        estimate_face_box,
        frame_audio_levels,
        read_audio,
        resample_linear,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Blend a Wav2Lip result back into the original video with a tight mouth mask.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--generated", required=True)
    parser.add_argument("--detail-generated")
    parser.add_argument("--preserve-lips", action="store_true")
    parser.add_argument("--dynamic-preserve", action="store_true")
    parser.add_argument("--seamless-edge", action="store_true")
    parser.add_argument("--detail-restore", action="store_true")
    parser.add_argument("--align-detail", action="store_true")
    parser.add_argument("--soft-cavity", action="store_true")
    parser.add_argument("--upper-cavity-lift", action="store_true")
    parser.add_argument(
        "--aperture-mode",
        choices=["auto", "open", "closed"],
        default="auto",
        help="Debug aperture independently from audio sync: auto follows audio, open/closed force mouth state.",
    )
    parser.add_argument("--forced-openness", type=float, default=None)
    parser.add_argument("--texture-source", help="Optional source video used to build a person-specific mouth texture atlas.")
    parser.add_argument("--texture-samples", type=int, default=160)
    parser.add_argument("--texture-top-k", type=int, default=10)
    parser.add_argument("--aperture-atlas-source", help="Same-identity video used to stabilize closed/micro-open mouth states.")
    parser.add_argument("--aperture-atlas-strength", type=float, default=0.0)
    parser.add_argument("--aperture-energy-threshold", type=float, default=0.22)
    parser.add_argument("--aperture-min-ratio", type=float, default=0.08)
    parser.add_argument("--aperture-max-ratio", type=float, default=0.34)
    parser.add_argument("--aperture-attack", type=float, default=1.0)
    parser.add_argument("--aperture-release", type=float, default=1.0)
    parser.add_argument("--open-closed-priority", action="store_true", help="Prioritize visible open/closed mouth shapes before detailed audio sync.")
    parser.add_argument("--open-shape-trigger", type=float, default=0.25)
    parser.add_argument("--open-shape-openness", type=float, default=0.76)
    parser.add_argument("--open-geometry-warp", action="store_true", help="Experimentally expand visual mouth aperture on open frames.")
    parser.add_argument("--open-geometry-strength", type=float, default=0.72)
    parser.add_argument("--open-geometry-max-ratio", type=float, default=0.38)
    parser.add_argument("--open-generated-priority", action="store_true", help="Preserve generated open-mouth pixels instead of repainting the aperture.")
    parser.add_argument("--mouth-state-debug-output", help="Optional internal JSON dump for audio mouth-state decisions.")
    parser.add_argument("--audio", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


@dataclass
class MouthTexture:
    frame: np.ndarray
    mouth_points: np.ndarray
    ratio: float
    score: float
    index: int


@dataclass(frozen=True)
class MouthStateFrame:
    energy: float
    centroid: float
    zero_crossing: float
    high_band_share: float
    state: str
    openness: float


def read_frames(video_path: Path) -> tuple[list[np.ndarray], float]:
    container = av.open(str(video_path))
    stream = next(item for item in container.streams if item.type == "video")
    fps = float(stream.average_rate or 25)
    frames = [frame.to_ndarray(format="rgb24") for frame in container.decode(stream)]
    container.close()
    return frames, fps


def write_video(frames: list[np.ndarray], output: Path, fps: float) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    container = av.open(str(output), mode="w")
    stream = container.add_stream("libx264", rate=round(fps) or 25)
    stream.width = frames[0].shape[1]
    stream.height = frames[0].shape[0]
    stream.pix_fmt = "yuv420p"
    stream.options = {"crf": "18", "preset": "medium"}
    for image in frames:
        video_frame = av.VideoFrame.from_ndarray(image, format="rgb24")
        for packet in stream.encode(video_frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()


def mouth_open_ratio(mouth_points: np.ndarray) -> float:
    inner = mouth_points[12:20].astype(np.float32)
    if inner.shape[0] < 6:
        return 0.0
    inner_width = max(float(inner[:, 0].max() - inner[:, 0].min()), 1.0)
    inner_height = float(inner[:, 1].max() - inner[:, 1].min())
    return float(np.clip(inner_height / inner_width, 0.0, 1.0))


def scan_mouth_textures(
    video_path: Path | None,
    target_shape: tuple[int, int],
    sample_count: int,
    top_k: int,
) -> list[MouthTexture]:
    if video_path is None:
        return []
    if cv2 is None:
        return []
    height, width = target_shape
    textures: list[MouthTexture] = []
    container = av.open(str(video_path))
    stream = next(item for item in container.streams if item.type == "video")
    total_frames = int(stream.frames or 0)
    stride = max(1, total_frames // max(sample_count, 1)) if total_frames else 45
    previous_box: tuple[int, int, int, int] | None = None

    for index, frame in enumerate(container.decode(stream)):
        if index % stride != 0:
            continue
        image = frame.to_ndarray(format="rgb24")
        if image.shape[0] != height or image.shape[1] != width:
            image = cv2.resize(image, (width, height), interpolation=cv2.INTER_LINEAR)
        face_box = estimate_face_box(image, previous_box)
        previous_box = face_box
        mouth_points = detect_mouth_points(image, face_box)
        if mouth_points is None:
            continue
        ratio = mouth_open_ratio(mouth_points)
        if ratio < 0.16:
            continue

        inner = mouth_points[12:20].astype(np.float32)
        mask = np.zeros((height, width), dtype=np.uint8)
        cv2.fillConvexPoly(mask, cv2.convexHull(inner.astype(np.int32)), 255)
        pixels = image[mask > 0].astype(np.float32)
        if pixels.size == 0:
            continue
        luma = pixels.mean(axis=1)
        bright_share = float(np.mean(luma > 145.0))
        dark_share = float(np.mean(luma < 38.0))
        natural_luma = float(np.clip((luma.mean() - 45.0) / 90.0, 0.0, 1.0))
        score = ratio * 2.0 + bright_share * 0.45 + natural_luma * 0.25 - dark_share * 0.8
        textures.append(MouthTexture(image.copy(), mouth_points.astype(np.float32), ratio, score, index))
        textures = sorted(textures, key=lambda item: item.score, reverse=True)[: max(top_k * 3, top_k)]

    container.close()
    textures = sorted(textures, key=lambda item: item.score, reverse=True)[:top_k]
    print(
        "mouth texture atlas:",
        ", ".join(f"f{item.index}:r{item.ratio:.2f}:s{item.score:.2f}" for item in textures[:6]),
        flush=True,
    )
    return textures


def scan_aperture_atlas(
    video_path: Path | None,
    target_shape: tuple[int, int],
    sample_count: int,
    top_k: int,
) -> list[MouthTexture]:
    if video_path is None or cv2 is None:
        return []
    height, width = target_shape
    textures: list[MouthTexture] = []
    container = av.open(str(video_path))
    stream = next(item for item in container.streams if item.type == "video")
    total_frames = int(stream.frames or 0)
    stride = max(1, total_frames // max(sample_count, 1)) if total_frames else 45
    previous_box: tuple[int, int, int, int] | None = None

    for index, frame in enumerate(container.decode(stream)):
        if index % stride != 0:
            continue
        image = frame.to_ndarray(format="rgb24")
        if image.shape[0] != height or image.shape[1] != width:
            image = cv2.resize(image, (width, height), interpolation=cv2.INTER_LINEAR)
        face_box = estimate_face_box(image, previous_box)
        previous_box = face_box
        mouth_points = detect_mouth_points(image, face_box)
        if mouth_points is None:
            continue
        ratio = mouth_open_ratio(mouth_points)
        outer = mouth_points[:12].astype(np.float32)
        mask = np.zeros((height, width), dtype=np.uint8)
        cv2.fillConvexPoly(mask, cv2.convexHull(outer.astype(np.int32)), 255)
        pixels = image[mask > 0].astype(np.float32)
        if pixels.size == 0:
            continue
        luma = pixels.mean(axis=1)
        dark_share = float(np.mean(luma < 32.0))
        natural_luma = float(np.clip((luma.mean() - 42.0) / 110.0, 0.0, 1.0))
        # Keep both closed and micro-open targets; prefer frames without harsh
        # black cavities because this atlas is for aperture state, not texture drama.
        score = natural_luma * 0.55 - dark_share * 0.65
        textures.append(MouthTexture(image.copy(), mouth_points.astype(np.float32), ratio, score, index))

    container.close()
    textures = sorted(textures, key=lambda item: item.score, reverse=True)[: max(top_k * 8, top_k)]
    textures = sorted(textures, key=lambda item: item.ratio)
    if textures:
        print(
            "mouth aperture atlas:",
            f"min=f{textures[0].index}:r{textures[0].ratio:.2f}",
            f"mid=f{textures[len(textures)//2].index}:r{textures[len(textures)//2].ratio:.2f}",
            f"max=f{textures[-1].index}:r{textures[-1].ratio:.2f}",
            flush=True,
        )
    return textures[:top_k]


def choose_mouth_texture(textures: list[MouthTexture], mouth_points: np.ndarray, openness: float) -> MouthTexture | None:
    if not textures or openness < 0.34:
        return None
    target_ratio = mouth_open_ratio(mouth_points)
    if target_ratio <= 0.02:
        target_ratio = 0.18 + openness * 0.42
    return min(textures, key=lambda item: abs(item.ratio - target_ratio) * 1.6 - item.score * 0.18)


def smoothstep(value: float) -> float:
    value = float(np.clip(value, 0.0, 1.0))
    return value * value * (3.0 - 2.0 * value)


def aperture_ratio_from_energy(
    openness: float,
    *,
    energy_threshold: float,
    min_ratio: float,
    max_ratio: float,
) -> float:
    energy_threshold = float(np.clip(energy_threshold, 0.0, 0.85))
    energy = smoothstep((float(np.clip(openness, 0.0, 1.0)) - energy_threshold) / max(1.0 - energy_threshold, 1e-5))
    min_ratio = float(np.clip(min_ratio, 0.0, 0.8))
    max_ratio = float(np.clip(max_ratio, min_ratio, 0.8))
    return min_ratio + energy * (max_ratio - min_ratio)


def mouth_state_openness_levels(
    levels: np.ndarray,
    *,
    close_threshold: float,
    open_threshold: float | None = None,
    attack: float = 0.75,
    release: float = 0.85,
) -> np.ndarray:
    if levels.size == 0:
        return levels.astype(np.float32, copy=False)
    close_threshold = float(np.clip(close_threshold, 0.0, 0.85))
    open_threshold = float(np.clip(open_threshold if open_threshold is not None else close_threshold + 0.16, close_threshold + 1e-4, 1.0))
    attack = float(np.clip(attack, 0.0, 1.0))
    release = float(np.clip(release, 0.0, 1.0))

    controlled = np.zeros_like(levels, dtype=np.float32)
    current = 0.0
    for index, level in enumerate(levels.astype(np.float32, copy=False)):
        level_f = float(np.clip(level, 0.0, 1.0))
        if level_f <= close_threshold:
            target = 0.0
        elif level_f >= open_threshold:
            target = level_f
        else:
            transition = smoothstep((level_f - close_threshold) / max(open_threshold - close_threshold, 1e-5))
            target = level_f * transition
        rate = attack if target > current else release
        current = current * (1.0 - rate) + target * rate
        controlled[index] = current
    return controlled


def _frame_frequency_features(segment: np.ndarray, sample_rate: int) -> tuple[float, float, float]:
    if segment.size < 4:
        return 0.0, 0.0, 0.0
    centered = segment.astype(np.float32, copy=False) - float(np.mean(segment))
    if np.max(np.abs(centered)) <= 1e-6:
        return 0.0, 0.0, 0.0
    zero_crossing = float(np.mean(centered[:-1] * centered[1:] < 0.0))
    window = np.hanning(centered.size).astype(np.float32)
    spectrum = np.abs(np.fft.rfft(centered * window)).astype(np.float32)
    if spectrum.size <= 1 or float(np.sum(spectrum)) <= 1e-6:
        return zero_crossing, 0.0, 0.0
    freqs = np.fft.rfftfreq(centered.size, d=1.0 / float(sample_rate))
    centroid = float(np.sum(freqs * spectrum) / max(float(np.sum(spectrum)), 1e-6))
    high_band = float(np.sum(spectrum[freqs >= 2600.0]) / max(float(np.sum(spectrum)), 1e-6))
    return zero_crossing, float(np.clip(centroid / 4200.0, 0.0, 1.0)), float(np.clip(high_band, 0.0, 1.0))


def audio_mouth_state_controller(
    samples: np.ndarray,
    sample_rate: int,
    fps: float,
    frame_count: int,
    *,
    close_threshold: float,
    open_threshold: float | None = None,
    attack: float = 0.82,
    release: float = 0.72,
) -> list[MouthStateFrame]:
    if frame_count <= 0:
        return []
    levels = frame_audio_levels(samples, sample_rate, fps, frame_count)
    if levels.size == 0:
        return []
    close_threshold = float(np.clip(close_threshold, 0.0, 0.85))
    open_threshold = float(np.clip(open_threshold if open_threshold is not None else close_threshold + 0.18, close_threshold + 1e-4, 1.0))
    attack = float(np.clip(attack, 0.0, 1.0))
    release = float(np.clip(release, 0.0, 1.0))

    states: list[MouthStateFrame] = []
    current = 0.0
    for index in range(frame_count):
        start = int(index / fps * sample_rate)
        end = int((index + 1) / fps * sample_rate)
        segment = samples[start:end]
        energy = float(levels[min(index, levels.size - 1)])
        zero_crossing, centroid, high_band = _frame_frequency_features(segment, sample_rate)
        noisy_consonant = zero_crossing > 0.18 or centroid > 0.42 or high_band > 0.30
        closed_consonant = (
            energy <= close_threshold + 0.04
            and zero_crossing < 0.08
            and centroid < 0.16
            and high_band < 0.10
        )
        if energy <= close_threshold:
            state = "silence"
            target = 0.0
        elif closed_consonant:
            state = "consonant_closed"
            target = 0.0
        elif noisy_consonant:
            state = "consonant"
            consonant_level = smoothstep((energy - close_threshold) / max(open_threshold - close_threshold, 1e-5))
            target = min(energy * consonant_level, close_threshold * 1.05)
        else:
            state = "vowel"
            vowel_level = smoothstep((energy - close_threshold) / max(1.0 - close_threshold, 1e-5))
            target = max(energy, vowel_level)
        rate = attack if target > current else release
        current = current * (1.0 - rate) + target * rate
        if state in {"silence", "consonant_closed"}:
            current = 0.0
        states.append(
            MouthStateFrame(
                energy=energy,
                centroid=centroid,
                zero_crossing=zero_crossing,
                high_band_share=high_band,
                state=state,
                openness=float(np.clip(current, 0.0, 1.0)),
            )
        )
    return states


def summarize_mouth_states(states: list[MouthStateFrame]) -> dict:
    if not states:
        return {
            "total_frames": 0,
            "state_counts": {},
            "state_shares": {},
            "openness": {"min": 0.0, "mean": 0.0, "max": 0.0},
            "frames": [],
        }
    counts: dict[str, int] = {}
    for state in states:
        counts[state.state] = counts.get(state.state, 0) + 1
    openness = np.array([state.openness for state in states], dtype=np.float32)
    frames = [
        {
            "index": index,
            "state": state.state,
            "energy": round(state.energy, 4),
            "openness": round(state.openness, 4),
            "zero_crossing": round(state.zero_crossing, 4),
            "centroid": round(state.centroid, 4),
            "high_band_share": round(state.high_band_share, 4),
        }
        for index, state in enumerate(states)
    ]
    return {
        "total_frames": len(states),
        "state_counts": counts,
        "state_shares": {key: round(value / len(states), 4) for key, value in counts.items()},
        "openness": {
            "min": round(float(np.min(openness)), 4),
            "mean": round(float(np.mean(openness)), 4),
            "max": round(float(np.max(openness)), 4),
        },
        "frames": frames,
    }


def write_mouth_state_debug(path: Path, states: list[MouthStateFrame]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summarize_mouth_states(states), ensure_ascii=False, indent=2), encoding="utf-8")


def aperture_control_from_mouth_state(
    raw_openness: float,
    mouth_state: MouthStateFrame | None,
    *,
    energy_threshold: float,
) -> tuple[float, bool, bool]:
    raw_openness = float(np.clip(raw_openness, 0.0, 1.0))
    if mouth_state is None:
        return raw_openness, raw_openness <= energy_threshold, raw_openness <= energy_threshold
    if mouth_state.state in {"silence", "consonant_closed"}:
        return 0.0, True, True
    if mouth_state.state == "vowel":
        if float(mouth_state.energy) <= energy_threshold:
            return 0.0, True, True
        audio_driver = max(
            raw_openness,
            float(np.clip(mouth_state.energy, 0.0, 1.0)),
            float(np.clip(mouth_state.openness, 0.0, 1.0)),
        )
        return audio_driver, False, False
    if raw_openness <= energy_threshold:
        return 0.0, True, True
    if mouth_state.state == "consonant":
        constrained = min(float(np.clip(mouth_state.openness, 0.0, 1.0)), energy_threshold * 1.05)
        strong_consonant = (
            mouth_state.zero_crossing > 0.32
            or mouth_state.centroid > 0.55
            or mouth_state.high_band_share > 0.30
        )
        return constrained, strong_consonant, False
    return max(raw_openness, float(np.clip(mouth_state.openness, 0.0, 1.0))), False, False


def apply_vowel_release_floor(
    target_ratio: float,
    mouth_state: MouthStateFrame | None,
    *,
    min_ratio: float,
    max_ratio: float,
    target_lock: bool,
    closed_lock: bool,
) -> float:
    if mouth_state is None or mouth_state.state != "vowel" or target_lock or closed_lock:
        return target_ratio
    expected_open = max(float(mouth_state.energy), float(mouth_state.openness))
    if expected_open < 0.42:
        return target_ratio
    min_ratio = float(np.clip(min_ratio, 0.0, 0.8))
    max_ratio = float(np.clip(max_ratio, min_ratio, 0.8))
    vowel_floor = min_ratio + (max_ratio - min_ratio) * 0.60
    return max(float(target_ratio), vowel_floor)


def open_closed_priority_shape(
    openness: float,
    mouth_state: MouthStateFrame | None,
    *,
    enabled: bool,
    trigger: float,
    open_openness: float,
    target_lock: bool,
    closed_lock: bool,
) -> tuple[float, bool]:
    openness = float(np.clip(openness, 0.0, 1.0))
    if not enabled or mouth_state is None or target_lock or closed_lock:
        return openness, False
    if mouth_state.state != "vowel":
        return openness, False
    expected_open = max(float(mouth_state.energy), float(mouth_state.openness), openness)
    if expected_open < float(np.clip(trigger, 0.0, 1.0)):
        return openness, False
    adaptive_open = natural_open_shape_openness(
        openness,
        expected_open,
        trigger=trigger,
        open_openness=open_openness,
    )
    return adaptive_open, True


def natural_open_shape_openness(
    openness: float,
    expected_open: float,
    *,
    trigger: float,
    open_openness: float,
) -> float:
    openness = float(np.clip(openness, 0.0, 1.0))
    expected_open = max(openness, float(np.clip(expected_open, 0.0, 1.0)))
    trigger = float(np.clip(trigger, 0.0, 1.0))
    if expected_open < trigger:
        return openness

    max_open = float(np.clip(open_openness, 0.0, 0.92))
    medium_open = min(max_open, max(0.44, max_open * 0.58))
    transition = smoothstep((expected_open - trigger) / 0.44)
    strong_open = smoothstep((expected_open - 0.84) / 0.12)
    adaptive_open = medium_open + (max_open - medium_open) * transition + strong_open * 0.08
    return max(openness, float(np.clip(adaptive_open, 0.0, 0.92)))


def expected_open_motion(
    aperture_mode: str,
    openness: float,
    mouth_state: MouthStateFrame | None,
    *,
    trigger: float,
) -> bool:
    if aperture_mode == "closed":
        return False
    if aperture_mode == "open":
        return True
    openness = float(np.clip(openness, 0.0, 1.0))
    if openness >= 0.42:
        return True
    if mouth_state is None or mouth_state.state != "vowel":
        return False
    expected_open = max(float(mouth_state.energy), float(mouth_state.openness), openness)
    return expected_open >= float(np.clip(trigger, 0.0, 1.0))


def should_release_medium_vowel_geometry(generated_ratio: float, expected_open_value: float) -> bool:
    return float(generated_ratio) < 0.24 and 0.25 <= float(expected_open_value) <= 0.36


def should_release_strong_vowel_geometry(generated_ratio: float, expected_open_value: float) -> bool:
    return float(generated_ratio) < 0.30 and float(expected_open_value) >= 0.62


def choose_aperture_target(
    atlas: list[MouthTexture],
    mouth_points: np.ndarray,
    target_ratio: float,
    *,
    closed_lock: bool = False,
) -> MouthTexture | None:
    if not atlas:
        return None
    generated_ratio = mouth_open_ratio(mouth_points)
    # The atlas drives the state, while generated landmarks keep small frame-to-frame motion.
    if closed_lock:
        target_ratio = float(np.clip(target_ratio, 0.0, 0.8))
    else:
        target_ratio = generated_ratio * 0.18 + float(np.clip(target_ratio, 0.0, 0.8)) * 0.82
    return min(atlas, key=lambda item: abs(item.ratio - target_ratio) * 2.2 - item.score * 0.12)


def mouth_alpha_masks(
    shape: tuple[int, int],
    mouth_points: np.ndarray,
    openness: float,
    preserve_strength: float,
    force_open_shape: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    height, width = shape
    points = mouth_points.astype(np.float32)
    center = points.mean(axis=0)
    openness = float(np.clip(openness, 0.0, 1.0))
    expanded = points.copy()
    expanded[:, 0] = center[0] + (expanded[:, 0] - center[0]) * (1.34 + openness * 0.18)
    dynamic_open_gain = max(0.0, 1.0 - preserve_strength) * 0.28
    expanded[:, 1] = center[1] + (expanded[:, 1] - center[1]) * (1.55 + openness * (0.42 + dynamic_open_gain))
    expanded[:, 0] = np.clip(expanded[:, 0], 0, width - 1)
    expanded[:, 1] = np.clip(expanded[:, 1], 0, height - 1)

    outer_mask = np.zeros((height, width), dtype=np.float32)
    preserve_strength = float(np.clip(preserve_strength, 0.0, 1.0))
    generated_outer_alpha = 0.55 + openness * 0.08
    preserved_outer_alpha = 0.26 + openness * 0.05
    outer_alpha = generated_outer_alpha * (1.0 - preserve_strength) + preserved_outer_alpha * preserve_strength
    cv2.fillConvexPoly(outer_mask, cv2.convexHull(expanded[:12].astype(np.int32)), outer_alpha)
    inner_mask = np.zeros((height, width), dtype=np.float32)
    inner = expanded[12:20]
    if inner.shape[0] >= 6:
        inner_center = inner.mean(axis=0)
        inner_width = max(float(inner[:, 0].max() - inner[:, 0].min()), 1.0)
        open_boost = 0.18 if force_open_shape else 0.0
        inner_height = max(
            float(inner[:, 1].max() - inner[:, 1].min()),
            inner_width * (0.06 + openness * (0.18 + open_boost + dynamic_open_gain * 0.55)),
        )
        yy, xx = np.mgrid[0:height, 0:width]
        oval = (
            ((xx - inner_center[0]) / max(inner_width * (0.52 + openness * 0.10), 1.0)) ** 2
            + ((yy - inner_center[1]) / max(inner_height * (0.72 + openness * (0.18 + open_boost)), 1.0)) ** 2
        )
        inner_mask = np.clip(1.0 - oval, 0.0, 1.0)

    kernel = max(5, int(round(min(width, height) * 0.012)))
    if kernel % 2 == 0:
        kernel += 1
    outer_mask = cv2.GaussianBlur(outer_mask, (kernel * 2 + 1, kernel * 2 + 1), 0)
    inner_mask = cv2.GaussianBlur(inner_mask, (kernel, kernel), 0)
    generated_inner_alpha = 0.88 + openness * 0.10
    preserved_inner_alpha = 0.96 + openness * 0.03
    inner_alpha = generated_inner_alpha * (1.0 - preserve_strength) + preserved_inner_alpha * preserve_strength
    full_mask = np.maximum(outer_mask, inner_mask * inner_alpha)
    return np.clip(full_mask, 0.0, 0.92 + openness * 0.06), np.clip(inner_mask, 0.0, 1.0)


def rgb_mouth_repair(
    generated: np.ndarray,
    source: np.ndarray,
    mask: np.ndarray,
    inner_mask: np.ndarray,
    soft_cavity: bool,
    upper_cavity_lift: bool,
    mouth_points: np.ndarray | None = None,
    openness: float = 0.0,
) -> np.ndarray:
    gen = generated.astype(np.float32)
    src = source.astype(np.float32)
    mask_3 = mask[:, :, None]
    gen_luma = gen.mean(axis=2, keepdims=True)
    src_luma = src.mean(axis=2, keepdims=True)

    lip_pixels = (mask > 0.12) & (inner_mask < 0.55) & (gen_luma[:, :, 0] > 88)
    if np.any(lip_pixels):
        correction = np.clip(src[lip_pixels].mean(axis=0) - gen[lip_pixels].mean(axis=0), -28.0, 28.0)
        gen = np.clip(gen + correction * 0.38, 0, 255)

    floor_delta = 56.0 if soft_cavity else 82.0
    floor_value = 84.0 if soft_cavity else 58.0
    too_black = (inner_mask[:, :, None] > 0.18) & (gen_luma < np.maximum(src_luma - floor_delta, floor_value))
    if np.any(too_black):
        warm_cavity = np.array([116.0, 72.0, 64.0], dtype=np.float32) if soft_cavity else np.array([88.0, 56.0, 50.0], dtype=np.float32)
        lift_weight = 0.62 if soft_cavity else 0.45
        lift = gen * (1.0 - lift_weight) + warm_cavity * lift_weight
        gen = np.where(too_black, lift, gen)

    if upper_cavity_lift and mouth_points is not None and openness > 0.32:
        inner = mouth_points[12:20].astype(np.float32)
        if inner.shape[0] >= 6:
            center_y = float(inner[:, 1].mean())
            height = max(float(inner[:, 1].max() - inner[:, 1].min()), 1.0)
            yy, _ = np.mgrid[0 : generated.shape[0], 0 : generated.shape[1]]
            upper_band = yy < center_y + height * 0.16
            dead_shadow = (
                (inner_mask[:, :, None] > 0.22)
                & upper_band[:, :, None]
                & (gen_luma < 70.0)
                & (src_luma > 78.0)
            )
            if np.any(dead_shadow):
                warm_highlight = np.array([134.0, 88.0, 78.0], dtype=np.float32)
                strength = 0.22 * np.clip((openness - 0.32) / 0.36, 0.0, 1.0)
                lifted = gen * (1.0 - strength) + warm_highlight * strength
                gen = np.where(dead_shadow, lifted, gen)

    return np.clip(gen, 0, 255)


def suppress_inner_mouth_shadow(
    image: np.ndarray,
    source: np.ndarray,
    mouth_points: np.ndarray,
    inner_mask: np.ndarray,
    openness: float,
) -> np.ndarray:
    openness = float(np.clip(openness, 0.0, 1.0))
    if openness < 0.42:
        return image
    inner = mouth_points[12:20].astype(np.float32)
    outer = mouth_points[:12].astype(np.float32)
    if inner.shape[0] < 6 or outer.shape[0] < 8:
        return image

    result = image.astype(np.float32)
    source_f = source.astype(np.float32)
    result_luma = result.mean(axis=2)
    source_luma = source_f.mean(axis=2)
    inner_region = inner_mask > 0.14
    if not np.any(inner_region):
        return image

    x0, y0 = outer.min(axis=0)
    x1, y1 = outer.max(axis=0)
    width = max(float(x1 - x0), 1.0)
    height = max(float(y1 - y0), width * 0.18)
    h, w = image.shape[:2]
    xa = max(0, int(x0 - width * 0.45))
    xb = min(w, int(x1 + width * 0.45))
    ya = max(0, int(y0 - height * 1.25))
    yb = min(h, int(y1 + height * 1.35))
    local_source = source_f[ya:yb, xa:xb]
    local_mask = inner_mask[ya:yb, xa:xb]
    skin_pixels = local_source[local_mask < 0.08]
    if skin_pixels.size:
        skin_color = skin_pixels.reshape(-1, 3).mean(axis=0)
    else:
        skin_color = np.array([156.0, 116.0, 102.0], dtype=np.float32)

    warm_inner = np.clip(skin_color * np.array([0.78, 0.66, 0.64], dtype=np.float32), 82.0, 210.0)
    source_floor = np.maximum(source_luma * 0.74, 92.0)
    too_dark = inner_region & (result_luma < source_floor)
    if not np.any(too_dark):
        return image

    lift_alpha = np.clip(inner_mask * (0.34 + openness * 0.18), 0.0, 0.48)[:, :, None]
    lifted = result * (1.0 - lift_alpha) + warm_inner * lift_alpha
    return np.where(too_dark[:, :, None], lifted, result).clip(0, 255).astype(np.uint8)

def add_inner_mouth_detail(image: np.ndarray, mouth_points: np.ndarray, inner_mask: np.ndarray, openness: float) -> np.ndarray:
    openness = float(np.clip(openness, 0.0, 1.0))
    if openness < 0.36:
        return image
    result = image.astype(np.float32)
    inner = mouth_points[12:20].astype(np.float32)
    if inner.shape[0] < 6:
        return image
    center = inner.mean(axis=0)
    width = max(float(inner[:, 0].max() - inner[:, 0].min()), 1.0)
    height = max(float(inner[:, 1].max() - inner[:, 1].min()), width * 0.18)
    yy, xx = np.mgrid[0 : image.shape[0], 0 : image.shape[1]]

    tooth_y = float(inner[:, 1].min() + height * 0.34)
    tooth = np.exp(-(((xx - center[0]) / max(width * 0.34, 1.0)) ** 2 + ((yy - tooth_y) / max(height * 0.20, 1.0)) ** 2))
    tooth = tooth * inner_mask * (openness - 0.36) * 0.26
    tooth = np.clip(tooth, 0.0, 0.13)[:, :, None]
    tooth_color = np.array([220.0, 212.0, 198.0], dtype=np.float32)
    result = result * (1.0 - tooth) + tooth_color * tooth

    tongue_y = float(inner[:, 1].min() + height * 0.68)
    tongue = np.exp(-(((xx - center[0]) / max(width * 0.42, 1.0)) ** 2 + ((yy - tongue_y) / max(height * 0.24, 1.0)) ** 2))
    tongue = tongue * inner_mask * (openness - 0.36) * 0.18
    tongue = np.clip(tongue, 0.0, 0.08)[:, :, None]
    tongue_color = np.array([114.0, 64.0, 58.0], dtype=np.float32)
    result = result * (1.0 - tongue) + tongue_color * tongue
    return np.clip(result, 0, 255).astype(np.uint8)


def force_open_aperture(image: np.ndarray, mouth_points: np.ndarray, inner_mask: np.ndarray, openness: float) -> np.ndarray:
    if openness < 0.45 or cv2 is None:
        return image
    inner = mouth_points[12:20].astype(np.float32)
    outer = mouth_points[:12].astype(np.float32)
    if inner.shape[0] < 6 or outer.shape[0] < 8:
        return image

    result = image.astype(np.float32)
    center = inner.mean(axis=0)
    outer_width = max(float(outer[:, 0].max() - outer[:, 0].min()), 1.0)
    inner_height = max(float(inner[:, 1].max() - inner[:, 1].min()), outer_width * 0.08)
    height = max(inner_height, outer_width * (0.20 + openness * 0.22))
    yy, xx = np.mgrid[0 : image.shape[0], 0 : image.shape[1]]

    outer_mask = np.zeros(image.shape[:2], dtype=np.float32)
    expanded_outer = outer.copy()
    outer_center = outer.mean(axis=0)
    expanded_outer[:, 0] = outer_center[0] + (expanded_outer[:, 0] - outer_center[0]) * (1.08 + openness * 0.05)
    expanded_outer[:, 1] = outer_center[1] + (expanded_outer[:, 1] - outer_center[1]) * (1.18 + openness * 0.12)
    cv2.fillConvexPoly(outer_mask, cv2.convexHull(expanded_outer.astype(np.int32)), 1.0)
    outer_mask = cv2.GaussianBlur(outer_mask, (11, 11), 0)

    cavity_y = float(inner[:, 1].min() + height * 0.48)
    cavity = np.exp(
        -(
            ((xx - center[0]) / max(outer_width * (0.22 + openness * 0.07), 1.0)) ** 2
            + ((yy - cavity_y) / max(height * (0.24 + openness * 0.10), 1.0)) ** 2
        )
    )
    open_mask = np.clip(cavity * outer_mask, 0.0, 1.0)
    open_mask = cv2.GaussianBlur(open_mask.astype(np.float32), (7, 7), 0)
    cavity_alpha = np.clip(open_mask * (0.52 + openness * 0.20), 0.0, 0.68)[:, :, None]
    skin = result[
        max(0, int(center[1] - height * 1.5)) : min(image.shape[0], int(center[1] + height * 1.8)),
        max(0, int(center[0] - outer_width * 0.9)) : min(image.shape[1], int(center[0] + outer_width * 0.9)),
    ]
    skin_mean = skin.reshape(-1, 3).mean(axis=0) if skin.size else np.array([150.0, 108.0, 96.0], dtype=np.float32)
    cavity_color = np.array(
        [
            max(54.0, skin_mean[0] * 0.38),
            max(32.0, skin_mean[1] * 0.28),
            max(34.0, skin_mean[2] * 0.30),
        ],
        dtype=np.float32,
    )
    result = result * (1.0 - cavity_alpha) + cavity_color * cavity_alpha

    tooth_y = float(cavity_y - height * 0.16)
    tooth = np.exp(
        -(
            ((xx - center[0]) / max(outer_width * 0.22, 1.0)) ** 2
            + ((yy - tooth_y) / max(height * 0.075, 1.0)) ** 2
        )
    )
    tooth = cv2.GaussianBlur((tooth * open_mask).astype(np.float32), (5, 5), 0)
    tooth_alpha = np.clip(tooth * (openness - 0.42) * 0.38, 0.0, 0.18)[:, :, None]
    tooth_color = np.array([222.0, 212.0, 198.0], dtype=np.float32)
    result = result * (1.0 - tooth_alpha) + tooth_color * tooth_alpha

    tongue_y = float(cavity_y + height * 0.30)
    tongue = np.exp(
        -(
            ((xx - center[0]) / max(outer_width * 0.32, 1.0)) ** 2
            + ((yy - tongue_y) / max(height * 0.16, 1.0)) ** 2
        )
    )
    tongue = cv2.GaussianBlur((tongue * open_mask).astype(np.float32), (5, 5), 0)
    tongue_alpha = np.clip(tongue * (openness - 0.42) * 0.20, 0.0, 0.09)[:, :, None]
    tongue_color = np.array([122.0, 62.0, 58.0], dtype=np.float32)
    result = result * (1.0 - tongue_alpha) + tongue_color * tongue_alpha
    return np.clip(result, 0, 255).astype(np.uint8)


def generated_open_priority_blend(
    source: np.ndarray,
    generated: np.ndarray,
    mouth_points: np.ndarray,
    openness: float,
    expected_open_value: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    height, width = source.shape[:2]
    outer = mouth_points[:12].astype(np.float32)
    inner = mouth_points[12:20].astype(np.float32)
    if outer.shape[0] < 8 or inner.shape[0] < 6 or cv2 is None:
        mask, inner_mask = mouth_alpha_masks(source.shape[:2], mouth_points, openness, 0.0, True)
        blended = np.clip(source.astype(np.float32) * (1.0 - mask[:, :, None]) + generated.astype(np.float32) * mask[:, :, None], 0, 255).astype(np.uint8)
        return blended, mask, inner_mask

    generated_ratio = mouth_open_ratio(mouth_points)
    geometry_open = smoothstep((generated_ratio - 0.29) / 0.08)
    expected_open_value = max(float(np.clip(expected_open_value, 0.0, 1.0)), float(np.clip(openness, 0.0, 1.0)))
    audio_open = natural_open_shape_openness(
        openness,
        expected_open_value,
        trigger=0.25,
        open_openness=0.78,
    )
    geometry_bonus = geometry_open * smoothstep((expected_open_value - 0.58) / 0.22) * 0.08
    openness = max(float(np.clip(openness, 0.0, 1.0)), float(np.clip(audio_open + geometry_bonus, 0.0, 0.90)))

    center = outer.mean(axis=0)
    expanded = outer.copy()
    expanded[:, 0] = center[0] + (expanded[:, 0] - center[0]) * (1.24 + openness * 0.08)
    expanded[:, 1] = center[1] + (expanded[:, 1] - center[1]) * (1.36 + openness * 0.18)
    expanded[:, 0] = np.clip(expanded[:, 0], 0, width - 1)
    expanded[:, 1] = np.clip(expanded[:, 1], 0, height - 1)

    outer_mask = np.zeros((height, width), dtype=np.float32)
    cv2.fillConvexPoly(outer_mask, cv2.convexHull(expanded.astype(np.int32)), 1.0)
    kernel = max(5, int(round(min(width, height) * 0.012)))
    if kernel % 2 == 0:
        kernel += 1
    outer_mask = cv2.GaussianBlur(outer_mask, (kernel * 2 + 1, kernel * 2 + 1), 0)

    inner_center = inner.mean(axis=0)
    inner_width = max(float(inner[:, 0].max() - inner[:, 0].min()), 1.0)
    inner_height = max(
        float(inner[:, 1].max() - inner[:, 1].min()),
        inner_width * (0.12 + openness * 0.18),
    )
    yy, xx = np.mgrid[0:height, 0:width]
    oval = (
        ((xx - inner_center[0]) / max(inner_width * (0.62 + openness * 0.08), 1.0)) ** 2
        + ((yy - inner_center[1]) / max(inner_height * (0.96 + openness * 0.18), 1.0)) ** 2
    )
    inner_mask = cv2.GaussianBlur(np.clip(1.0 - oval, 0.0, 1.0).astype(np.float32), (kernel, kernel), 0)

    source_f = source.astype(np.float32)
    generated_f = generated.astype(np.float32)
    gen_luma = generated_f.mean(axis=2)
    src_luma = source_f.mean(axis=2)
    lip_pixels = (outer_mask > 0.18) & (inner_mask < 0.42) & (gen_luma > 70.0)
    if np.any(lip_pixels):
        correction = np.clip(source_f[lip_pixels].mean(axis=0) - generated_f[lip_pixels].mean(axis=0), -22.0, 22.0)
        generated_f = np.clip(generated_f + correction * 0.22, 0, 255)

    dark_patch = (inner_mask > 0.20) & (gen_luma < np.maximum(src_luma - 95.0, 38.0))
    if np.any(dark_patch):
        warm_floor = np.maximum(source_f * 0.72, np.array([92.0, 74.0, 68.0], dtype=np.float32))
        lifted = generated_f * 0.78 + warm_floor * 0.22
        generated_f = np.where(dark_patch[:, :, None], lifted, generated_f)

    alpha = np.maximum(outer_mask * (0.72 + openness * 0.14), inner_mask * (0.92 + openness * 0.06))
    alpha = np.clip(alpha, 0.0, 0.98)
    edge = np.clip(outer_mask - inner_mask * 0.72, 0.0, 1.0)
    blur = cv2.GaussianBlur(generated_f.astype(np.uint8), (0, 0), 0.65).astype(np.float32)
    generated_f = generated_f * (1.0 - edge[:, :, None] * 0.14) + blur * edge[:, :, None] * 0.14
    blended = np.clip(source_f * (1.0 - alpha[:, :, None]) + generated_f * alpha[:, :, None], 0, 255).astype(np.uint8)
    if should_release_medium_vowel_geometry(generated_ratio, expected_open_value):
        blended = warp_open_mouth_geometry(
            blended,
            mouth_points,
            openness,
            enabled=True,
            strength=0.26,
            max_ratio=0.29,
        )
    elif should_release_strong_vowel_geometry(generated_ratio, expected_open_value):
        released_openness = max(openness, min(0.92, expected_open_value * 0.92))
        blended = warp_open_mouth_geometry(
            blended,
            mouth_points,
            released_openness,
            enabled=True,
            strength=0.58,
            max_ratio=0.42,
        )
        blended = suppress_inner_mouth_shadow(blended, source, mouth_points, inner_mask, released_openness)
    return blended, alpha.astype(np.float32), inner_mask.astype(np.float32)


def target_open_geometry_ratio(
    mouth_points: np.ndarray,
    openness: float,
    *,
    max_ratio: float = 0.38,
) -> float:
    current_ratio = mouth_open_ratio(mouth_points)
    openness = float(np.clip(openness, 0.0, 1.0))
    max_ratio = float(np.clip(max_ratio, 0.18, 0.58))
    open_floor = 0.22 + openness * 0.20
    return max(current_ratio, min(max_ratio, open_floor))


def open_geometry_target_points(
    mouth_points: np.ndarray,
    openness: float,
    *,
    max_ratio: float = 0.38,
) -> np.ndarray:
    target = mouth_points.astype(np.float32).copy()
    inner = target[12:20]
    outer = target[:12]
    if inner.shape[0] < 6 or outer.shape[0] < 8:
        return target

    outer_width = max(float(outer[:, 0].max() - outer[:, 0].min()), 1.0)
    current_height = max(float(inner[:, 1].max() - inner[:, 1].min()), outer_width * 0.06)
    target_height = outer_width * target_open_geometry_ratio(mouth_points, openness, max_ratio=max_ratio)
    delta = max(0.0, (target_height - current_height) * 0.5)
    if delta <= 0.1:
        return target

    upper_inner = [13, 14, 15]
    lower_inner = [17, 18, 19]
    upper_outer = [2, 3, 4]
    lower_outer = [8, 9, 10]
    target[upper_inner, 1] -= delta
    target[lower_inner, 1] += delta
    target[[12, 16], 1] += delta * 0.08
    target[upper_outer, 1] -= delta * 0.22
    target[lower_outer, 1] += delta * 0.38
    return target


def warp_open_mouth_geometry(
    image: np.ndarray,
    mouth_points: np.ndarray,
    openness: float,
    *,
    enabled: bool,
    strength: float = 0.72,
    max_ratio: float = 0.38,
) -> np.ndarray:
    if not enabled or openness < 0.42 or cv2 is None:
        return image
    source_points = mouth_points.astype(np.float32)
    inner = source_points[12:20]
    outer = source_points[:12]
    if inner.shape[0] < 6 or outer.shape[0] < 8:
        return image

    target_points = open_geometry_target_points(source_points, openness, max_ratio=max_ratio)
    displacement = target_points - source_points
    if float(np.max(np.abs(displacement[:, 1]))) <= 0.1:
        return image

    height, width = image.shape[:2]
    center = inner.mean(axis=0)
    outer_width = max(float(outer[:, 0].max() - outer[:, 0].min()), 1.0)
    outer_height = max(float(outer[:, 1].max() - outer[:, 1].min()), outer_width * 0.18)
    strength = float(np.clip(strength, 0.0, 1.0))
    if strength <= 0.0:
        return image

    combined = np.vstack([source_points, target_points])
    x_min = max(0, int(combined[:, 0].min() - outer_width * 0.28))
    x_max = min(width, int(combined[:, 0].max() + outer_width * 0.28))
    y_min = max(0, int(combined[:, 1].min() - outer_height * 0.62))
    y_max = min(height, int(combined[:, 1].max() + outer_height * 0.74))
    if x_max - x_min < 8 or y_max - y_min < 8:
        return image

    region = image[y_min:y_max, x_min:x_max]
    yy, xx = np.mgrid[y_min:y_max, x_min:x_max].astype(np.float32)
    horizontal = np.exp(-(((xx - center[0]) / max(outer_width * 0.58, 1.0)) ** 2))
    vertical = np.exp(-(((yy - center[1]) / max(outer_height * 1.08, 1.0)) ** 2))
    mouth_weight = cv2.GaussianBlur((horizontal * vertical).astype(np.float32), (9, 9), 0)
    mouth_weight = np.clip(mouth_weight * strength, 0.0, 1.0)
    if float(mouth_weight.max()) <= 0.02:
        return image

    local_h, local_w = region.shape[:2]
    local_y, local_x = np.mgrid[0:local_h, 0:local_w]
    disp_x = np.zeros((local_h, local_w), dtype=np.float32)
    disp_y = np.zeros((local_h, local_w), dtype=np.float32)
    weight_sum = np.zeros((local_h, local_w), dtype=np.float32)
    sigma = max(outer_width * 0.28, 3.0)
    local_x_abs = local_x.astype(np.float32) + float(x_min)
    local_y_abs = local_y.astype(np.float32) + float(y_min)
    control_indices = [2, 3, 4, 8, 9, 10, 12, 13, 14, 15, 16, 17, 18, 19]
    for point_index in control_indices:
        dx = local_x_abs - target_points[point_index, 0]
        dy = local_y_abs - target_points[point_index, 1]
        weights = np.exp(-(dx * dx + dy * dy) / max(sigma * sigma, 1.0)).astype(np.float32)
        disp_x += weights * displacement[point_index, 0]
        disp_y += weights * displacement[point_index, 1]
        weight_sum += weights
    weight_sum = np.maximum(weight_sum, 1e-5)
    disp_x = disp_x / weight_sum * mouth_weight
    disp_y = disp_y / weight_sum * mouth_weight
    map_x = (local_x.astype(np.float32) - disp_x).astype(np.float32)
    map_y = (local_y.astype(np.float32) - disp_y).astype(np.float32)
    warped = cv2.remap(
        region,
        map_x,
        map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT_101,
    ).astype(np.float32)
    alpha = np.clip(mouth_weight * (0.62 + openness * 0.22), 0.0, 0.84)[:, :, None]
    result = image.astype(np.float32)
    result[y_min:y_max, x_min:x_max] = region.astype(np.float32) * (1.0 - alpha) + warped * alpha
    return np.clip(result, 0, 255).astype(np.uint8)


def warp_lower_lip_open(image: np.ndarray, mouth_points: np.ndarray, inner_mask: np.ndarray, openness: float) -> np.ndarray:
    if openness < 0.45 or cv2 is None:
        return image
    inner = mouth_points[12:20].astype(np.float32)
    outer = mouth_points[:12].astype(np.float32)
    if inner.shape[0] < 6 or outer.shape[0] < 8:
        return image

    height, width = image.shape[:2]
    center = inner.mean(axis=0)
    outer_width = max(float(outer[:, 0].max() - outer[:, 0].min()), 1.0)
    outer_height = max(float(outer[:, 1].max() - outer[:, 1].min()), outer_width * 0.16)
    shift = outer_width * (0.055 + openness * 0.085)
    x_min = max(0, int(outer[:, 0].min() - outer_width * 0.20))
    x_max = min(width, int(outer[:, 0].max() + outer_width * 0.20))
    y_min = max(0, int(outer[:, 1].min() - outer_height * 0.35))
    y_max = min(height, int(outer[:, 1].max() + shift + outer_height * 0.55))
    if x_max - x_min < 8 or y_max - y_min < 8:
        return image

    region = image[y_min:y_max, x_min:x_max].astype(np.float32)
    yy, xx = np.mgrid[y_min:y_max, x_min:x_max]
    lower_weight = np.clip((yy - center[1]) / max(outer_height * 0.48, 1.0), 0.0, 1.0)
    horizontal_falloff = np.exp(-(((xx - center[0]) / max(outer_width * 0.58, 1.0)) ** 2))
    local_mask = inner_mask[y_min:y_max, x_min:x_max]
    warp_weight = cv2.GaussianBlur((lower_weight * horizontal_falloff * local_mask).astype(np.float32), (7, 7), 0)
    if warp_weight.max() <= 0.02:
        return image

    local_h, local_w = region.shape[:2]
    local_y, local_x = np.mgrid[0:local_h, 0:local_w]
    map_x = local_x.astype(np.float32)
    map_y = (local_y - shift * warp_weight).astype(np.float32)
    warped = cv2.remap(
        region.astype(np.uint8),
        map_x,
        map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    ).astype(np.float32)
    alpha = np.clip(warp_weight * (0.42 + openness * 0.22), 0.0, 0.58)[:, :, None]
    result = image.copy().astype(np.float32)
    result[y_min:y_max, x_min:x_max] = region * (1.0 - alpha) + warped * alpha
    return np.clip(result, 0, 255).astype(np.uint8)


def transfer_bright_mouth_detail(
    image: np.ndarray,
    detail: np.ndarray | None,
    mouth_points: np.ndarray,
    detail_mouth_points: np.ndarray | None,
    inner_mask: np.ndarray,
    openness: float,
    align_detail: bool,
) -> np.ndarray:
    if detail is None or openness < 0.34:
        return image
    result = image.astype(np.float32)
    if align_detail and detail_mouth_points is not None and detail_mouth_points.shape == mouth_points.shape:
        detail = align_detail_frame(detail, detail_mouth_points, mouth_points, image.shape[:2])
    detail_f = detail.astype(np.float32)
    inner = mouth_points[12:20].astype(np.float32)
    if inner.shape[0] < 6:
        return image
    center_y = float(inner[:, 1].mean())
    yy, _ = np.mgrid[0 : image.shape[0], 0 : image.shape[1]]
    upper = yy < center_y + max(float(inner[:, 1].max() - inner[:, 1].min()) * 0.16, 2.0)
    result_luma = result.mean(axis=2)
    detail_luma = detail_f.mean(axis=2)
    bright = (
        (inner_mask > 0.18)
        & upper
        & (detail_luma > result_luma + 5.0)
        & (detail_luma > 108.0)
        & (detail_luma < 238.0)
    )
    if not np.any(bright):
        return image
    strength = np.clip((detail_luma - result_luma - 5.0) / 42.0, 0.0, 1.0) * inner_mask * (openness - 0.34) * 0.44
    strength = cv2.GaussianBlur(strength.astype(np.float32), (5, 5), 0)
    alpha = np.where(bright, strength, 0.0)[:, :, None]
    return np.clip(result * (1.0 - alpha) + detail_f * alpha, 0, 255).astype(np.uint8)


def transfer_texture_mouth(
    image: np.ndarray,
    texture: MouthTexture | None,
    mouth_points: np.ndarray,
    inner_mask: np.ndarray,
    openness: float,
) -> np.ndarray:
    if texture is None or openness < 0.34:
        return image
    aligned = align_detail_frame(texture.frame, texture.mouth_points, mouth_points, image.shape[:2])
    result = image.astype(np.float32)
    aligned_f = aligned.astype(np.float32)
    result_luma = result.mean(axis=2)
    texture_luma = aligned_f.mean(axis=2)

    inner = mouth_points[12:20].astype(np.float32)
    if inner.shape[0] < 6:
        return image
    center_y = float(inner[:, 1].mean())
    height = max(float(inner[:, 1].max() - inner[:, 1].min()), 1.0)
    yy, _ = np.mgrid[0 : image.shape[0], 0 : image.shape[1]]
    upper_inner = yy < center_y + height * 0.22

    usable_texture = (inner_mask > 0.15) & (texture_luma > 82.0) & (texture_luma < 238.0)
    black_fix = (inner_mask > 0.22) & upper_inner & (result_luma < 62.0) & (texture_luma > result_luma + 18.0)
    bright_detail = usable_texture & upper_inner & (texture_luma > result_luma + 4.0) & (texture_luma > 105.0)
    active = black_fix | bright_detail
    if not np.any(active):
        return image

    alpha = np.zeros_like(inner_mask, dtype=np.float32)
    alpha = np.where(black_fix, 0.16, alpha)
    alpha = np.where(bright_detail, np.maximum(alpha, 0.18), alpha)
    alpha *= inner_mask * np.clip((openness - 0.30) / 0.42, 0.0, 1.0)
    alpha = cv2.GaussianBlur(alpha.astype(np.float32), (5, 5), 0)
    alpha = np.where(active, alpha, 0.0)[:, :, None]
    return np.clip(result * (1.0 - alpha) + aligned_f * alpha, 0, 255).astype(np.uint8)


def transfer_aperture_target(
    image: np.ndarray,
    target: MouthTexture | None,
    mouth_points: np.ndarray,
    inner_mask: np.ndarray,
    openness: float,
    strength: float,
    closed_lock: bool = False,
) -> np.ndarray:
    if target is None or strength <= 0 or cv2 is None:
        return image
    aligned = align_detail_frame(target.frame, target.mouth_points, mouth_points, image.shape[:2])
    result = image.astype(np.float32)
    aligned_f = aligned.astype(np.float32)
    height, width = image.shape[:2]
    outer = mouth_points[:12].astype(np.float32)
    if outer.shape[0] < 8:
        return image
    mask = np.zeros((height, width), dtype=np.float32)
    center = outer.mean(axis=0)
    expanded = outer.copy()
    expanded[:, 0] = center[0] + (expanded[:, 0] - center[0]) * 1.18
    expanded[:, 1] = center[1] + (expanded[:, 1] - center[1]) * 1.24
    cv2.fillConvexPoly(mask, cv2.convexHull(expanded.astype(np.int32)), 1.0)
    kernel = max(5, int(round(min(width, height) * 0.010)))
    if kernel % 2 == 0:
        kernel += 1
    mask = cv2.GaussianBlur(mask, (kernel, kernel), 0)
    openness = float(np.clip(openness, 0.0, 1.0))
    state_strength = float(np.clip(strength, 0.0, 1.0)) * (0.58 - openness * 0.26)
    if closed_lock:
        state_strength = max(state_strength, float(np.clip(strength, 0.0, 1.0)) * 0.82)
    lip_alpha = np.clip(mask * state_strength, 0.0, 0.58 if closed_lock else 0.42)
    inner_alpha = np.clip(inner_mask * state_strength * (0.78 if closed_lock else 0.55), 0.0, 0.34 if closed_lock else 0.20)
    alpha = np.maximum(lip_alpha, inner_alpha)[:, :, None]
    return np.clip(result * (1.0 - alpha) + aligned_f * alpha, 0, 255).astype(np.uint8)


def align_detail_frame(
    detail: np.ndarray,
    detail_mouth_points: np.ndarray,
    target_mouth_points: np.ndarray,
    shape: tuple[int, int],
) -> np.ndarray:
    src = detail_mouth_points.astype(np.float32)
    dst = target_mouth_points.astype(np.float32)
    if src.shape[0] < 20 or dst.shape[0] < 20:
        return detail
    src_ref = np.vstack([src[:12], src[12:20]])
    dst_ref = np.vstack([dst[:12], dst[12:20]])
    matrix, _ = cv2.estimateAffinePartial2D(src_ref, dst_ref, method=cv2.LMEDS)
    if matrix is None:
        return detail
    height, width = shape
    return cv2.warpAffine(
        detail,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT_101,
    )


def blend_mouth_only(
    source: np.ndarray,
    generated: np.ndarray,
    detail_generated: np.ndarray | None,
    texture: MouthTexture | None,
    aperture_target: MouthTexture | None,
    mouth_points: np.ndarray,
    detail_mouth_points: np.ndarray | None,
    openness: float,
    preserve_strength: float,
    seamless_edge: bool,
    detail_restore: bool,
    align_detail: bool,
    soft_cavity: bool,
    upper_cavity_lift: bool,
    force_open_shape: bool,
    open_geometry_warp: bool,
    open_geometry_strength: float,
    open_geometry_max_ratio: float,
    open_generated_priority: bool,
    expected_open_value: float,
    aperture_atlas_strength: float,
    closed_lock: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if force_open_shape and open_generated_priority:
        blended, mask, inner_mask = generated_open_priority_blend(
            source,
            generated,
            mouth_points,
            openness,
            expected_open_value,
        )
        if detail_restore:
            blended = restore_local_detail(blended, source, mask, inner_mask, openness)
        return blended, mask, inner_mask

    mask, inner_mask = mouth_alpha_masks(
        source.shape[:2],
        mouth_points,
        openness,
        preserve_strength,
        force_open_shape,
    )
    repaired = rgb_mouth_repair(
        generated,
        source,
        mask,
        inner_mask,
        soft_cavity,
        upper_cavity_lift,
        mouth_points,
        openness,
    )
    repaired = transfer_bright_mouth_detail(
        repaired,
        detail_generated,
        mouth_points,
        detail_mouth_points,
        inner_mask,
        openness,
        align_detail,
    )
    repaired = transfer_aperture_target(
        repaired,
        aperture_target,
        mouth_points,
        inner_mask,
        openness,
        aperture_atlas_strength,
        closed_lock,
    )
    repaired = transfer_texture_mouth(repaired, texture, mouth_points, inner_mask, openness)
    repaired = add_inner_mouth_detail(repaired, mouth_points, inner_mask, openness)
    repaired = warp_open_mouth_geometry(
        repaired,
        mouth_points,
        openness,
        enabled=force_open_shape and open_geometry_warp,
        strength=open_geometry_strength,
        max_ratio=open_geometry_max_ratio,
    )
    if force_open_shape:
        repaired = force_open_aperture(repaired, mouth_points, inner_mask, openness)
    edge_mask = np.clip(mask - inner_mask * 0.72, 0.0, 1.0)
    edge_blur = cv2.GaussianBlur(repaired, (0, 0), 0.9)
    repaired = np.clip(repaired.astype(np.float32) * (1.0 - edge_mask[:, :, None] * 0.22) + edge_blur.astype(np.float32) * edge_mask[:, :, None] * 0.22, 0, 255)
    alpha = mask[:, :, None]
    blended = np.clip(source.astype(np.float32) * (1.0 - alpha) + repaired.astype(np.float32) * alpha, 0, 255).astype(np.uint8)
    if seamless_edge:
        blended = seamless_edge_blend(source, blended, mask, inner_mask)
    if detail_restore:
        blended = restore_local_detail(blended, source, mask, inner_mask, openness)
    return blended, mask, inner_mask


def restore_local_detail(
    blended: np.ndarray,
    source: np.ndarray,
    mask: np.ndarray,
    inner_mask: np.ndarray,
    openness: float,
) -> np.ndarray:
    result = blended.astype(np.float32)
    blur = cv2.GaussianBlur(blended, (0, 0), 0.85).astype(np.float32)
    generated_detail = np.clip(result - blur, -16.0, 16.0)

    source_blur = cv2.GaussianBlur(source, (0, 0), 0.85).astype(np.float32)
    source_detail = np.clip(source.astype(np.float32) - source_blur, -10.0, 10.0)

    lip_line = np.clip(mask - inner_mask * 0.62, 0.0, 1.0)
    lip_line = cv2.GaussianBlur(lip_line.astype(np.float32), (5, 5), 0)
    inner = cv2.GaussianBlur(inner_mask.astype(np.float32), (3, 3), 0)

    openness = float(np.clip(openness, 0.0, 1.0))
    lip_strength = (0.10 + (1.0 - openness) * 0.05) * lip_line
    inner_strength = (0.05 + openness * 0.07) * inner
    detail = source_detail * lip_strength[:, :, None] + generated_detail * inner_strength[:, :, None]
    return np.clip(result + detail, 0, 255).astype(np.uint8)


def seamless_edge_blend(source: np.ndarray, blended: np.ndarray, mask: np.ndarray, inner_mask: np.ndarray) -> np.ndarray:
    edge_mask = np.clip(mask - inner_mask * 0.82, 0.0, 1.0)
    if edge_mask.max() <= 0.08:
        return blended
    binary = (edge_mask > 0.10).astype(np.uint8) * 255
    points = cv2.findNonZero(binary)
    if points is None:
        return blended
    x, y, w, h = cv2.boundingRect(points)
    pad = 8
    x1 = max(0, x - pad)
    y1 = max(0, y - pad)
    x2 = min(source.shape[1], x + w + pad)
    y2 = min(source.shape[0], y + h + pad)
    if x2 - x1 < 4 or y2 - y1 < 4:
        return blended
    local_mask = binary[y1:y2, x1:x2]
    local_src = cv2.cvtColor(blended[y1:y2, x1:x2], cv2.COLOR_RGB2BGR)
    local_dst = cv2.cvtColor(source[y1:y2, x1:x2], cv2.COLOR_RGB2BGR)
    center = ((x2 - x1) // 2, (y2 - y1) // 2)
    try:
        mixed = cv2.seamlessClone(local_src, local_dst, local_mask, center, cv2.MIXED_CLONE)
    except cv2.error:
        return blended
    result = blended.copy()
    # Keep inner mouth from the alpha result; use Poisson only near the boundary.
    mixed_rgb = cv2.cvtColor(mixed, cv2.COLOR_BGR2RGB)
    local_edge = (edge_mask[y1:y2, x1:x2] * 0.55)[:, :, None]
    patch = blended[y1:y2, x1:x2].astype(np.float32) * (1.0 - local_edge) + mixed_rgb.astype(np.float32) * local_edge
    result[y1:y2, x1:x2] = np.clip(patch, 0, 255).astype(np.uint8)
    return result


def temporal_refine(
    current: np.ndarray,
    previous: np.ndarray | None,
    mask: np.ndarray,
    inner_mask: np.ndarray,
    openness_delta: float,
) -> np.ndarray:
    if previous is None or previous.shape != current.shape:
        return current
    motion = float(np.clip(openness_delta / 0.28, 0.0, 1.0))
    edge_mask = np.clip(mask - inner_mask * 0.78, 0.0, 1.0)
    edge_mask = cv2.GaussianBlur(edge_mask.astype(np.float32), (9, 9), 0)
    strength = 0.18 * (1.0 - motion) + 0.055 * motion
    alpha = (edge_mask * strength)[:, :, None]
    return np.clip(current.astype(np.float32) * (1.0 - alpha) + previous.astype(np.float32) * alpha, 0, 255).astype(np.uint8)


def blend_generated_mouth(
    source: Path,
    generated: Path,
    detail_generated: Path | None,
    texture_source: Path | None,
    audio: Path,
    output: Path,
    preserve_lips: bool,
    dynamic_preserve: bool,
    seamless_edge: bool,
    detail_restore: bool,
    align_detail: bool,
    soft_cavity: bool,
    upper_cavity_lift: bool,
    aperture_mode: str,
    forced_openness: float | None,
    aperture_atlas_source: Path | None,
    aperture_atlas_strength: float,
    aperture_energy_threshold: float,
    aperture_min_ratio: float,
    aperture_max_ratio: float,
    aperture_attack: float,
    aperture_release: float,
    open_closed_priority: bool,
    open_shape_trigger: float,
    open_shape_openness: float,
    open_geometry_warp: bool,
    open_geometry_strength: float,
    open_geometry_max_ratio: float,
    open_generated_priority: bool,
    texture_samples: int,
    texture_top_k: int,
    mouth_state_debug_output: Path | None = None,
) -> None:
    if cv2 is None:
        raise RuntimeError("OpenCV is required for landmark mouth blending.")
    source_frames, fps = read_frames(source)
    generated_frames, _ = read_frames(generated)
    detail_frames = read_frames(detail_generated)[0] if detail_generated is not None else None
    frame_count = min(len(source_frames), len(generated_frames), len(detail_frames) if detail_frames is not None else len(generated_frames))
    texture_atlas = scan_mouth_textures(texture_source, source_frames[0].shape[:2], texture_samples, texture_top_k)
    aperture_atlas = scan_aperture_atlas(aperture_atlas_source, source_frames[0].shape[:2], texture_samples, texture_top_k)
    samples, audio_rate = read_audio(audio)
    resampled_audio = resample_linear(samples, audio_rate, SAMPLE_RATE)
    levels = frame_audio_levels(resampled_audio, SAMPLE_RATE, fps, frame_count)
    mouth_states = audio_mouth_state_controller(
        resampled_audio,
        SAMPLE_RATE,
        fps,
        frame_count,
        close_threshold=aperture_energy_threshold,
        attack=max(aperture_attack, 0.82),
        release=max(aperture_release, 0.72),
    )
    if mouth_state_debug_output is not None:
        write_mouth_state_debug(mouth_state_debug_output, mouth_states)

    blended_frames: list[np.ndarray] = []
    previous_box: tuple[int, int, int, int] | None = None
    previous_mouth: np.ndarray | None = None
    previous_detail_mouth: np.ndarray | None = None
    previous_output: np.ndarray | None = None
    previous_openness = 0.0
    smoothed_aperture_ratio: float | None = None
    aperture_attack = float(np.clip(aperture_attack, 0.0, 1.0))
    aperture_release = float(np.clip(aperture_release, 0.0, 1.0))
    for index in range(frame_count):
        original = source_frames[index].copy()
        generated_frame = generated_frames[index]
        detail_frame = detail_frames[index] if detail_frames is not None else None
        face_box = estimate_face_box(original, previous_box)
        previous_box = face_box
        openness = float(levels[min(index, len(levels) - 1)]) if len(levels) else 0.0
        if aperture_mode == "open":
            openness = float(np.clip(0.72 if forced_openness is None else forced_openness, 0.0, 1.0))
        elif aperture_mode == "closed":
            openness = float(np.clip(0.02 if forced_openness is None else forced_openness, 0.0, 1.0))
        mouth_state = mouth_states[min(index, len(mouth_states) - 1)] if mouth_states else None

        # Closed-mouth tuning should keep the original lip contour. Open/auto
        # modes use Wav2Lip geometry first, then fall back to the source.
        if aperture_mode == "closed":
            mouth_points = detect_mouth_points(original, face_box)
            if mouth_points is None:
                mouth_points = detect_mouth_points(generated_frame, face_box)
        else:
            mouth_points = detect_mouth_points(generated_frame, face_box)
            if mouth_points is None:
                mouth_points = detect_mouth_points(original, face_box)
        if mouth_points is not None and previous_mouth is not None and previous_mouth.shape == mouth_points.shape:
            # Expected-open frames need to keep the generated mouth geometry;
            # the default heavy smoothing can pull vowels back toward the
            # previous closed contour.
            open_motion = expected_open_motion(
                aperture_mode,
                openness,
                mouth_state,
                trigger=open_shape_trigger,
            )
            if open_motion:
                mouth_points = previous_mouth * 0.25 + mouth_points * 0.75
            else:
                mouth_points = previous_mouth * 0.60 + mouth_points * 0.40
        if mouth_points is not None:
            previous_mouth = mouth_points
        detail_mouth_points = None
        if detail_frame is not None:
            detail_mouth_points = detect_mouth_points(detail_frame, face_box)
            if detail_mouth_points is not None and previous_detail_mouth is not None and previous_detail_mouth.shape == detail_mouth_points.shape:
                detail_mouth_points = previous_detail_mouth * 0.60 + detail_mouth_points * 0.40
            if detail_mouth_points is not None:
                previous_detail_mouth = detail_mouth_points

        if mouth_points is not None:
            texture = choose_mouth_texture(texture_atlas, mouth_points, openness)
            aperture_driver, target_lock, closed_lock = aperture_control_from_mouth_state(
                openness,
                mouth_state,
                energy_threshold=aperture_energy_threshold,
            )
            if aperture_mode == "open":
                aperture_driver = openness
                target_lock = False
                closed_lock = False
            elif aperture_mode == "closed":
                aperture_driver = 0.0
                target_lock = True
                closed_lock = True
            render_openness, force_open_shape = open_closed_priority_shape(
                openness,
                mouth_state,
                enabled=open_closed_priority,
                trigger=open_shape_trigger,
                open_openness=open_shape_openness,
                target_lock=target_lock,
                closed_lock=closed_lock,
            )
            if aperture_mode == "open":
                force_open_shape = True
                render_openness = openness
            expected_open_value = openness
            if mouth_state is not None:
                expected_open_value = max(float(mouth_state.energy), float(mouth_state.openness), openness)
            if dynamic_preserve:
                # Weak/closed frames keep the original lip texture; strong
                # visual-open frames let the generated mouth shape drive.
                motion_open = float(np.clip((render_openness - 0.26) / 0.34, 0.0, 1.0))
                motion_open = motion_open * motion_open * (3.0 - 2.0 * motion_open)
                preserve_strength = 1.0 - motion_open * 0.92
            else:
                preserve_strength = 1.0 if preserve_lips else 0.0
            target_aperture_ratio = aperture_ratio_from_energy(
                aperture_driver,
                energy_threshold=aperture_energy_threshold,
                min_ratio=aperture_min_ratio,
                max_ratio=aperture_max_ratio,
            )
            target_aperture_ratio = apply_vowel_release_floor(
                target_aperture_ratio,
                mouth_state,
                min_ratio=aperture_min_ratio,
                max_ratio=aperture_max_ratio,
                target_lock=target_lock,
                closed_lock=closed_lock,
            )
            if smoothed_aperture_ratio is None:
                smoothed_aperture_ratio = target_aperture_ratio
            else:
                rate = aperture_attack if target_aperture_ratio > smoothed_aperture_ratio else aperture_release
                smoothed_aperture_ratio = (
                    smoothed_aperture_ratio * (1.0 - rate) + target_aperture_ratio * rate
                )
            aperture_target = choose_aperture_target(
                aperture_atlas,
                mouth_points,
                smoothed_aperture_ratio,
                closed_lock=target_lock,
            )
            blended, mask, inner_mask = blend_mouth_only(
                original,
                generated_frame,
                detail_frame,
                texture,
                aperture_target,
                mouth_points,
                detail_mouth_points,
                render_openness,
                preserve_strength,
                seamless_edge,
                detail_restore,
                align_detail,
                soft_cavity,
                upper_cavity_lift,
                force_open_shape,
                open_geometry_warp,
                open_geometry_strength,
                open_geometry_max_ratio,
                open_generated_priority,
                expected_open_value,
                aperture_atlas_strength,
                closed_lock,
            )
            blended = temporal_refine(blended, previous_output, mask, inner_mask, abs(render_openness - previous_openness))
        else:
            blended = original
        previous_output = blended.copy()
        previous_openness = render_openness if mouth_points is not None else openness
        blended_frames.append(blended)

    write_video(blended_frames, output, fps)


def main() -> None:
    args = parse_args()
    detail_generated = Path(args.detail_generated) if args.detail_generated else None
    blend_generated_mouth(
        Path(args.source),
        Path(args.generated),
        detail_generated,
        Path(args.texture_source) if args.texture_source else None,
        Path(args.audio),
        Path(args.output),
        args.preserve_lips,
        args.dynamic_preserve,
        args.seamless_edge,
        args.detail_restore,
        args.align_detail,
        args.soft_cavity,
        args.upper_cavity_lift,
        args.aperture_mode,
        args.forced_openness,
        Path(args.aperture_atlas_source) if args.aperture_atlas_source else None,
        args.aperture_atlas_strength,
        args.aperture_energy_threshold,
        args.aperture_min_ratio,
        args.aperture_max_ratio,
        args.aperture_attack,
        args.aperture_release,
        args.open_closed_priority,
        args.open_shape_trigger,
        args.open_shape_openness,
        args.open_geometry_warp,
        args.open_geometry_strength,
        args.open_geometry_max_ratio,
        args.open_generated_priority,
        args.texture_samples,
        args.texture_top_k,
        Path(args.mouth_state_debug_output) if args.mouth_state_debug_output else None,
    )


if __name__ == "__main__":
    main()

