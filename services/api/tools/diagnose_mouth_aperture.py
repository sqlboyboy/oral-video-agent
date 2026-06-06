from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import av
import cv2
import numpy as np

from wav2lip_onnx import detect_mouth_points, estimate_face_box
from blend_wav2lip_result import mouth_open_ratio


@dataclass
class MouthFrame:
    index: int
    ratio: float
    frame: np.ndarray


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find source-video closed/open mouth target frames.")
    parser.add_argument("--video", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--samples", type=int, default=180)
    return parser.parse_args()


def scan(video: Path, samples: int) -> list[MouthFrame]:
    container = av.open(str(video))
    stream = next(item for item in container.streams if item.type == "video")
    total_frames = int(stream.frames or 0)
    stride = max(1, total_frames // max(samples, 1)) if total_frames else 1
    previous_box: tuple[int, int, int, int] | None = None
    frames: list[MouthFrame] = []

    for index, frame in enumerate(container.decode(stream)):
        if index % stride != 0:
            continue
        image = frame.to_ndarray(format="rgb24")
        face_box = estimate_face_box(image, previous_box)
        previous_box = face_box
        mouth = detect_mouth_points(image, face_box)
        if mouth is None:
            continue
        frames.append(MouthFrame(index=index, ratio=mouth_open_ratio(mouth), frame=image))

    container.close()
    return frames


def crop_face(frame: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    crop = frame[int(height * 0.20) : int(height * 0.60), int(width * 0.20) : int(width * 0.80)]
    return cv2.resize(crop, (300, 420), interpolation=cv2.INTER_AREA)


def save_contact_sheet(frames: list[MouthFrame], output: Path) -> None:
    if not frames:
        raise RuntimeError("No mouth landmarks detected.")
    sorted_frames = sorted(frames, key=lambda item: item.ratio)
    picks = [
        ("closed 1", sorted_frames[0]),
        ("closed 2", sorted_frames[min(1, len(sorted_frames) - 1)]),
        ("middle", sorted_frames[len(sorted_frames) // 2]),
        ("open 2", sorted_frames[max(0, len(sorted_frames) - 2)]),
        ("open 1", sorted_frames[-1]),
    ]
    font = cv2.FONT_HERSHEY_SIMPLEX
    cells = []
    for label, item in picks:
        crop = crop_face(item.frame)
        banner = np.zeros((48, crop.shape[1], 3), dtype=np.uint8)
        banner[:] = (24, 26, 38)
        text = f"{label} f{item.index} r{item.ratio:.3f}"
        cv2.putText(banner, text, (10, 31), font, 0.66, (230, 240, 255), 2, cv2.LINE_AA)
        cells.append(np.concatenate([banner, crop], axis=0))
    sheet = np.concatenate(cells, axis=1)
    output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output), cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR))


def main() -> None:
    args = parse_args()
    frames = scan(Path(args.video), args.samples)
    save_contact_sheet(frames, Path(args.output))
    ratios = [item.ratio for item in frames]
    print(
        f"detected={len(frames)} min={min(ratios):.4f} median={np.median(ratios):.4f} max={max(ratios):.4f}",
        flush=True,
    )


if __name__ == "__main__":
    main()
