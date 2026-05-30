import json
from pathlib import Path
from typing import Dict, List, Optional

from .models import Asset, storage_dir


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


def save_upload(file, directory: str, kind: str) -> Asset:
    if not file.filename:
        raise ValueError("文件名不能为空")
    asset = Asset(kind=kind, filename=file.filename, path="")
    suffix = Path(file.filename).suffix
    target_path = storage_dir(directory) / f"{asset.asset_id}{suffix}"
    with target_path.open("wb") as out:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
    asset.path = str(target_path)
    return asset_store.put(asset)


asset_store = AssetStore()
