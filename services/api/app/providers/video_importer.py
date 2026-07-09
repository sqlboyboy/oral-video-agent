import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from ..models import Asset, storage_dir


URL_RE = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+", re.IGNORECASE)
DOUYIN_URL_RE = re.compile(
    r"(?:https?://)?(?:[A-Za-z0-9-]+\.)?douyin\.com/"
    r"[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+",
    re.IGNORECASE,
)
TRAILING_URL_CHARS = ".,;:!?，。；：！？、)]}）】》\"'"

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_BROWSER_ARGS = [
    "--disable-background-networking",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--no-first-run",
]


class VideoImportError(RuntimeError):
    pass


StageCallback = Callable[[str, str], None]


def _notify_stage(callback: Optional[StageCallback], key: str, status: str) -> None:
    if callback is None:
        return
    callback(key, status)


def _clean_url_candidate(url: str) -> str:
    return url.strip().rstrip(TRAILING_URL_CHARS)


def _normalize_share_url(url: str) -> str:
    url = _clean_url_candidate(url)
    if url and not re.match(r"^https?://", url, flags=re.IGNORECASE):
        return f"https://{url}"
    return url


def _is_douyin_url(url: str) -> bool:
    host = urllib.parse.urlparse(url).netloc.lower()
    return host == "douyin.com" or host.endswith(".douyin.com")


def extract_douyin_share_url(text: str) -> Optional[str]:
    for match in DOUYIN_URL_RE.finditer(text or ""):
        url = _normalize_share_url(match.group(0))
        if url and _is_douyin_url(url):
            return url
    for match in URL_RE.finditer(text or ""):
        url = _normalize_share_url(match.group(0))
        if url and _is_douyin_url(url):
            return url
    return None


def extract_first_url(text: str) -> Optional[str]:
    douyin_url = extract_douyin_share_url(text)
    if douyin_url:
        return douyin_url
    match = URL_RE.search(text or "")
    if not match:
        return None
    return _clean_url_candidate(match.group(0))


def _system_chromium_paths() -> list[Path]:
    local_app_data = os.getenv("LOCALAPPDATA", "")
    candidates = [
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
        Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
    ]
    if local_app_data:
        candidates.extend(
            [
                Path(local_app_data) / "Google/Chrome/Application/chrome.exe",
                Path(local_app_data) / "Microsoft/Edge/Application/msedge.exe",
            ]
        )

    seen: set[str] = set()
    existing: list[Path] = []
    for path in candidates:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        if path.exists():
            existing.append(path)
    return existing


def _launch_chromium(playwright):
    try:
        return playwright.chromium.launch(headless=True, args=_BROWSER_ARGS)
    except Exception as bundled_exc:
        if os.getenv("ORAL_VIDEO_AGENT_ALLOW_SYSTEM_BROWSER", "").strip().lower() not in {
            "1",
            "true",
            "yes",
            "on",
        }:
            raise VideoImportError(
                "Playwright Chromium 启动失败，无法打开分享链接。"
                "请使用包含浏览器内核的完整安装包重新安装。"
                f"详细原因：{bundled_exc}"
            ) from bundled_exc

        errors: list[str] = [f"bundled chromium: {bundled_exc}"]
        for executable in _system_chromium_paths():
            try:
                return playwright.chromium.launch(
                    executable_path=str(executable),
                    headless=True,
                    args=_BROWSER_ARGS,
                )
            except Exception as exc:
                errors.append(f"{executable}: {exc}")

        raise VideoImportError(
            "Playwright Chromium 启动失败，且未找到可用的系统 Chrome/Edge。"
            f"详细原因：{' | '.join(errors[-3:])}"
        ) from bundled_exc


def _extract_video_url_via_browser(share_url: str) -> Optional[str]:
    """
    Open share_url in a headless browser, intercept the aweme detail API
    response, and return the first playable video CDN URL.
    """
    from playwright.sync_api import sync_playwright  # lazy import

    detail_body: Optional[bytes] = None

    with sync_playwright() as p:
        browser = _launch_chromium(p)
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
    def import_from_share_text(
        self, share_text: str, on_stage: Optional[StageCallback] = None
    ) -> Asset:
        _notify_stage(on_stage, "resolve_link", "running")
        url = extract_first_url(share_text)
        if not url:
            _notify_stage(on_stage, "resolve_link", "failed")
            raise VideoImportError("没有识别到有效视频链接")

        try:
            video_url = _extract_video_url_via_browser(url)
        except Exception as exc:
            _notify_stage(on_stage, "resolve_link", "failed")
            raise VideoImportError(
                f"视频链接导入失败，请改用本地上传。原因：{exc}"
            ) from exc

        if not video_url:
            _notify_stage(on_stage, "resolve_link", "failed")
            raise VideoImportError(
                "未能从视频页面中提取到视频地址，可能是网络问题或抖音页面结构变化。请改用本地上传。"
            )
        _notify_stage(on_stage, "resolve_link", "completed")

        asset = Asset(kind="source_video", filename="douyin_source.mp4", path="")
        dest = storage_dir("uploads") / f"{asset.asset_id}.mp4"

        _notify_stage(on_stage, "download_video", "running")
        try:
            _download_video(video_url, dest)
        except Exception as exc:
            _notify_stage(on_stage, "download_video", "failed")
            raise VideoImportError(
                f"视频下载失败，请改用本地上传。原因：{exc}"
            ) from exc

        if not dest.exists() or dest.stat().st_size == 0:
            _notify_stage(on_stage, "download_video", "failed")
            raise VideoImportError("视频下载失败：文件为空，请改用本地上传")
        _notify_stage(on_stage, "download_video", "completed")

        asset.filename = dest.name
        asset.path = str(dest)
        return asset
