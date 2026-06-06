from __future__ import annotations

import argparse
import math
from pathlib import Path

import av
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lightweight CPU mouth open/close renderer.")
    parser.add_argument("--reference", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def audio_samples(audio_path: Path) -> tuple[np.ndarray, int]:
    container = av.open(str(audio_path))
    try:
        stream = next(s for s in container.streams if s.type == "audio")
    except StopIteration as exc:
        raise RuntimeError(f"No audio stream found: {audio_path}") from exc

    chunks: list[np.ndarray] = []
    sample_rate = int(stream.rate or 22050)
    for frame in container.decode(stream):
        sample_rate = int(frame.sample_rate or sample_rate)
        data = frame.to_ndarray()
        if data.ndim > 1:
            data = data.mean(axis=0)
        data = data.astype(np.float32, copy=False)
        max_abs = np.max(np.abs(data)) if data.size else 0
        if max_abs > 1.5:
            data = data / 32768.0
        chunks.append(data)
    container.close()
    if not chunks:
        return np.zeros(1, dtype=np.float32), sample_rate
    return np.concatenate(chunks).astype(np.float32, copy=False), sample_rate


def frame_levels(samples: np.ndarray, sample_rate: int, fps: float, frame_count: int) -> np.ndarray:
    if frame_count <= 0:
        return np.zeros(0, dtype=np.float32)
    levels = np.zeros(frame_count, dtype=np.float32)
    for index in range(frame_count):
        start = int(index / fps * sample_rate)
        end = int((index + 1) / fps * sample_rate)
        segment = samples[start:end]
        if segment.size:
            levels[index] = float(np.sqrt(np.mean(segment * segment)))

    noise_floor = float(np.percentile(levels, 20)) if levels.size else 0.0
    peak = float(np.percentile(levels, 95)) if levels.size else 0.0
    denom = max(peak - noise_floor, 1e-4)
    levels = np.clip((levels - noise_floor) / denom, 0.0, 1.0)

    smoothed = np.zeros_like(levels)
    current = 0.0
    for index, level in enumerate(levels):
        target = float(level)
        current = current * 0.55 + target * 0.45
        smoothed[index] = current
    return smoothed


def estimate_mouth(frame: np.ndarray, fallback: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    height, width = frame.shape[:2]
    x0, x1 = int(width * 0.18), int(width * 0.82)
    y0, y1 = int(height * 0.05), int(height * 0.72)
    crop = frame[y0:y1, x0:x1].astype(np.float32)
    if crop.size == 0:
        return fallback

    r = crop[:, :, 0]
    g = crop[:, :, 1]
    b = crop[:, :, 2]
    brightness = (r + g + b) / 3.0
    skin = (
        (brightness > 65)
        & (brightness < 235)
        & (r > g * 0.95)
        & (g > b * 0.82)
        & ((r - b) > 10)
    )
    ys, xs = np.nonzero(skin)
    if xs.size < 300:
        return fallback

    min_x = float(np.percentile(xs, 8) + x0)
    max_x = float(np.percentile(xs, 92) + x0)
    min_y = float(np.percentile(ys, 8) + y0)
    max_y = float(np.percentile(ys, 92) + y0)
    face_w = max(max_x - min_x, width * 0.12)
    face_h = max(max_y - min_y, height * 0.14)
    center_x = (min_x + max_x) / 2.0
    center_y = min_y + face_h * 0.70
    radius_x = max(face_w * 0.16, width * 0.025)
    radius_y = max(face_h * 0.045, height * 0.006)
    return center_x, center_y, radius_x, radius_y


def draw_mouth(frame: np.ndarray, mouth: tuple[float, float, float, float], level: float) -> np.ndarray:
    height, width = frame.shape[:2]
    center_x, center_y, radius_x, base_radius_y = mouth
    open_amount = 1.0 / (1.0 + math.exp(-9.0 * (float(level) - 0.34)))
    radius_y = base_radius_y * (0.35 + open_amount * 2.15)

    x_min = max(0, int(center_x - radius_x - 3))
    x_max = min(width, int(center_x + radius_x + 4))
    y_min = max(0, int(center_y - radius_y - 4))
    y_max = min(height, int(center_y + radius_y + 5))
    if x_max <= x_min or y_max <= y_min:
        return frame

    yy, xx = np.ogrid[y_min:y_max, x_min:x_max]
    ellipse = ((xx - center_x) / max(radius_x, 1.0)) ** 2 + ((yy - center_y) / max(radius_y, 1.0)) ** 2
    mask = np.clip(1.0 - ellipse, 0.0, 1.0)
    mask = np.power(mask, 0.45)
    alpha = (mask * (0.42 + open_amount * 0.36))[:, :, None]
    mouth_color = np.array([28, 10, 12], dtype=np.float32)

    region = frame[y_min:y_max, x_min:x_max].astype(np.float32)
    region = region * (1.0 - alpha) + mouth_color * alpha
    frame[y_min:y_max, x_min:x_max] = np.clip(region, 0, 255).astype(np.uint8)
    return frame


def render(reference: Path, audio: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    samples, sample_rate = audio_samples(audio)

    input_container = av.open(str(reference))
    video_stream = next(s for s in input_container.streams if s.type == "video")
    fps_rate = video_stream.average_rate or video_stream.base_rate
    fps = float(fps_rate) if fps_rate else 25.0
    total_frames = int(video_stream.frames or 0)
    if total_frames <= 0:
        duration = float(video_stream.duration * video_stream.time_base) if video_stream.duration else 0.0
        total_frames = max(1, int(round(duration * fps)))

    levels = frame_levels(samples, sample_rate, fps, total_frames)

    output_container = av.open(str(output), mode="w")
    output_stream = output_container.add_stream("libx264", rate=fps_rate or 25)
    output_stream.width = int(video_stream.width)
    output_stream.height = int(video_stream.height)
    output_stream.pix_fmt = "yuv420p"
    output_stream.options = {"preset": "ultrafast", "crf": "22"}

    fallback = (
        output_stream.width * 0.50,
        output_stream.height * 0.47,
        output_stream.width * 0.045,
        output_stream.height * 0.010,
    )
    mouth = fallback
    frame_index = 0
    for video_frame in input_container.decode(video_stream):
        image = video_frame.to_ndarray(format="rgb24")
        detected = estimate_mouth(image, mouth)
        mouth = tuple(mouth[i] * 0.78 + detected[i] * 0.22 for i in range(4))
        level = levels[min(frame_index, len(levels) - 1)] if len(levels) else 0.0
        image = draw_mouth(image, mouth, float(level))
        encoded_frame = av.VideoFrame.from_ndarray(image, format="rgb24")
        encoded_frame.pts = None
        for packet in output_stream.encode(encoded_frame):
            output_container.mux(packet)
        frame_index += 1

    for packet in output_stream.encode():
        output_container.mux(packet)
    output_container.close()
    input_container.close()


def main() -> None:
    args = parse_args()
    render(Path(args.reference), Path(args.audio), Path(args.output))


if __name__ == "__main__":
    main()
