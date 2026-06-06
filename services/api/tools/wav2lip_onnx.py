from __future__ import annotations

import argparse
import math
from pathlib import Path

import av
import numpy as np
import onnxruntime as ort
import torch

try:
    import cv2
except ImportError:  # pragma: no cover - optional runtime dependency
    cv2 = None
if cv2 is not None and not hasattr(cv2, "resize"):
    cv2 = None


def has_cv2_attr(name: str) -> bool:
    return cv2 is not None and hasattr(cv2, name)


SAMPLE_RATE = 16000
N_FFT = 800
HOP_LENGTH = 200
WIN_LENGTH = 800
N_MELS = 80
MEL_FRAMES = 16
IMG_SIZE = 96


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Optional Wav2Lip ONNX runner.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--aperture-mode",
        choices=["auto", "open", "closed"],
        default="auto",
        help="Debug mouth aperture before matching detailed mouth shapes to audio.",
    )
    parser.add_argument("--forced-openness", type=float, default=None)
    return parser.parse_args()


def read_audio(audio_path: Path) -> tuple[np.ndarray, int]:
    container = av.open(str(audio_path))
    stream = next((item for item in container.streams if item.type == "audio"), None)
    if stream is None:
        raise RuntimeError(f"No audio stream found: {audio_path}")

    sample_rate = int(stream.rate or SAMPLE_RATE)
    chunks: list[np.ndarray] = []
    for frame in container.decode(stream):
        sample_rate = int(frame.sample_rate or sample_rate)
        data = frame.to_ndarray()
        if data.ndim > 1:
            data = data.mean(axis=0)
        data = data.astype(np.float32, copy=False)
        if data.size and np.max(np.abs(data)) > 1.5:
            data = data / 32768.0
        chunks.append(data)
    container.close()
    if not chunks:
        return np.zeros(1, dtype=np.float32), sample_rate
    return np.concatenate(chunks).astype(np.float32, copy=False), sample_rate


def resample_linear(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate:
        return samples.astype(np.float32, copy=False)
    if samples.size <= 1:
        return np.zeros(1, dtype=np.float32)
    duration = samples.size / float(source_rate)
    target_count = max(1, int(round(duration * target_rate)))
    source_x = np.linspace(0.0, duration, num=samples.size, endpoint=False)
    target_x = np.linspace(0.0, duration, num=target_count, endpoint=False)
    return np.interp(target_x, source_x, samples).astype(np.float32)


def hz_to_mel(freq: np.ndarray | float) -> np.ndarray | float:
    return 2595.0 * np.log10(1.0 + np.asarray(freq) / 700.0)


def mel_to_hz(mel: np.ndarray | float) -> np.ndarray | float:
    return 700.0 * (10.0 ** (np.asarray(mel) / 2595.0) - 1.0)


def mel_filterbank() -> torch.Tensor:
    fmin = 55.0
    fmax = 7600.0
    mel_points = np.linspace(hz_to_mel(fmin), hz_to_mel(fmax), N_MELS + 2)
    hz_points = mel_to_hz(mel_points)
    bins = np.floor((N_FFT + 1) * hz_points / SAMPLE_RATE).astype(int)
    bank = np.zeros((N_MELS, N_FFT // 2 + 1), dtype=np.float32)
    for i in range(1, N_MELS + 1):
        left, center, right = bins[i - 1], bins[i], bins[i + 1]
        if center > left:
            bank[i - 1, left:center] = (np.arange(left, center) - left) / float(center - left)
        if right > center:
            bank[i - 1, center:right] = (right - np.arange(center, right)) / float(right - center)
    return torch.from_numpy(bank)


def wav_to_mel(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    samples = resample_linear(samples, sample_rate, SAMPLE_RATE)
    samples = np.append(samples[0], samples[1:] - 0.97 * samples[:-1]).astype(np.float32)
    wav = torch.from_numpy(samples)
    window = torch.hann_window(WIN_LENGTH)
    spec = torch.stft(
        wav,
        n_fft=N_FFT,
        hop_length=HOP_LENGTH,
        win_length=WIN_LENGTH,
        window=window,
        center=True,
        return_complex=True,
    )
    power = torch.abs(spec)
    mel = torch.matmul(mel_filterbank(), power)
    mel = torch.clamp(mel, min=1e-5)
    # FaceFusion's Wav2Lip ONNX export expects log-mel values in roughly
    # [-4, 4], not the 0..1 normalization used by some demos.
    mel_norm = torch.log10(mel) * 1.6 + 3.2
    mel_norm = torch.clamp(mel_norm, -4.0, 4.0)
    return mel_norm.numpy().astype(np.float32)


def resize_nearest(image: np.ndarray, width: int, height: int) -> np.ndarray:
    if has_cv2_attr("resize"):
        return cv2.resize(image, (width, height), interpolation=cv2.INTER_LINEAR)
    src_h, src_w = image.shape[:2]
    ys = np.clip((np.arange(height) * src_h / height).astype(np.int32), 0, src_h - 1)
    xs = np.clip((np.arange(width) * src_w / width).astype(np.int32), 0, src_w - 1)
    return image[ys[:, None], xs[None, :]]


_FACE_CASCADE = None
_FACEMARK = None


def default_landmark_model() -> Path:
    return Path(__file__).resolve().parents[3] / "storage" / "models" / "face_landmarks" / "lbfmodel.yaml"


def load_facemark():
    global _FACEMARK
    if cv2 is None or not hasattr(cv2, "face"):
        return None
    if _FACEMARK is not None:
        return _FACEMARK
    model = default_landmark_model()
    if not model.exists():
        return None
    facemark = cv2.face.createFacemarkLBF()
    facemark.loadModel(str(model))
    _FACEMARK = facemark
    return _FACEMARK


def haar_face_box(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    global _FACE_CASCADE
    if cv2 is None or not has_cv2_attr("CascadeClassifier") or not has_cv2_attr("cvtColor"):
        return None
    if _FACE_CASCADE is None:
        haar_dir = getattr(getattr(cv2, "data", None), "haarcascades", None)
        if not haar_dir:
            return None
        cascade_path = Path(haar_dir) / "haarcascade_frontalface_default.xml"
        _FACE_CASCADE = cv2.CascadeClassifier(str(cascade_path))
    if _FACE_CASCADE.empty():
        return None

    height, width = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    faces = _FACE_CASCADE.detectMultiScale(
        gray,
        scaleFactor=1.08,
        minNeighbors=4,
        minSize=(max(64, width // 8), max(64, height // 10)),
    )
    if len(faces) == 0:
        return None
    faces = sorted(faces, key=lambda item: item[2] * item[3], reverse=True)
    x, y, w, h = faces[0]
    pad_x = int(w * 0.10)
    pad_top = int(h * 0.08)
    pad_bottom = int(h * 0.12)
    return (
        max(0, int(x - pad_x)),
        max(0, int(y - pad_top)),
        min(width, int(x + w + pad_x)),
        min(height, int(y + h + pad_bottom)),
    )


def estimate_face_box(frame: np.ndarray, previous: tuple[int, int, int, int] | None) -> tuple[int, int, int, int]:
    detected = haar_face_box(frame)
    if detected is not None:
        if previous is None:
            return detected
        return tuple(int(previous[i] * 0.70 + detected[i] * 0.30) for i in range(4))

    height, width = frame.shape[:2]
    crop = frame[: int(height * 0.75)].astype(np.float32)
    r = crop[:, :, 0]
    g = crop[:, :, 1]
    b = crop[:, :, 2]
    brightness = (r + g + b) / 3.0
    skin = (
        (brightness > 55)
        & (brightness < 245)
        & (r > g * 0.93)
        & (g > b * 0.78)
        & ((r - b) > 8)
    )
    ys, xs = np.nonzero(skin)
    if xs.size < 500:
        if previous is not None:
            return previous
        box_w = int(width * 0.45)
        box_h = int(box_w * 1.15)
        cx = width // 2
        cy = int(height * 0.32)
        return (
            max(0, cx - box_w // 2),
            max(0, cy - box_h // 2),
            min(width, cx + box_w // 2),
            min(height, cy + box_h // 2),
        )

    x1 = int(np.percentile(xs, 4))
    x2 = int(np.percentile(xs, 96))
    y1 = int(np.percentile(ys, 3))
    y2 = int(np.percentile(ys, 97))
    face_w = max(x2 - x1, int(width * 0.18))
    face_h = max(y2 - y1, int(height * 0.18))
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    size = int(max(face_w * 1.15, face_h * 0.95))
    top = int(cy - size * 0.43)
    bottom = top + size
    left = int(cx - size * 0.50)
    right = left + size
    box = (max(0, left), max(0, top), min(width, right), min(height, bottom))
    if previous is None:
        return box
    return tuple(int(previous[i] * 0.75 + box[i] * 0.25) for i in range(4))


def detect_mouth_points(frame: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray | None:
    facemark = load_facemark()
    if facemark is None or not has_cv2_attr("cvtColor"):
        return None
    x1, y1, x2, y2 = box
    width = x2 - x1
    height = y2 - y1
    if width <= 20 or height <= 20:
        return None

    # FacemarkLBF expects a face rectangle, not the extra-padded Wav2Lip crop.
    rect = np.array(
        [[
            max(0, int(x1 + width * 0.07)),
            max(0, int(y1 + height * 0.04)),
            max(20, int(width * 0.86)),
            max(20, int(height * 0.82)),
        ]],
        dtype=np.int32,
    )
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    try:
        ok, landmarks = facemark.fit(gray, rect)
    except cv2.error:
        return None
    if not ok or landmarks is None or len(landmarks) == 0:
        return None
    points = np.asarray(landmarks[0], dtype=np.float32).reshape(-1, 2)
    if points.shape[0] < 68:
        return None
    mouth = points[48:68]
    mx1, my1 = mouth.min(axis=0)
    mx2, my2 = mouth.max(axis=0)
    if mx2 <= x1 or mx1 >= x2 or my2 <= y1 or my1 >= y2:
        return None
    return mouth


def detect_generated_mouth_points(
    frame: np.ndarray,
    generated: np.ndarray,
    box: tuple[int, int, int, int],
) -> np.ndarray | None:
    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1:
        return None
    canvas = frame.copy()
    canvas[y1:y2, x1:x2] = resize_nearest(generated, x2 - x1, y2 - y1)
    return detect_mouth_points(canvas, box)


def build_mel_chunk(
    mel: np.ndarray,
    frame_index: int,
    fps: float,
    aperture_mode: str = "auto",
    forced_openness: float | None = None,
) -> np.ndarray:
    mel_index_multiplier = 80.0 / fps
    start = int(frame_index * mel_index_multiplier)
    if start + MEL_FRAMES > mel.shape[1]:
        start = max(0, mel.shape[1] - MEL_FRAMES)
    chunk = mel[:, start : start + MEL_FRAMES]
    if chunk.shape[1] < MEL_FRAMES:
        pad = np.repeat(chunk[:, -1:], MEL_FRAMES - chunk.shape[1], axis=1)
        chunk = np.concatenate([chunk, pad], axis=1)
    if aperture_mode == "open":
        open_drive = float(np.clip(0.78 if forced_openness is None else forced_openness, 0.0, 1.0))
        chunk = np.clip(chunk * (1.08 + open_drive * 0.22) + (0.14 + open_drive * 0.34), -4.0, 4.0)
    elif aperture_mode == "closed":
        chunk = np.clip(chunk * 0.12 - 0.55, -4.0, 4.0)
    return chunk[np.newaxis, np.newaxis, :, :].astype(np.float32)


def session_inputs(session: ort.InferenceSession) -> tuple[str, str]:
    inputs = session.get_inputs()
    if len(inputs) < 2:
        raise RuntimeError("Wav2Lip ONNX model must expose face and mel inputs.")
    face_input = None
    mel_input = None
    for item in inputs:
        shape = [dim if isinstance(dim, int) else None for dim in item.shape]
        name = item.name.lower()
        if "mel" in name or (len(shape) == 4 and shape[-2:] == [80, 16]):
            mel_input = item.name
        elif "face" in name or "img" in name or (len(shape) == 4 and (shape[1] == 6 or shape[-1] == 6)):
            face_input = item.name
    if face_input is None:
        face_input = inputs[0].name
    if mel_input is None:
        mel_input = inputs[1].name if inputs[1].name != face_input else inputs[0].name
    return face_input, mel_input


def infer_face(session: ort.InferenceSession, face_input: str, mel_input: str, face: np.ndarray, mel: np.ndarray) -> np.ndarray:
    # Wav2Lip ONNX exports are commonly converted from OpenCV/BGR code paths.
    # A/B tests also tried RGB input/output, but that made the mouth cleaner at
    # the cost of weaker articulation on this source clip.
    face_bgr = face[:, :, ::-1]
    face_96 = resize_nearest(face_bgr, IMG_SIZE, IMG_SIZE)
    masked = face_96.copy()
    masked[IMG_SIZE // 2 :, :, :] = 0
    model_face = np.concatenate([masked, face_96], axis=2).astype(np.float32) / 255.0
    model_face = np.transpose(model_face, (2, 0, 1))[np.newaxis, :, :, :]
    result = session.run(None, {face_input: model_face, mel_input: mel})[0]
    result = np.asarray(result)
    if result.ndim == 4 and result.shape[1] == 3:
        result = np.transpose(result[0], (1, 2, 0))
    elif result.ndim == 4:
        result = result[0]
    result = np.clip(result * 255.0, 0, 255).astype(np.uint8)
    return result[:, :, ::-1]


def frame_audio_levels(samples: np.ndarray, sample_rate: int, fps: float, frame_count: int) -> np.ndarray:
    levels = np.zeros(max(frame_count, 0), dtype=np.float32)
    if samples.size == 0 or frame_count <= 0:
        return levels
    for index in range(frame_count):
        start = int(index / fps * sample_rate)
        end = int((index + 1) / fps * sample_rate)
        segment = samples[start:end]
        if segment.size:
            levels[index] = float(np.sqrt(np.mean(segment * segment)))
    floor = float(np.percentile(levels, 25)) if levels.size else 0.0
    peak = float(np.percentile(levels, 95)) if levels.size else 0.0
    levels = np.clip((levels - floor) / max(peak - floor, 1e-5), 0.0, 1.0)
    smoothed = np.zeros_like(levels)
    current = 0.0
    for index, level in enumerate(levels):
        current = current * 0.62 + float(level) * 0.38
        smoothed[index] = current
    return smoothed


def soft_mouth_mask(height: int, width: int, openness: float) -> np.ndarray:
    yy, xx = np.mgrid[0:height, 0:width]
    openness = float(np.clip(openness, 0.0, 1.0))
    # Keep the generated pixels tightly around the lips. A broad lower-face
    # blend makes low-res Wav2Lip outputs look like a pasted dark patch.
    oval = (
        ((xx - width * 0.50) / max(width * (0.155 + openness * 0.030), 1.0)) ** 2
        + ((yy - height * 0.645) / max(height * (0.062 + openness * 0.050), 1.0)) ** 2
    )
    mask = np.clip(1.0 - oval, 0.0, 1.0)
    mask[yy < height * 0.555] = 0.0
    mask[yy > height * 0.755] = 0.0
    mask = np.power(mask, 0.55)
    if cv2 is not None:
        kernel = max(3, int(round(min(width, height) * 0.045)))
        if kernel % 2 == 0:
            kernel += 1
        mask = cv2.GaussianBlur(mask.astype(np.float32), (kernel, kernel), 0)
    alpha = 0.10 + openness * 0.62
    return np.clip(mask * alpha, 0.0, alpha)[:, :, None]


def landmark_mouth_mask(
    height: int,
    width: int,
    box: tuple[int, int, int, int],
    mouth_points: np.ndarray,
    openness: float,
) -> np.ndarray:
    openness = float(np.clip(openness, 0.0, 1.0))
    x1, y1, _, _ = box
    local = mouth_points.copy()
    local[:, 0] -= float(x1)
    local[:, 1] -= float(y1)
    if not np.all(np.isfinite(local)):
        return soft_mouth_mask(height, width, openness)

    center = local.mean(axis=0)
    expanded = local.copy()
    expanded[:, 0] = center[0] + (expanded[:, 0] - center[0]) * (1.28 + openness * 0.08)
    expanded[:, 1] = center[1] + (expanded[:, 1] - center[1]) * (1.42 + openness * 0.22)
    expanded[:, 0] = np.clip(expanded[:, 0], 0, width - 1)
    expanded[:, 1] = np.clip(expanded[:, 1], 0, height - 1)

    mask = np.zeros((height, width), dtype=np.float32)
    outer = cv2.convexHull(expanded[:12].astype(np.int32))
    cv2.fillConvexPoly(mask, outer, 0.34 + openness * 0.08)

    # Add a tiny inner emphasis so the generated lip-sync is visible, but keep
    # it inside the detected lip contour rather than spreading into the philtrum.
    inner = expanded[12:20]
    if inner.shape[0] >= 6:
        inner_mask = np.zeros_like(mask)
        cv2.fillConvexPoly(inner_mask, cv2.convexHull(inner.astype(np.int32)), 1.0)
        mask = np.maximum(mask, inner_mask * (1.0 + openness * 0.18))

    kernel = max(3, int(round(min(width, height) * 0.035)))
    if kernel % 2 == 0:
        kernel += 1
    mask = cv2.GaussianBlur(mask, (kernel, kernel), 0)
    alpha = 0.10 + openness * 0.76
    return np.clip(mask * alpha, 0.0, alpha)[:, :, None]


def match_region_color(generated: np.ndarray, region: np.ndarray, mask: np.ndarray) -> np.ndarray:
    mask_2d = mask[:, :, 0] > 0.08
    if not np.any(mask_2d):
        return generated.astype(np.float32)
    generated_f = generated.astype(np.float32)
    region_f = region.astype(np.float32)
    src_mean = generated_f[mask_2d].mean(axis=0)
    dst_mean = region_f[mask_2d].mean(axis=0)
    # Only correct global cast, not the actual dark inner-mouth pixels.
    correction = np.clip(dst_mean - src_mean, -22.0, 22.0)
    return np.clip(generated_f + correction * 0.45, 0, 255)


def suppress_dark_patch(generated: np.ndarray, region: np.ndarray, mask: np.ndarray, openness: float) -> np.ndarray:
    generated_f = generated.astype(np.float32)
    region_f = region.astype(np.float32)
    generated_luma = generated_f.mean(axis=2, keepdims=True)
    region_luma = region_f.mean(axis=2, keepdims=True)
    openness = float(np.clip(openness, 0.0, 1.0))
    too_dark = (generated_luma < region_luma - (36.0 + openness * 30.0)) & (mask > 0.10)
    if not np.any(too_dark):
        return generated_f
    # Keep some inner-mouth darkness, but prevent it from becoming a hard
    # horizontal black sticker across the lips.
    repaired = generated_f * (0.38 + openness * 0.18) + region_f * (0.62 - openness * 0.18)
    repaired_luma = repaired.mean(axis=2, keepdims=True)
    target_floor = np.maximum(region_luma - (58.0 + openness * 18.0), 44.0 + openness * 10.0)
    lift = np.clip(target_floor - repaired_luma, 0.0, 55.0)
    repaired = np.clip(repaired + lift * np.array([0.95, 0.76, 0.78], dtype=np.float32), 0, 255)
    return np.where(too_dark, repaired, generated_f)


def enhance_mouth_aperture(blended: np.ndarray, openness: float, mouth_points: np.ndarray | None = None) -> np.ndarray:
    openness = float(np.clip((openness - 0.12) / 0.58, 0.0, 1.0))
    if openness <= 0.02:
        return blended
    if mouth_points is not None and mouth_points.shape[0] >= 20 and cv2 is not None:
        return enhance_landmark_mouth_detail(blended, openness, mouth_points)
    height, width = blended.shape[:2]
    cx = width * 0.50
    cy = height * 0.655
    rx = max(width * (0.052 + openness * 0.045), 1.0)
    ry = max(height * (0.010 + openness * 0.060), 1.0)
    y_min = max(0, int(cy - ry * 2.2))
    y_max = min(height, int(cy + ry * 2.4))
    x_min = max(0, int(cx - rx * 2.2))
    x_max = min(width, int(cx + rx * 2.2))
    if x_max <= x_min or y_max <= y_min:
        return blended

    yy, xx = np.mgrid[y_min:y_max, x_min:x_max]
    ellipse = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
    inner = np.clip(1.0 - ellipse, 0.0, 1.0)
    inner = np.power(inner, 0.42)
    if cv2 is not None:
        inner = cv2.GaussianBlur(inner.astype(np.float32), (5, 5), 0)

    region = blended[y_min:y_max, x_min:x_max].astype(np.float32)
    skin_mean = region.reshape(-1, 3).mean(axis=0)
    mouth_color = np.array([
        max(76.0, skin_mean[0] * 0.48),
        max(48.0, skin_mean[1] * 0.36),
        max(52.0, skin_mean[2] * 0.38),
    ], dtype=np.float32)
    alpha = (inner * (0.36 + openness * 0.34))[:, :, None]
    region = region * (1.0 - alpha) + mouth_color * alpha

    if openness > 0.58:
        tooth = np.exp(
            -(
                ((yy - (cy - ry * 0.55)) / max(ry * 0.30, 1.0)) ** 2
                + ((xx - cx) / max(rx * 0.86, 1.0)) ** 2
            )
        )
        tooth = np.clip(tooth * (openness - 0.58) * 0.28, 0.0, 0.10)[:, :, None]
        tooth_color = np.array([210.0, 198.0, 184.0], dtype=np.float32)
        region = region * (1.0 - tooth) + tooth_color * tooth

    # Add very soft lip shading above and below the aperture so the opening
    # reads as a mouth, not as a detached dark line.
    lip = np.exp(-(((yy - (cy - ry * 1.08)) / max(ry * 0.55, 1.0)) ** 2 + ((xx - cx) / max(rx * 1.35, 1.0)) ** 2))
    lip += np.exp(-(((yy - (cy + ry * 1.12)) / max(ry * 0.62, 1.0)) ** 2 + ((xx - cx) / max(rx * 1.45, 1.0)) ** 2))
    lip = np.clip(lip * openness * 0.12, 0.0, 0.12)[:, :, None]
    lip_color = np.array([skin_mean[0] * 0.82, skin_mean[1] * 0.58, skin_mean[2] * 0.58], dtype=np.float32)
    region = region * (1.0 - lip) + lip_color * lip

    blended[y_min:y_max, x_min:x_max] = np.clip(region, 0, 255)

    return blended


def enhance_landmark_mouth_detail(blended: np.ndarray, openness: float, mouth_points: np.ndarray) -> np.ndarray:
    inner = mouth_points[12:20].astype(np.float32)
    if inner.shape[0] < 6:
        return blended

    height, width = blended.shape[:2]
    outer = mouth_points[:12].astype(np.float32)
    center = inner.mean(axis=0)
    expanded = inner.copy()
    expanded[:, 0] = center[0] + (expanded[:, 0] - center[0]) * (1.12 + openness * 0.18)
    expanded[:, 1] = center[1] + (expanded[:, 1] - center[1]) * (1.42 + openness * 0.60)
    outer_width = float(max(outer[:, 0].max() - outer[:, 0].min(), expanded[:, 0].max() - expanded[:, 0].min(), 1.0))
    target_inner_height = outer_width * (0.055 + openness * 0.255)
    current_inner_height = float(max(expanded[:, 1].max() - expanded[:, 1].min(), 1.0))
    if target_inner_height > current_inner_height:
        expanded[:, 1] = center[1] + (expanded[:, 1] - center[1]) * (target_inner_height / current_inner_height)
    expanded[:, 0] = np.clip(expanded[:, 0], 0, width - 1)
    expanded[:, 1] = np.clip(expanded[:, 1], 0, height - 1)

    mask = np.zeros((height, width), dtype=np.float32)
    cv2.fillConvexPoly(mask, cv2.convexHull(expanded.astype(np.int32)), 1.0)
    kernel = max(3, int(round(min(width, height) * 0.018)))
    if kernel % 2 == 0:
        kernel += 1
    mask = cv2.GaussianBlur(mask, (kernel, kernel), 0)
    if mask.max() <= 1e-6:
        return blended

    lower_shift = outer_width * max(openness - 0.28, 0.0) * 0.135
    y_min = max(0, int(expanded[:, 1].min()) - kernel)
    y_max = min(height, int(expanded[:, 1].max() + lower_shift) + kernel + 1)
    x_min = max(0, int(expanded[:, 0].min()) - kernel)
    x_max = min(width, int(expanded[:, 0].max()) + kernel + 1)
    if x_max <= x_min or y_max <= y_min:
        return blended

    local_mask = mask[y_min:y_max, x_min:x_max][:, :, None]
    region = blended[y_min:y_max, x_min:x_max].astype(np.float32)
    if lower_shift > 1.0:
        yy_w, xx_w = np.mgrid[y_min:y_max, x_min:x_max].astype(np.float32)
        span_x_w = max(float(expanded[:, 0].max() - expanded[:, 0].min()), outer_width * 0.55)
        span_y_w = max(float(expanded[:, 1].max() - expanded[:, 1].min()), outer_width * 0.12)
        lower_weight = np.clip((yy_w - center[1]) / max(span_y_w * 0.55, 1.0), 0.0, 1.0)
        mouth_falloff = np.exp(-(((xx_w - center[0]) / max(span_x_w * 0.72, 1.0)) ** 2))
        warp_weight = lower_weight * mouth_falloff * local_mask[:, :, 0]
        map_x = (xx_w - x_min).astype(np.float32)
        map_y = (yy_w - y_min - lower_shift * warp_weight).astype(np.float32)
        warped = cv2.remap(
            region,
            map_x,
            map_y,
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
        warp_alpha = (warp_weight * min(0.72, 0.34 + openness * 0.34))[:, :, None]
        region = region * (1.0 - warp_alpha) + warped * warp_alpha
    skin = blended[
        max(0, int(center[1] - 28)) : min(height, int(center[1] + 32)),
        max(0, int(center[0] - 38)) : min(width, int(center[0] + 38)),
    ].astype(np.float32)
    skin_mean = skin.reshape(-1, 3).mean(axis=0) if skin.size else region.reshape(-1, 3).mean(axis=0)

    shadow = np.array(
        [
            max(96.0, skin_mean[0] * 0.62),
            max(62.0, skin_mean[1] * 0.48),
            max(60.0, skin_mean[2] * 0.48),
        ],
        dtype=np.float32,
    )
    luma = region.mean(axis=2, keepdims=True)
    floor = max(82.0, float(skin_mean.mean()) - 48.0 + openness * 16.0)
    dark_alpha = np.clip((floor - luma) / 58.0, 0.0, 1.0) * local_mask * (0.10 + openness * 0.18)
    region = region * (1.0 - dark_alpha) + shadow * dark_alpha

    if openness > 0.30:
        yy2, xx2 = np.mgrid[y_min:y_max, x_min:x_max]
        span_x = float(max(expanded[:, 0].max() - expanded[:, 0].min(), outer_width * 0.48))
        span_y = float(max(expanded[:, 1].max() - expanded[:, 1].min(), outer_width * (0.070 + openness * 0.180)))
        cavity_y = float(expanded[:, 1].min() + span_y * 0.54)
        cavity_x = float(center[0])
        cavity_rx = max(span_x * (0.34 + openness * 0.12), 1.0)
        cavity_ry = max(span_y * (0.34 + openness * 0.18), 1.0)
        cavity = np.exp(-(((xx2 - cavity_x) / cavity_rx) ** 2 + ((yy2 - cavity_y) / cavity_ry) ** 2))
        cavity = (cavity * local_mask[:, :, 0] * (openness - 0.30) * 0.58)[:, :, None]
        region = region * (1.0 - cavity) + shadow * cavity

        tooth_y = float(expanded[:, 1].min() + span_y * 0.28)
        tooth_x = float(center[0])
        rx = max(span_x * 0.38, 1.0)
        ry = max(span_y * 0.16, 1.0)
        tooth = np.exp(-(((xx2 - tooth_x) / rx) ** 2 + ((yy2 - tooth_y) / ry) ** 2))
        tooth = (tooth * local_mask[:, :, 0] * (openness - 0.30) * 0.46)[:, :, None]
        tooth_color = np.array([224.0, 214.0, 202.0], dtype=np.float32)
        region = region * (1.0 - tooth) + tooth_color * tooth

    blended[y_min:y_max, x_min:x_max] = np.clip(region, 0, 255)
    return blended


def restore_mouth_texture(
    blended: np.ndarray,
    original: np.ndarray,
    mouth_points: np.ndarray | None,
    openness: float,
) -> np.ndarray:
    if mouth_points is None or mouth_points.shape[0] < 20 or cv2 is None:
        return blended

    height, width = blended.shape[:2]
    local = mouth_points.astype(np.float32)
    center = local.mean(axis=0)
    expanded = local.copy()
    expanded[:, 0] = center[0] + (expanded[:, 0] - center[0]) * (1.22 + openness * 0.06)
    expanded[:, 1] = center[1] + (expanded[:, 1] - center[1]) * (1.30 + openness * 0.12)
    expanded[:, 0] = np.clip(expanded[:, 0], 0, width - 1)
    expanded[:, 1] = np.clip(expanded[:, 1], 0, height - 1)

    outer_mask = np.zeros((height, width), dtype=np.float32)
    inner_mask = np.zeros((height, width), dtype=np.float32)
    cv2.fillConvexPoly(outer_mask, cv2.convexHull(expanded[:12].astype(np.int32)), 1.0)
    cv2.fillConvexPoly(inner_mask, cv2.convexHull(expanded[12:20].astype(np.int32)), 1.0)

    kernel = max(3, int(round(min(width, height) * 0.018)))
    if kernel % 2 == 0:
        kernel += 1
    outer_mask = cv2.GaussianBlur(outer_mask, (kernel, kernel), 0)
    inner_mask = cv2.GaussianBlur(inner_mask, (kernel, kernel), 0)
    lip_mask = np.clip(outer_mask - inner_mask * 0.70, 0.0, 1.0)[:, :, None]
    inner = np.clip(inner_mask, 0.0, 1.0)[:, :, None]

    if lip_mask.max() <= 1e-6 and inner.max() <= 1e-6:
        return blended

    original_f = original.astype(np.float32)
    blended_f = blended.astype(np.float32)
    blur_kernel = max(3, int(round(min(width, height) * 0.026)))
    if blur_kernel % 2 == 0:
        blur_kernel += 1
    original_blur = cv2.GaussianBlur(original_f, (blur_kernel, blur_kernel), 0)
    blended_blur = cv2.GaussianBlur(blended_f, (blur_kernel, blur_kernel), 0)

    original_detail = np.clip(original_f - original_blur, -18.0, 18.0)
    blended_detail = np.clip(blended_f - blended_blur, -14.0, 14.0)
    lip_strength = 0.26 + (1.0 - float(np.clip(openness, 0.0, 1.0))) * 0.08
    inner_strength = 0.08 + float(np.clip(openness, 0.0, 1.0)) * 0.08
    restored = blended_f + original_detail * lip_mask * lip_strength + blended_detail * inner * inner_strength

    return np.clip(restored, 0, 255)


def blend_lower_face(
    frame: np.ndarray,
    generated: np.ndarray,
    box: tuple[int, int, int, int],
    openness: float,
    mouth_points: np.ndarray | None = None,
) -> np.ndarray:
    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1:
        return frame
    generated = resize_nearest(generated, x2 - x1, y2 - y1)
    region = frame[y1:y2, x1:x2].astype(np.float32)
    height, width = region.shape[:2]
    local_mouth = None
    if mouth_points is not None and cv2 is not None:
        mask = landmark_mouth_mask(height, width, box, mouth_points, openness)
        local_mouth = mouth_points.copy()
        local_mouth[:, 0] -= float(x1)
        local_mouth[:, 1] -= float(y1)
    else:
        mask = soft_mouth_mask(height, width, openness)
    generated_f = match_region_color(generated, region, mask)
    generated_f = suppress_dark_patch(generated_f, region, mask, openness)
    blended = region * (1.0 - mask) + generated_f * mask
    blended = enhance_mouth_aperture(blended, openness, local_mouth)
    frame[y1:y2, x1:x2] = np.clip(blended, 0, 255).astype(np.uint8)
    return frame


def temporal_smooth_mouth(
    frame: np.ndarray,
    previous_frame: np.ndarray | None,
    box: tuple[int, int, int, int],
    mouth_points: np.ndarray | None,
    openness_delta: float,
) -> np.ndarray:
    if previous_frame is None or previous_frame.shape != frame.shape or cv2 is None:
        return frame
    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1:
        return frame

    height = y2 - y1
    width = x2 - x1
    if mouth_points is not None:
        mask = landmark_mouth_mask(height, width, box, mouth_points, 0.55)[:, :, 0]
    else:
        mask = soft_mouth_mask(height, width, 0.55)[:, :, 0]
    if mask.max() <= 1e-6:
        return frame

    mask = mask / float(mask.max())
    kernel = max(3, int(round(min(width, height) * 0.025)))
    if kernel % 2 == 0:
        kernel += 1
    mask = cv2.GaussianBlur(mask.astype(np.float32), (kernel, kernel), 0)

    motion = float(np.clip(openness_delta / 0.28, 0.0, 1.0))
    strength = 0.18 * (1.0 - motion) + 0.055 * motion
    alpha = (mask * strength)[:, :, None]

    current = frame[y1:y2, x1:x2].astype(np.float32)
    previous = previous_frame[y1:y2, x1:x2].astype(np.float32)
    mixed = current * (1.0 - alpha) + previous * alpha
    frame[y1:y2, x1:x2] = np.clip(mixed, 0, 255).astype(np.uint8)
    return frame


def lower_face_box(box: tuple[int, int, int, int], frame_shape: tuple[int, ...]) -> tuple[int, int, int, int]:
    frame_h, frame_w = frame_shape[:2]
    x1, y1, x2, y2 = box
    width = x2 - x1
    height = y2 - y1
    cx = (x1 + x2) / 2.0
    new_w = width * 0.74
    return (
        max(0, int(cx - new_w / 2.0)),
        max(0, int(y1 + height * 0.36)),
        min(frame_w, int(cx + new_w / 2.0)),
        min(frame_h, int(y1 + height * 0.93)),
    )


def render(
    model: Path,
    reference: Path,
    audio: Path,
    output: Path,
    aperture_mode: str = "auto",
    forced_openness: float | None = None,
) -> None:
    if not model.exists():
        raise RuntimeError(f"Wav2Lip ONNX model not found: {model}")
    output.parent.mkdir(parents=True, exist_ok=True)

    session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    face_input, mel_input = session_inputs(session)
    samples, audio_rate = read_audio(audio)
    mel = wav_to_mel(samples, audio_rate)
    level_samples = resample_linear(samples, audio_rate, SAMPLE_RATE)

    input_container = av.open(str(reference))
    video_stream = next(item for item in input_container.streams if item.type == "video")
    fps_rate = video_stream.average_rate or video_stream.base_rate
    fps = float(fps_rate) if fps_rate else 25.0
    total_frames = int(video_stream.frames or 0)
    if total_frames <= 0:
        duration = float(video_stream.duration * video_stream.time_base) if video_stream.duration else 0.0
        total_frames = max(1, int(round(duration * fps)))
    audio_levels = frame_audio_levels(level_samples, SAMPLE_RATE, fps, total_frames)

    output_container = av.open(str(output), mode="w")
    output_stream = output_container.add_stream("libx264", rate=fps_rate or 25)
    output_stream.width = int(video_stream.width)
    output_stream.height = int(video_stream.height)
    output_stream.pix_fmt = "yuv420p"
    output_stream.options = {"preset": "veryfast", "crf": "20"}

    previous_box: tuple[int, int, int, int] | None = None
    previous_mouth: np.ndarray | None = None
    previous_output: np.ndarray | None = None
    previous_openness = 0.0
    for frame_index, video_frame in enumerate(input_container.decode(video_stream)):
        image = video_frame.to_ndarray(format="rgb24")
        face_box = estimate_face_box(image, previous_box)
        previous_box = face_box
        x1, y1, x2, y2 = face_box
        face = image[y1:y2, x1:x2]
        if face.size:
            generated = infer_face(
                session,
                face_input,
                mel_input,
                face,
                build_mel_chunk(mel, frame_index, fps, aperture_mode, forced_openness),
            )
            openness = float(audio_levels[min(frame_index, len(audio_levels) - 1)]) if len(audio_levels) else 0.0
            if aperture_mode == "open":
                openness = float(np.clip(0.78 if forced_openness is None else forced_openness, 0.0, 1.0))
            elif aperture_mode == "closed":
                openness = float(np.clip(0.02 if forced_openness is None else forced_openness, 0.0, 1.0))
            generated_mouth_points = None
            generated_driven_open = aperture_mode == "open" or openness >= 0.42
            if generated_driven_open:
                generated_mouth_points = detect_generated_mouth_points(image, generated, face_box)
            mouth_points = generated_mouth_points if generated_mouth_points is not None else detect_mouth_points(image, face_box)
            if mouth_points is not None and previous_mouth is not None and previous_mouth.shape == mouth_points.shape:
                if generated_driven_open and generated_mouth_points is not None:
                    mouth_points = previous_mouth * 0.42 + mouth_points * 0.58
                else:
                    mouth_points = previous_mouth * 0.72 + mouth_points * 0.28
            if mouth_points is not None:
                previous_mouth = mouth_points
            image = blend_lower_face(image, generated, face_box, openness, mouth_points)
            image = temporal_smooth_mouth(
                image,
                previous_output,
                face_box,
                mouth_points,
                abs(openness - previous_openness),
            )
            previous_openness = openness
        previous_output = image.copy()
        encoded_frame = av.VideoFrame.from_ndarray(image, format="rgb24")
        encoded_frame.pts = None
        for packet in output_stream.encode(encoded_frame):
            output_container.mux(packet)

    for packet in output_stream.encode():
        output_container.mux(packet)
    output_container.close()
    input_container.close()


def main() -> None:
    args = parse_args()
    render(
        Path(args.model),
        Path(args.reference),
        Path(args.audio),
        Path(args.output),
        args.aperture_mode,
        args.forced_openness,
    )


if __name__ == "__main__":
    main()
