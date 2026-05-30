from io import BytesIO

import pytest

from app import asset_store
from app.asset_store import save_upload


class FakeUpload:
    def __init__(self, filename: str, content: bytes) -> None:
        self.filename = filename
        self.file = BytesIO(content)


def test_save_upload_rejects_files_over_kind_limit(monkeypatch):
    monkeypatch.setitem(asset_store.MAX_UPLOAD_BYTES, "bgm", 4)

    with pytest.raises(ValueError, match="文件过大"):
        save_upload(FakeUpload("large.mp3", b"12345"), "bgm", "bgm")
