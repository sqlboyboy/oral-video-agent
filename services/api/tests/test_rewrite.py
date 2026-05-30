from app.models import RewriteRequest
from app.providers.rewrite import RewriteProvider, build_rewrite_prompt


def test_build_rewrite_prompt_contains_constraints_and_inputs():
    prompt = build_rewrite_prompt(
        "原始口播内容",
        RewriteRequest(
            style="种草",
            product_info="智能口播软件",
            target_audience="短视频创作者",
            duration_seconds=45,
        ),
    )

    assert "不要逐字复制原文" in prompt
    assert "仿写风格：种草" in prompt
    assert "产品/服务：智能口播软件" in prompt
    assert "目标人群：短视频创作者" in prompt
    assert "期望时长：约 45 秒" in prompt
    assert "原始口播内容" in prompt


def test_rewrite_provider_returns_placeholder_script_with_prompt_preview():
    result = RewriteProvider().rewrite(
        "先讲痛点，再讲方法，最后引导行动。",
        RewriteRequest(style="知识口播", product_info="AI 视频工具"),
    )

    assert "【知识口播】" in result
    assert "AI 视频工具" in result
    assert "Prompt Preview" in result
    assert "不要逐字复制原文" in result
