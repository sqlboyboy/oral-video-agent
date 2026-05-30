from typing import Protocol

import anthropic
from anthropic import Anthropic

from ..models import RewriteRequest
from ..settings import Settings


class ScriptRewriteProvider(Protocol):
    def rewrite(self, original_script: str, req: RewriteRequest) -> str:
        ...


def build_rewrite_prompt(original_script: str, req: RewriteRequest) -> str:
    product = req.product_info or "用户提供的产品/服务"
    audience = req.target_audience or "目标用户"
    duration = f"约 {req.duration_seconds} 秒" if req.duration_seconds else "适合短视频口播时长"
    return (
        "你是短视频口播文案策划。请基于原文的表达结构和节奏进行原创仿写，"
        "不要逐字复制原文，不要保留他人的专属身份、品牌、承诺或不可验证数据。\n\n"
        f"仿写风格：{req.style}\n"
        f"产品/服务：{product}\n"
        f"目标人群：{audience}\n"
        f"期望时长：{duration}\n\n"
        "输出要求：\n"
        "1. 开头 3 秒抓住注意力。\n"
        "2. 中段讲清痛点、场景、解决方案和核心卖点。\n"
        "3. 结尾给出自然行动引导。\n"
        "4. 语言要像真人口播，句子短，有节奏。\n\n"
        f"原口播文本：\n{original_script}"
    )


class PlaceholderRewriteProvider:
    def rewrite(self, original_script: str, req: RewriteRequest) -> str:
        audience = f"面向{req.target_audience}" if req.target_audience else "面向目标用户"
        product = req.product_info or "你的产品/服务"
        duration = f"控制在约{req.duration_seconds}秒" if req.duration_seconds else "适合短视频节奏"
        prompt = build_rewrite_prompt(original_script, req)
        return (
            f"【{req.style}】\n"
            f"你是不是也遇到过这种情况：明明想把{product}讲清楚，但一开口就没有重点？\n"
            f"其实爆款口播不是照搬别人，而是复用它的表达结构：先抛痛点，再给结果，最后给行动理由。\n"
            f"这条内容会{audience}，用更自然、更有记忆点的方式，把核心卖点讲出来。\n"
            f"如果你也想做出这种效果，可以先从一个清晰的开头、一句有画面感的卖点、一个明确的结尾开始。\n"
            f"要求：{duration}。\n\n"
            f"参考原文结构：{original_script[:160]}\n\n"
            f"---\nPrompt Preview:\n{prompt[:260]}"
        )


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
        return "\n".join(texts).strip()


def create_rewrite_provider(settings: Settings) -> ScriptRewriteProvider:
    if settings.rewrite_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required when REWRITE_PROVIDER=anthropic")
        return AnthropicRewriteProvider(settings.anthropic_api_key, settings.anthropic_model)
    return PlaceholderRewriteProvider()


RewriteProvider = PlaceholderRewriteProvider
