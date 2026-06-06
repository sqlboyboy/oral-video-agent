import re
from difflib import SequenceMatcher
from typing import Protocol

import anthropic
from anthropic import Anthropic

from ..models import RewriteRequest
from ..settings import Settings


class ScriptRewriteProvider(Protocol):
    def rewrite(self, original_script: str, req: RewriteRequest) -> str:
        ...


_PUNCTUATION_PATTERN = re.compile(r"[\s，,。！？!?；;：:、\"“”'‘’（）()【】《》<>….\-]+")


def _normalize_for_similarity(text: str) -> str:
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

    return "\n".join(line for line in lines if line)


def _pick_highlights(original_script: str, limit: int = 3) -> list[str]:
    sentences = _split_sentences(original_script)
    if not sentences:
        return ["先把核心问题讲清楚", "再把解决方案讲具体", "最后给出行动引导"]
    ranked = sorted(sentences, key=len, reverse=True)
    return ranked[:limit]


def _target_length(original_script: str) -> str:
    length = len(original_script.strip())
    low = max(10, int(length * 0.75))
    high = max(low + 8, int(length * 1.25))
    return f"{low}-{high} 字"


def _light_paraphrase(text: str) -> str:
    stripped = text.strip()
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


def build_rewrite_prompt(original_script: str, req: RewriteRequest) -> str:
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
        f"1. 字数控制在原文附近，建议 {_target_length(original_script)}。\n"
        "2. 不要输出标题、标签、解释、提示词、【产品名称】、【核心卖点】等占位符。\n"
        "3. 不要新增原文没有的信息，不要把短文案扩成带货长文案。\n"
        "4. 不要只是给原文补标点，至少改写关键动词、称呼、连接词和句式。\n"
        "5. 按自然口播断句输出，明显是一句话的放在同一行，每行一句或半句，不要把一句话拆得太碎。\n"
        "6. 只输出可直接口播的中文文案，不要额外解释。\n\n"
        f"原口播文本：\n{original_script}"
    )


class PlaceholderRewriteProvider:
    def rewrite(self, original_script: str, req: RewriteRequest) -> str:
        return _ensure_rewritten_distance(original_script, _light_paraphrase(original_script))


class AnthropicRewriteProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = Anthropic(api_key=api_key)
        self.model = model

    def rewrite(self, original_script: str, req: RewriteRequest) -> str:
        prompt = build_rewrite_prompt(original_script, req)
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=16000,
                thinking={"type": "adaptive"},
                output_config={"effort": "medium"},
                system="你是专业的中文短视频口播文案策划，只输出可直接口播的原创中文文案。",
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIError as exc:
            raise RuntimeError(f"Claude rewrite failed: {exc.message}") from exc

        texts = [block.text for block in response.content if block.type == "text"]
        return _ensure_rewritten_distance(original_script, "\n".join(texts).strip())


class QwenLocalRewriteProvider:
    def __init__(self, model_path: str, device: str = "auto", max_new_tokens: int = 900) -> None:
        self.model_path = model_path
        self.device = device
        self.max_new_tokens = max_new_tokens
        self._tokenizer = None
        self._model = None

    def _load(self):
        if self._tokenizer is not None and self._model is not None:
            return self._tokenizer, self._model
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "本地 Qwen 改写需要安装 torch 和 transformers："
                "cd services/api && uv add torch transformers accelerate"
            ) from exc

        model_kwargs = {}
        if self.device == "auto":
            model_kwargs["device_map"] = "auto"
            model_kwargs["torch_dtype"] = "auto"
        else:
            model_kwargs["torch_dtype"] = torch.float16 if self.device.startswith("cuda") else torch.float32

        try:
            tokenizer = AutoTokenizer.from_pretrained(self.model_path, trust_remote_code=True)
            model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                trust_remote_code=True,
                **model_kwargs,
            )
            if self.device != "auto":
                model = model.to(self.device)
        except Exception as exc:
            raise RuntimeError(
                f"本地 Qwen 模型加载失败：{self.model_path}。请确认模型已下载到本机，"
                "或设置 QWEN_MODEL_PATH 指向本地目录。"
            ) from exc

        self._tokenizer = tokenizer
        self._model = model
        return tokenizer, model

    def _has_context_keyword(self, text: str, source: str) -> bool:
        if not source.strip():
            return True
        words = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", source)
        pairs: set[str] = set()
        for word in words:
            if len(word) <= 4:
                pairs.add(word)
            else:
                pairs.update(word[i:i + 2] for i in range(0, len(word) - 1, 2))
        return not pairs or any(pair in text for pair in pairs)

    def _looks_unusable(self, text: str, original_script: str, req: RewriteRequest) -> bool:
        stripped = text.strip()
        if len(stripped) < 30:
            return True
        question_ratio = stripped.count("?") / max(len(stripped), 1)
        prompt_markers = (
            "Prompt",
            "提示词",
            "原文：",
            "要求：",
            "请基于",
            "不要逐字复制",
            "产品名称",
            "核心卖点",
            "目标人群",
            "痛点",
            "解决方案",
            "【",
        )
        if question_ratio > 0.08 or any(marker in stripped for marker in prompt_markers):
            return True
        original_len = max(len(original_script.strip()), 1)
        if len(stripped) > max(80, int(original_len * 1.6)):
            return True
        if req.product_info and not self._has_context_keyword(stripped, req.product_info):
            return True
        highlights = " ".join(_pick_highlights(original_script, limit=2))
        return not self._has_context_keyword(stripped, highlights)

    def rewrite(self, original_script: str, req: RewriteRequest) -> str:
        tokenizer, model = self._load()
        prompt = build_rewrite_prompt(original_script, req)
        messages = [
            {
                "role": "system",
                "content": (
                    "你是中文短视频口播轻度仿写助手。只输出一段和原文主题、顺序、语气、长度接近的中文口播。"
                    "相似度控制在 85% 左右，必须重组句式并替换关键表达，不要只加标点。"
                    "不要扩写，不要加入产品卖点，不解释，不输出提示词，不输出问号占位符。"
                ),
            },
            {"role": "user", "content": prompt},
        ]
        text = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = tokenizer([text], return_tensors="pt")
        inputs = {key: value.to(model.device) for key, value in inputs.items()}
        outputs = model.generate(
            **inputs,
            max_new_tokens=min(self.max_new_tokens, max(80, int(len(original_script) * 2.0))),
            do_sample=True,
            temperature=0.45,
            top_p=0.82,
            repetition_penalty=1.05,
            eos_token_id=tokenizer.eos_token_id,
        )
        generated = outputs[0][inputs["input_ids"].shape[-1]:]
        result = tokenizer.decode(generated, skip_special_tokens=True).strip()
        if self._looks_unusable(result, original_script, req):
            return PlaceholderRewriteProvider().rewrite(original_script, req)
        return _ensure_rewritten_distance(original_script, result)


def create_rewrite_provider(settings: Settings) -> ScriptRewriteProvider:
    if settings.rewrite_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required when REWRITE_PROVIDER=anthropic")
        return AnthropicRewriteProvider(settings.anthropic_api_key, settings.anthropic_model)
    if settings.rewrite_provider in {"qwen", "qwen-local", "qwen2.5"}:
        return QwenLocalRewriteProvider(
            settings.qwen_model_path,
            settings.qwen_device,
            settings.qwen_max_new_tokens,
        )
    return PlaceholderRewriteProvider()


RewriteProvider = PlaceholderRewriteProvider
