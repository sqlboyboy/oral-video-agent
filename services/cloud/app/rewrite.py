from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


MAX_REWRITE_CHARS = 300


@dataclass(frozen=True)
class RewriteInput:
    source_script: str
    style: str = "同款口播"
    product_info: str = ""
    target_audience: str = ""
    max_chars: int = MAX_REWRITE_CHARS


def rewrite_script(req: RewriteInput, settings: Any) -> str:
    original_script = to_simplified_chinese(req.source_script).strip()
    if not original_script:
        raise ValueError("source_script is required")

    provider = str(getattr(settings, "rewrite_provider", "deepseek") or "deepseek").lower()
    if provider in {"placeholder", "mock"}:
        return light_paraphrase(original_script)

    api_key = str(getattr(settings, "deepseek_api_key", "") or "").strip()
    if not api_key:
        raise RuntimeError("server missing DEEPSEEK_API_KEY")

    base_url = str(getattr(settings, "deepseek_base_url", "https://api.deepseek.com")).rstrip("/")
    model = str(getattr(settings, "deepseek_model", "deepseek-chat") or "deepseek-chat")
    timeout = int(getattr(settings, "deepseek_timeout_seconds", 30) or 30)
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你是专业的中文短视频口播文案策划，只输出可直接口播的原创简体中文文案。",
            },
            {"role": "user", "content": build_rewrite_prompt(original_script, req)},
        ],
        "temperature": 0.7,
        "max_tokens": 900,
        "stream": False,
    }

    last_response: Any = None
    for _ in range(2):
        response = post_json(
            f"{base_url}/chat/completions",
            payload,
            timeout_seconds=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        last_response = response
        rewritten = extract_rewrite_content(response)
        if rewritten and is_usable_rewrite(original_script, rewritten):
            return format_spoken_lines(rewritten)
        payload["messages"].append(
            {
                "role": "user",
                "content": (
                    "上一次没有输出合格正文。请直接改写下面【原文】里的内容，"
                    "必须保留原文主题和核心词，禁止跑题，禁止要求我再提供文本，禁止解释，只输出口播文案。\n"
                    f"【原文】{original_script}【原文结束】"
                ),
            }
        )
    fallback = light_paraphrase(original_script)
    if fallback:
        return fallback
    raise RuntimeError(f"DeepSeek returned empty content: {short_json(last_response)}")


def build_rewrite_prompt(original_script: str, req: RewriteInput) -> str:
    max_chars = bounded_rewrite_chars(req.max_chars)
    product = req.product_info.strip() or "不额外添加产品信息"
    audience = req.target_audience.strip() or "不额外指定人群"
    style = req.style.strip() or "同款口播"
    return (
        "请直接改写下面【原文】里的口播文本。即使原文很短，也必须完成改写，禁止要求用户再提供文本。\n"
        "请做同主题原创仿写，不要只是加标点或营销扩写。\n"
        "保留原文主题、表达顺序、情绪、语气和大致字数，但要重组句子并替换表达。\n"
        "不要新增原文没有的信息，不要输出标题、标签、解释或占位符。\n"
        f"最终文案不超过 {max_chars} 字，只使用中文简体，不要输出繁体字。\n"
        "不要包含任何中英文标点符号，可用换行表示自然停顿。\n\n"
        f"仿写风格：{style}\n"
        f"产品/服务：{product}\n"
        f"目标人群：{audience}\n\n"
        f"【原文】\n{original_script}\n【原文结束】"
    )


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: int,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **(headers or {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek HTTP {exc.code}: {detail[-500:]}") from exc
    return json.loads(body) if body else {}


def extract_rewrite_content(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict):
        content = normalize_content(message.get("content"))
        if content:
            return content
        content = normalize_content(message.get("reasoning_content"))
        if content:
            return content
    return normalize_content(first.get("text"))


def normalize_content(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts).strip()
    return ""


def is_usable_rewrite(original_script: str, rewritten: str) -> bool:
    if is_unusable_rewrite(rewritten):
        return False
    return topic_overlap(original_script, rewritten) >= 0.06


def is_unusable_rewrite(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return True
    markers = [
        "请提供",
        "未提供",
        "没有提供",
        "需要提供",
        "需要您提供",
        "无法改写",
        "不能改写",
        "抱歉",
        "原文文本",
    ]
    return any(marker in compact for marker in markers)


def topic_overlap(original_script: str, rewritten: str) -> float:
    original_tokens = text_ngrams(original_script)
    if not original_tokens:
        return 1.0
    rewritten_tokens = text_ngrams(rewritten)
    if not rewritten_tokens:
        return 0.0
    return len(original_tokens & rewritten_tokens) / len(original_tokens)


def text_ngrams(text: str) -> set[str]:
    compact = re.sub(r"\s+", "", to_simplified_chinese(text))
    compact = re.sub(r"[，。！？、；：,.!?;:\"“”‘’（）()\[\]《》<>~\-—]+", "", compact)
    grams = {
        compact[index:index + 2]
        for index in range(max(0, len(compact) - 1))
        if not compact[index:index + 2].isspace()
    }
    stop = {"大家", "今天", "这个", "那个", "就是", "我们", "你们", "他们", "一下"}
    return {gram for gram in grams if gram not in stop}


def bounded_rewrite_chars(value: int | str | None) -> int:
    try:
        parsed = int(value or MAX_REWRITE_CHARS)
    except (TypeError, ValueError):
        parsed = MAX_REWRITE_CHARS
    return min(MAX_REWRITE_CHARS, max(20, parsed))


def light_paraphrase(text: str) -> str:
    replacements = [
        ("大家好", "各位好"),
        ("今天", "这次"),
        ("终于", "总算"),
        ("希望你能", "希望大家可以"),
        ("关注", "支持"),
    ]
    result = to_simplified_chinese(text).strip()
    for source, target in replacements:
        result = result.replace(source, target)
    return format_spoken_lines(result)


def format_spoken_lines(text: str, max_line_chars: int = 28) -> str:
    text = to_simplified_chinese(text)
    cleaned = re.sub(r"\s+", "", text.strip())
    cleaned = re.sub(r"[，。！？、；：,.!?;:\"“”‘’（）()\[\]《》<>~\-—]+", "\n", cleaned)
    lines: list[str] = []
    for raw in cleaned.splitlines():
        line = raw.strip()
        while len(line) > max_line_chars:
            lines.append(line[:max_line_chars])
            line = line[max_line_chars:]
        if line:
            lines.append(line)
    return "\n".join(lines).strip()


_TRADITIONAL_MAP = str.maketrans(
    {
        "開": "开",
        "後": "后",
        "臺": "台",
        "觀": "观",
        "眾": "众",
        "裡": "里",
        "這": "这",
        "個": "个",
        "麼": "么",
        "會": "会",
        "說": "说",
        "讓": "让",
        "對": "对",
        "與": "与",
        "為": "为",
        "裡": "里",
    }
)


def to_simplified_chinese(text: str) -> str:
    return text.translate(_TRADITIONAL_MAP)


def short_json(value: Any) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False)
    except TypeError:
        text = repr(value)
    return text[:500]
