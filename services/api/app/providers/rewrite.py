from ..models import RewriteRequest


class RewriteProvider:
    def rewrite(self, original_script: str, req: RewriteRequest) -> str:
        audience = f"面向{req.target_audience}" if req.target_audience else "面向目标用户"
        product = req.product_info or "你的产品/服务"
        duration = f"控制在约{req.duration_seconds}秒" if req.duration_seconds else "适合短视频节奏"
        return (
            f"【{req.style}】\n"
            f"你是不是也遇到过这种情况：明明想把{product}讲清楚，但一开口就没有重点？\n"
            f"其实爆款口播不是照搬别人，而是复用它的表达结构：先抛痛点，再给结果，最后给行动理由。\n"
            f"这条内容会{audience}，用更自然、更有记忆点的方式，把核心卖点讲出来。\n"
            f"如果你也想做出这种效果，可以先从一个清晰的开头、一句有画面感的卖点、一个明确的结尾开始。\n"
            f"要求：{duration}。\n\n"
            f"参考原文结构：{original_script[:160]}"
        )
