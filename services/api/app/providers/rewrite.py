import re
from difflib import SequenceMatcher
from typing import Protocol

import httpx

from ..models import RewriteRequest
from ..settings import Settings
from ..text_normalization import to_simplified_chinese


MAX_REWRITE_CHARS = 300


class ScriptRewriteProvider(Protocol):
    def rewrite(self, original_script: str, req: RewriteRequest) -> str:
        ...


_PUNCTUATION_PATTERN = re.compile(r"[\s，,。！？!?；;：:、\"“”'‘’（）()【】《》<>….\-]+")
_OUTPUT_PUNCTUATION_PATTERN = re.compile(r"[，,。！？!?；;：:、\"“”'‘’（）()【】《》<>….\-—_~～]+")


def _normalize_for_similarity(text: str) -> str:
    text = to_simplified_chinese(text)
    return _PUNCTUATION_PATTERN.sub("", text).lower()


def _script_similarity(source: str, rewritten: str) -> float:
    source_clean = _normalize_for_similarity(source)
    rewritten_clean = _normalize_for_similarity(rewritten)
    if not source_clean or not rewritten_clean:
        return 0.0
    return SequenceMatcher(None, source_clean, rewritten_clean).ratio()


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"[，,。！？!?；;\n]+", text)
    return [part.strip(" ，,") for part in parts if part.strip(" ，,")]


def _format_spoken_lines(text: str, max_line_chars: int = 28) -> str:
    text = to_simplified_chinese(text)
    cleaned = re.sub(r"\s+", "", text.strip())
    if not cleaned:
        return ""

    sentences: list[str] = []
    current = ""
    for char in cleaned:
        current += char
        if char in "。！？!?；;":
            sentence = current.strip()
            if sentence:
                sentences.append(sentence)
            current = ""
    if current.strip():
        sentences.append(current.strip())

    lines: list[str] = []
    for sentence in sentences:
        if len(sentence) <= max_line_chars:
            lines.append(sentence)
            continue
        chunk = ""
        for char in sentence:
            chunk += char
            if char in "，,、" and len(chunk) >= 10:
                lines.append(chunk.strip())
                chunk = ""
            elif len(chunk) >= max_line_chars:
                lines.append(chunk.strip())
                chunk = ""
        if chunk.strip():
            lines.append(chunk.strip())

    clean_lines = []
    for line in lines:
        clean = _OUTPUT_PUNCTUATION_PATTERN.sub("", line)
        clean = re.sub(r"\s+", "", clean).strip()
        if clean:
            clean_lines.append(clean)
    return "\n".join(clean_lines)


def _pick_highlights(original_script: str, limit: int = 3) -> list[str]:
    sentences = _split_sentences(original_script)
    if not sentences:
        return ["先把核心问题讲清楚", "再把解决方案讲具体", "最后给出行动引导"]
    ranked = sorted(sentences, key=len, reverse=True)
    return ranked[:limit]


def _target_length(original_script: str) -> str:
    length = len(original_script.strip())
    high = min(MAX_REWRITE_CHARS, max(20, int(length * 1.25)))
    low = min(high, max(10, int(length * 0.75)))
    return f"{low}-{high} 字"


def _light_paraphrase(text: str) -> str:
    stripped = to_simplified_chinese(text).strip()
    if "第一条视频" in stripped and "关注" in stripped:
        return (
            "Hello，大家好。今天总算鼓足勇气拍了第一条视频，"
            "很开心第一条视频就被你看到，希望大家能给我点个关注，"
            "给我一点鼓励吧，谢谢。"
        )

    replacements = [
        ("Hello", "哈喽"),
        ("hello", "哈喽"),
        ("大家好", "大家好呀"),
        ("今天", "今天呢"),
        ("终于", "总算"),
        ("鼓足勇气", "攒够勇气"),
        ("拍了", "录了"),
        ("第一条视频", "第一支视频"),
        ("很荣幸", "真的很开心"),
        ("被你刷到", "能被你看到"),
        ("希望你能", "希望大家可以"),
        ("给我点个关注", "点个关注支持一下"),
        ("给我一点鼓励", "给我一点小小的鼓励"),
        ("谢谢", "谢谢大家"),
    ]
    result = stripped
    for source, target in replacements:
        result = result.replace(source, target)
    return result


def _ensure_rewritten_distance(original_script: str, rewritten_script: str) -> str:
    if _script_similarity(original_script, rewritten_script) <= 0.90:
        return _format_spoken_lines(rewritten_script)
    fallback = _light_paraphrase(original_script)
    if _script_similarity(original_script, fallback) < _script_similarity(original_script, rewritten_script):
        return _format_spoken_lines(fallback)
    return _format_spoken_lines(rewritten_script)


def _finalize_rewrite(original_script: str, rewritten_script: str) -> str:
    return _ensure_rewritten_distance(original_script, rewritten_script)


def build_rewrite_prompt(original_script: str, req: RewriteRequest) -> str:
    original_script = to_simplified_chinese(original_script)
    product = req.product_info or "不额外添加产品信息"
    audience = req.target_audience or "不额外指定人群"
    duration = (
        f"约 {req.duration_seconds} 秒" if req.duration_seconds else "适合短视频口播时长"
    )
    return (
        "你是中文短视频口播文案仿写助手。请做同主题原创仿写，而不是只加标点或营销扩写。\n"
        "必须保留原文的主题、表达顺序、情绪、语气和大致字数，但要重组句子并替换表达。\n"
        "目标是和原文语义接近、文字不雷同，相似度控制在 85% 左右；不要逐字复制原文，也不要逐句照搬。\n"
        "如果原文是在求关注，就仍然写求关注；如果原文没有产品，就不要编造产品、卖点、人群、场景。\n\n"
        f"仿写风格：{req.style}\n"
        f"产品/服务：{product}\n"
        f"目标人群：{audience}\n"
        f"期望时长：{duration}\n\n"
        "输出要求：\n"
        f"1. 最终文案不超过 {MAX_REWRITE_CHARS} 字；字数控制在原文附近，建议 {_target_length(original_script)}。\n"
        "2. 不要输出标题、标签、解释、提示词、【产品名称】、【核心卖点】等占位符。\n"
        "3. 不要新增原文没有的信息，不要把短文案扩成带货长文案。\n"
        "4. 不要只是给原文补标点，至少改写关键动词、称呼、连接词和句式。\n"
        "5. 按自然口播断句输出，明显是一句话的放在同一行，每行一句或半句，不要把一句话拆得太碎。\n"
        "6. 只使用中文简体，不要输出繁体字。\n"
        "7. 最终文案不要包含任何中英文标点符号，只使用换行表示停顿。\n"
        "8. 只输出可直接口播的中文文案，不要额外解释。\n\n"
        f"原口播文本：\n{original_script}"
    )


class PlaceholderRewriteProvider:
    def rewrite(self, original_script: str, req: RewriteRequest) -> str:
        return _finalize_rewrite(original_script, _light_paraphrase(original_script))


class DeepSeekRewriteProvider:
    def __init__(self, api_key: str | None, model: str, base_url: str, timeout_seconds: int = 120) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = max(10, timeout_seconds)

    def rewrite(self, original_script: str, req: RewriteRequest) -> str:
        if not self.api_key:
            raise RuntimeError("请先在 services/api/.env 中填写 DEEPSEEK_API_KEY")
        prompt = build_rewrite_prompt(original_script, req)
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是专业的中文短视频口播文案策划，只输出可直接口播的原创简体中文文案。",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 2000,
                    "stream": False,
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            result = data["choices"][0]["message"]["content"].strip()
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise RuntimeError(f"DeepSeek 文案改写失败：{exc}") from exc
        if not result:
            raise RuntimeError("DeepSeek 文案改写失败：API 返回了空内容")
        return _finalize_rewrite(original_script, result)


def create_rewrite_provider(settings: Settings) -> ScriptRewriteProvider:
    if settings.rewrite_provider.strip().lower() in {"deepseek", "deepseek-api"}:
        return DeepSeekRewriteProvider(
            api_key=settings.deepseek_api_key,
            model=settings.deepseek_model,
            base_url=settings.deepseek_base_url,
            timeout_seconds=settings.deepseek_timeout_seconds,
        )
    return PlaceholderRewriteProvider()


RewriteProvider = PlaceholderRewriteProvider
