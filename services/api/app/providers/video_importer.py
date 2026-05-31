import re
from pathlib import Path
from typing import Optional

import yt_dlp

from ..models import Asset, storage_dir


URL_RE = re.compile(r"https?://[^\s，,]+")


class VideoImportError(RuntimeError):
    pass


def extract_first_url(text: str) -> Optional[str]:
    match = URL_RE.search(text.strip())
    if not match:
        return None
    return match.group(0).rstrip("。；;，,")


class VideoImporter:
    def __init__(self, cookies_file: Optional[str] = None):
        self._cookies_file = cookies_file

    def import_from_share_text(self, share_text: str) -> Asset:
        url = extract_first_url(share_text)
        if not url:
            raise VideoImportError("没有识别到有效视频链接")

        asset = Asset(kind="source_video", filename="douyin_source.mp4", path="")
        output_template = str(storage_dir("uploads") / f"{asset.asset_id}.%(ext)s")

        ydl_opts = {
            "outtmpl": output_template,
            "format": "mp4/best[ext=mp4]/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
        }

        if self._cookies_file and Path(self._cookies_file).exists():
            ydl_opts["cookiefile"] = self._cookies_file

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                downloaded = Path(ydl.prepare_filename(info))
        except Exception as exc:
            msg = str(exc)
            if "cookies" in msg.lower() or "Fresh cookies" in msg:
                raise VideoImportError(
                    "抖音下载需要登录 Cookie。请在 Edge/Chrome 中访问 douyin.com，"
                    "用「Get cookies.txt LOCALLY」扩展导出 cookies，"
                    "保存到 storage/douyin_cookies.txt，"
                    "并在 .env 中设置 DOUYIN_COOKIES_FILE=storage/douyin_cookies.txt。"
                    "或直接使用本地上传。"
                ) from exc
            raise VideoImportError(f"视频链接导入失败，请改用本地上传。原因：{exc}") from exc

        if not downloaded.exists():
            raise VideoImportError("视频链接导入失败：下载文件不存在，请改用本地上传")

        asset.filename = downloaded.name
        asset.path = str(downloaded)
        return asset
