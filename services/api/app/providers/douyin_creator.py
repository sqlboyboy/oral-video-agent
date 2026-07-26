from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlparse

from .video_importer import (
    _BROWSER_UA,
    _launch_chromium,
    extract_douyin_share_url,
)


class DouyinCreatorInputError(ValueError):
    """The pasted text does not contain a usable Douyin profile link."""


class DouyinCreatorFetchError(RuntimeError):
    """A public Douyin profile could not be collected."""


@dataclass(frozen=True)
class DouyinCreatorWork:
    description: str
    aweme_id: str | None = None


@dataclass(frozen=True)
class DouyinCreatorSnapshot:
    profile_url: str
    sec_uid: str | None
    nickname: str
    unique_id: str | None = None
    signature: str = ""
    follower_count: int | None = None
    recent_works: list[DouyinCreatorWork] = field(default_factory=list)


def _nested_mapping(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = payload.get(key)
    if isinstance(value, dict):
        return value
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get(key), dict):
        return data[key]
    return None


def _parse_profile_payload(payload: dict[str, Any]) -> dict[str, Any]:
    user = _nested_mapping(payload, "user") or _nested_mapping(payload, "user_info")
    if not user:
        return {}
    follower_count = user.get("follower_count")
    if follower_count is None:
        follower_count = user.get("mplatform_followers_count")
    result = {
        "nickname": str(user.get("nickname") or "").strip(),
        "unique_id": str(user.get("unique_id") or user.get("short_id") or "").strip() or None,
        "signature": str(user.get("signature") or "").strip(),
        "sec_uid": str(user.get("sec_uid") or "").strip() or None,
        "follower_count": _safe_int(follower_count),
    }
    if not any(result.get(key) for key in ("nickname", "signature", "sec_uid")):
        return {}
    return result


def _safe_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _aweme_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("aweme_list")
    if not isinstance(value, list):
        data = payload.get("data")
        value = data.get("aweme_list") if isinstance(data, dict) else None
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _parse_post_payloads(
    payloads: list[dict[str, Any]], max_works: int = 12
) -> list[DouyinCreatorWork]:
    works: list[DouyinCreatorWork] = []
    seen_descriptions: set[str] = set()
    for payload in payloads:
        for aweme in _aweme_list(payload):
            description = str(aweme.get("desc") or "").strip()
            if not description:
                share_info = aweme.get("share_info")
                if isinstance(share_info, dict):
                    description = str(share_info.get("share_title") or "").strip()
            description = re.sub(r"\s+", " ", description)
            description = re.sub(r"(?:\s*#[^\s#]+)+\s*$", "", description).strip()
            normalized = description.casefold()
            if not description or normalized in seen_descriptions:
                continue
            seen_descriptions.add(normalized)
            aweme_id = str(aweme.get("aweme_id") or "").strip() or None
            works.append(DouyinCreatorWork(description=description, aweme_id=aweme_id))
            if len(works) >= max_works:
                return works
    return works


def _sec_uid_from_url(url: str) -> str | None:
    path = unquote(urlparse(url).path)
    match = re.search(r"/user/([^/?#]+)", path)
    return match.group(1).strip() if match else None


def _decode_json_payload(raw: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


class DouyinCreatorCollector:
    def __init__(self, *, max_works: int = 12, timeout_ms: int = 30000) -> None:
        self.max_works = max(1, min(max_works, 30))
        self.timeout_ms = max(10000, timeout_ms)

    def collect(self, share_text: str) -> DouyinCreatorSnapshot:
        profile_url = extract_douyin_share_url(share_text)
        if not profile_url:
            raise DouyinCreatorInputError("请粘贴包含抖音主页链接的完整分享文案")

        try:
            profile_payloads, post_payloads, final_url = self._browse(profile_url)
        except DouyinCreatorFetchError:
            raise
        except Exception as exc:
            raise DouyinCreatorFetchError(f"抖音主页访问失败：{exc}") from exc

        profile: dict[str, Any] = {}
        for payload in profile_payloads:
            parsed = _parse_profile_payload(payload)
            if parsed:
                profile = parsed
                break
        if not profile:
            raise DouyinCreatorFetchError(
                "未能读取抖音主页公开资料，可能是网络异常、访问受限或页面结构已变化"
            )

        works = _parse_post_payloads(post_payloads, self.max_works)
        signature = str(profile.get("signature") or "").strip()
        if not signature and not works:
            raise DouyinCreatorFetchError("该主页没有可用于分析的公开简介或作品描述")

        return DouyinCreatorSnapshot(
            profile_url=final_url or profile_url,
            sec_uid=profile.get("sec_uid") or _sec_uid_from_url(final_url),
            nickname=profile.get("nickname") or "抖音创作者",
            unique_id=profile.get("unique_id"),
            signature=signature,
            follower_count=profile.get("follower_count"),
            recent_works=works,
        )

    def _browse(
        self, profile_url: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        from playwright.sync_api import sync_playwright  # lazy import

        profile_bodies: list[bytes] = []
        post_bodies: list[bytes] = []
        final_url = profile_url

        try:
            with sync_playwright() as playwright:
                browser = _launch_chromium(playwright)
                try:
                    context = browser.new_context(
                        user_agent=_BROWSER_UA,
                        locale="zh-CN",
                        viewport={"width": 1440, "height": 900},
                    )
                    page = context.new_page()

                    def on_response(response) -> None:
                        target = response.url
                        bucket: list[bytes] | None = None
                        if "/aweme/v1/web/user/profile/other/" in target:
                            bucket = profile_bodies
                        elif "/aweme/v1/web/aweme/post/" in target:
                            bucket = post_bodies
                        if bucket is None:
                            return
                        try:
                            bucket.append(response.body())
                        except Exception:
                            return

                    page.on("response", on_response)
                    try:
                        page.goto(
                            profile_url,
                            wait_until="domcontentloaded",
                            timeout=self.timeout_ms,
                        )
                    except Exception:
                        # Douyin may keep long-running requests open. Captured API
                        # responses are sufficient even when navigation times out.
                        pass
                    page.wait_for_timeout(7000)
                    final_url = page.url or profile_url
                finally:
                    browser.close()
        except Exception as exc:
            raise DouyinCreatorFetchError(f"抖音主页抓取失败：{exc}") from exc

        profile_payloads = [
            payload
            for raw in profile_bodies
            if (payload := _decode_json_payload(raw)) is not None
        ]
        post_payloads = [
            payload
            for raw in post_bodies
            if (payload := _decode_json_payload(raw)) is not None
        ]
        return profile_payloads, post_payloads, final_url
