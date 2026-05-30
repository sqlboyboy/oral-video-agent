from pydantic import BaseModel


class RewriteStylePreset(BaseModel):
    style_id: str
    name: str
    description: str


REWRITE_STYLE_PRESETS = [
    RewriteStylePreset(style_id="same-style", name="同款口播", description="保留原视频的表达结构和节奏，生成原创口播"),
    RewriteStylePreset(style_id="commerce", name="带货", description="突出产品卖点、使用场景和行动引导"),
    RewriteStylePreset(style_id="knowledge", name="知识口播", description="用清晰逻辑讲解观点、方法和步骤"),
    RewriteStylePreset(style_id="recommend", name="种草", description="强调体验感、画面感和自然推荐"),
    RewriteStylePreset(style_id="emotion", name="情绪价值", description="突出共鸣、陪伴、成长和情绪触发"),
]
