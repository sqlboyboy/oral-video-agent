from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import quote
from uuid import uuid4

from .settings import settings


@dataclass(frozen=True)
class PresignedUrl:
    method: str
    url: str
    headers: dict[str, str]
    expires_at: int
    cos_key: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "url": self.url,
            "headers": self.headers,
            "expires_at": self.expires_at,
            "cos_key": self.cos_key,
        }


class ObjectStorage:
    def __init__(self) -> None:
        self.backend = settings.object_storage_backend
        self.bucket = settings.cos_bucket
        self.region = settings.cos_region
        self.scheme = settings.cos_scheme
        self.local_root = settings.object_storage_root
        self.public_base_url = (
            settings.object_storage_public_base_url.rstrip("/")
            or settings.cloud_public_base_url.rstrip("/")
            or settings.cos_public_base_url.rstrip("/")
            or f"{self.scheme}://{self.bucket}.cos.{self.region}.myqcloud.com"
        )

    @property
    def using_local_storage(self) -> bool:
        return self.backend in {"local", "server", "filesystem", "fs"}

    @property
    def configured_for_tencent_cos(self) -> bool:
        return bool(
            self.backend in {"cos", "tencent_cos", "tencent-cos"}
            and
            settings.cos_secret_id
            and settings.cos_secret_key
            and settings.cos_bucket
            and settings.cos_region
        )

    def input_key(self, *, user_id: str, job_id: str, asset_id: str, file_name: str) -> str:
        safe_name = quote(file_name.strip() or "asset", safe="._-")
        return f"inputs/{user_id}/{job_id}/{asset_id}/{safe_name}"

    def output_key(self, *, user_id: str, job_id: str, file_name: str = "result.mp4") -> str:
        safe_name = quote(file_name.strip() or "result.mp4", safe="._-")
        return f"outputs/{user_id}/{job_id}/{safe_name}"

    def presign_upload(
        self,
        *,
        cos_key: str,
        content_type: str = "application/octet-stream",
        expires_seconds: int | None = None,
    ) -> PresignedUrl:
        return self._presign(
            method="PUT",
            cos_key=cos_key,
            content_type=content_type,
            expires_seconds=expires_seconds or settings.cos_upload_url_expires_seconds,
        )

    def presign_download(
        self,
        *,
        cos_key: str,
        expires_seconds: int | None = None,
    ) -> PresignedUrl:
        return self._presign(
            method="GET",
            cos_key=cos_key,
            content_type="",
            expires_seconds=expires_seconds or settings.cos_download_url_expires_seconds,
        )

    def delete_object(self, *, cos_key: str) -> dict[str, Any]:
        if self.using_local_storage:
            path = self.local_path_for_key(cos_key)
            deleted = False
            if path.exists():
                path.unlink()
                deleted = True
                self._remove_empty_parents(path.parent)
            return {"deleted": deleted, "cos_key": cos_key}
        if self.configured_for_tencent_cos:
            from qcloud_cos import CosConfig, CosS3Client  # type: ignore

            config = CosConfig(
                Region=self.region,
                SecretId=settings.cos_secret_id,
                SecretKey=settings.cos_secret_key,
                Scheme=self.scheme,
            )
            client = CosS3Client(config)
            client.delete_object(Bucket=self.bucket, Key=cos_key)
        return {"deleted": True, "cos_key": cos_key}

    def _presign(
        self,
        *,
        method: str,
        cos_key: str,
        content_type: str,
        expires_seconds: int,
    ) -> PresignedUrl:
        expires_at = int(time.time()) + expires_seconds
        headers = {"Content-Type": content_type} if method == "PUT" and content_type else {}
        if self.configured_for_tencent_cos:
            return self._presign_tencent_cos(
                method=method,
                cos_key=cos_key,
                content_type=content_type,
                expires_seconds=expires_seconds,
                expires_at=expires_at,
                headers=headers,
            )
        url = self._local_signed_url(method=method, cos_key=cos_key, expires_at=expires_at)
        return PresignedUrl(
            method=method,
            url=url,
            headers=headers,
            expires_at=expires_at,
            cos_key=cos_key,
        )

    def verify_signed_request(
        self,
        *,
        method: str,
        cos_key: str,
        expires_at: int,
        signature: str,
    ) -> None:
        if expires_at < int(time.time()):
            raise PermissionError("signed url expired")
        expected = self._signature(method=method.upper(), cos_key=cos_key, expires_at=expires_at)
        if not hmac.compare_digest(expected, signature):
            raise PermissionError("invalid signed url signature")

    async def save_upload_stream(
        self,
        *,
        cos_key: str,
        stream: AsyncIterator[bytes],
    ) -> dict[str, Any]:
        path = self.local_path_for_key(cos_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = self.local_root / "_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / f"{uuid4().hex}.tmp"
        size = 0
        try:
            with tmp_path.open("wb") as output:
                async for chunk in stream:
                    if not chunk:
                        continue
                    output.write(chunk)
                    size += len(chunk)
            os.replace(tmp_path, path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
        return {"uploaded": True, "cos_key": cos_key, "bytes": size}

    def local_path_for_key(self, cos_key: str) -> Path:
        key = cos_key.replace("\\", "/").lstrip("/")
        parts = []
        for part in key.split("/"):
            if part in {"", "."}:
                continue
            if part == "..":
                raise ValueError("invalid object key")
            parts.append(part)
        if not parts:
            raise ValueError("invalid object key")
        root = self.local_root.resolve()
        path = root.joinpath(*parts).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("invalid object key") from exc
        return path

    def _remove_empty_parents(self, directory: Path) -> None:
        root = self.local_root.resolve()
        current = directory.resolve()
        while current != root:
            try:
                current.rmdir()
            except OSError:
                return
            current = current.parent

    def _presign_tencent_cos(
        self,
        *,
        method: str,
        cos_key: str,
        content_type: str,
        expires_seconds: int,
        expires_at: int,
        headers: dict[str, str],
    ) -> PresignedUrl:
        from qcloud_cos import CosConfig, CosS3Client  # type: ignore

        config = CosConfig(
            Region=self.region,
            SecretId=settings.cos_secret_id,
            SecretKey=settings.cos_secret_key,
            Scheme=self.scheme,
        )
        client = CosS3Client(config)
        sdk_headers = {"Content-Type": content_type} if method == "PUT" and content_type else None
        url = client.get_presigned_url(
            Method=method,
            Bucket=self.bucket,
            Key=cos_key,
            Expired=expires_seconds,
            Headers=sdk_headers,
        )
        return PresignedUrl(
            method=method,
            url=url,
            headers=headers,
            expires_at=expires_at,
            cos_key=cos_key,
        )

    def _local_signed_url(self, *, method: str, cos_key: str, expires_at: int) -> str:
        signature = self._signature(method=method, cos_key=cos_key, expires_at=expires_at)
        return (
            f"{self.public_base_url}/api/storage/objects/{quote(cos_key, safe='/')}"
            f"?expires={expires_at}&signature={signature}"
        )

    def _signature(self, *, method: str, cos_key: str, expires_at: int) -> str:
        payload = f"{method}\n{cos_key}\n{expires_at}".encode("utf-8")
        return hmac.new(
            settings.cos_mock_secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()


object_storage = ObjectStorage()
