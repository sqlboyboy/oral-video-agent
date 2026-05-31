import json
import re
import urllib.request
from pathlib import Path
from typing import Optional

from ..models import Asset, storage_dir


URL_RE = re.compile(r"https?://[^\s，,]+")

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class VideoImportError(RuntimeError):
    pass


def extract_first_url(text: str) -> Optional[str]:
    match = URL_RE.search(text.strip())
    if not match:
        return None
    return match.group(0).rstrip("。；;，,")


def _extract_video_url_via_browser(share_url: str) -> Optional[str]:
    """
    Open share_url in a headless browser, intercept the aweme detail API
    response, and return the first playable video CDN URL.
    """
    from playwright.sync_api import sync_playwright  # lazy import

    detail_body: Optional[bytes] = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=_BROWSER_UA)
        page = context.new_page()

        def on_response(resp):
            nonlocal detail_body
            if "aweme/v1/web/aweme/detail" in resp.url and detail_body is None:
                try:
                    detail_body = resp.body()
                except Exception:
                    pass

        page.on("response", on_response)
        try:
            page.goto(share_url, wait_until="networkidle", timeout=30000)
        except Exception:
            pass  # timeout is fine — we just need the API response
        page.wait_for_timeout(5000)
        browser.close()

    if not detail_body:
        return None

    try:
        data = json.loads(detail_body)
    except Exception:
        return None

    aweme = data.get("aweme_detail", {})
    video = aweme.get("video", {})

    # Prefer play_addr (no watermark), fall back to download_addr
    for key in ("play_addr", "download_addr"):
        urls = video.get(key, {}).get("url_list", [])
        # Prefer douyinvod CDN URLs (more stable than douyin.com/aweme/v1/play)
        cdn_urls = [u for u in urls if "douyinvod.com" in u or "amemv.com" in u]
        if cdn_urls:
            return cdn_urls[0]
        if urls:
            return urls[0]

    return None


def _download_video(video_url: str, dest: Path) -> None:
    req = urllib.request.Request(
        video_url,
        headers={
            "User-Agent": _BROWSER_UA,
            "Referer": "https://www.douyin.com/",
        },
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
        while chunk := resp.read(1024 * 256):
            f.write(chunk)


class VideoImporter:
    def import_from_share_text(self, share_text: str) -> Asset:
        url = extract_first_url(share_text)
        if not url:
            raise VideoImportError("没有识别到有效视频链接")

        try:
            video_url = _extract_video_url_via_browser(url)
        except Exception as exc:
            raise VideoImportError(
                f"视频链接导入失败，请改用本地上传。原因：{exc}"
            ) from exc

        if not video_url:
            raise VideoImportError(
                "未能从视频页面中提取到视频地址，可能是网络问题或抖音页面结构变化。请改用本地上传。"
            )

        asset = Asset(kind="source_video", filename="douyin_source.mp4", path="")
        dest = storage_dir("uploads") / f"{asset.asset_id}.mp4"

        try:
            _download_video(video_url, dest)
        except Exception as exc:
            raise VideoImportError(
                f"视频下载失败，请改用本地上传。原因：{exc}"
            ) from exc

        if not dest.exists() or dest.stat().st_size == 0:
            raise VideoImportError("视频下载失败：文件为空，请改用本地上传")

        asset.filename = dest.name
        asset.path = str(dest)
        return asset
