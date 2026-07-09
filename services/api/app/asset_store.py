import json
import wave
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from .models import Asset, storage_dir


ALLOWED_SUFFIXES = {
    "source_video": {".mp4", ".mov", ".mkv", ".webm"},
    "voice_reference": {".wav", ".mp3", ".m4a", ".aac", ".flac", ".mp4", ".mov", ".mkv", ".webm"},
    "digital_human_reference": {".mp4", ".mov", ".mkv", ".webm"},
    "bgm": {".wav", ".mp3", ".m4a", ".aac", ".flac"},
    "pip": {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".mkv", ".webm"},
    "cover": {".png", ".jpg", ".jpeg", ".webp"},
}
MAX_UPLOAD_BYTES = {
    "source_video": 500 * 1024 * 1024,
    "voice_reference": 500 * 1024 * 1024,
    "digital_human_reference": 500 * 1024 * 1024,
    "bgm": 100 * 1024 * 1024,
    "pip": 500 * 1024 * 1024,
    "cover": 20 * 1024 * 1024,
}


class AssetStore:
    def __init__(self) -> None:
        self._db_path = storage_dir("assets") / "assets.json"
        self._items: Dict[str, Asset] = {}
        self._load()

    def _load(self) -> None:
        if not self._db_path.exists():
            return
        data = json.loads(self._db_path.read_text(encoding="utf-8"))
        self._items = {item["asset_id"]: Asset.model_validate(item) for item in data}

    def _save(self) -> None:
        data = [item.model_dump(mode="json") for item in self._items.values()]
        self._db_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def list(self, kind: Optional[str] = None) -> List[Asset]:
        items = list(self._items.values())
        if kind is None:
            return items
        return [item for item in items if item.kind == kind]

    def put(self, asset: Asset) -> Asset:
        self._items[asset.asset_id] = asset
        self._save()
        return asset

    def get(self, asset_id: str) -> Asset:
        if asset_id not in self._items:
            raise KeyError(asset_id)
        return self._items[asset_id]

    def delete(self, asset_id: str) -> Asset:
        if asset_id not in self._items:
            raise KeyError(asset_id)
        asset = self._items.pop(asset_id)
        self._save()
        return asset


def save_upload(file, directory: str, kind: str) -> Asset:
    if not file.filename:
        raise ValueError("文件名不能为空")
    asset = Asset(kind=kind, filename=file.filename, path="")
    suffix = Path(file.filename).suffix.lower()
    allowed_suffixes = ALLOWED_SUFFIXES.get(kind)
    if allowed_suffixes is not None and suffix not in allowed_suffixes:
        allowed = ", ".join(sorted(allowed_suffixes))
        raise ValueError(f"不支持的文件类型，允许：{allowed}")
    target_path = storage_dir(directory) / f"{asset.asset_id}{suffix}"
    max_bytes = MAX_UPLOAD_BYTES.get(kind)
    total_bytes = 0
    size_error = None
    with target_path.open("wb") as out:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            total_bytes += len(chunk)
            if max_bytes is not None and total_bytes > max_bytes:
                size_error = ValueError(f"文件过大，最大允许 {max_bytes // 1024 // 1024}MB")
                break
            out.write(chunk)
    if size_error is not None:
        target_path.unlink(missing_ok=True)
        raise size_error
    asset.path = str(target_path)
    return asset_store.put(asset)


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    samples = np.clip(samples, -1.0, 1.0)
    pcm = (samples * 32767.0).astype(np.int16)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())


def ensure_voice_reference_wav(asset: Asset) -> Asset:
    if asset.kind != "voice_reference":
        return asset
    source = Path(asset.path)
    if source.suffix.lower() == ".wav":
        return asset
    if not source.exists():
        return asset

    import av

    target = source.with_suffix(".wav")
    container = av.open(str(source))
    audio_stream = next((stream for stream in container.streams if stream.type == "audio"), None)
    if audio_stream is None:
        container.close()
        raise ValueError("参考音色文件没有可读取的音频轨道")

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
        raise ValueError("参考音色解码后没有音频数据")

    _write_wav(target, np.concatenate(chunks), 16000)
    source.unlink(missing_ok=True)
    asset.path = str(target)
    return asset_store.put(asset)


asset_store = AssetStore()
