import pytest

from app.models import RewriteRequest
from app.providers.rewrite import (
    DeepSeekRewriteProvider,
    MAX_REWRITE_CHARS,
    RewriteProvider,
    _format_spoken_lines,
    _script_similarity,
    build_rewrite_prompt,
    create_rewrite_provider,
)
from app.settings import Settings
from app.text_normalization import to_simplified_chinese


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
    assert "相似度控制在 85% 左右" in prompt
    assert "不要只是给原文补标点" in prompt
    assert "不要包含任何中英文标点符号" in prompt
    assert "仿写风格：种草" in prompt
    assert "产品/服务：智能口播软件" in prompt
    assert "目标人群：短视频创作者" in prompt
    assert "期望时长：约 45 秒" in prompt
    assert "原始口播内容" in prompt


def test_create_rewrite_provider_defaults_to_placeholder():
    provider = create_rewrite_provider(Settings(rewrite_provider="placeholder"))

    assert isinstance(provider, RewriteProvider)


def test_rewrite_prompt_uses_model_constraint_for_300_chars():
    prompt = build_rewrite_prompt("source", RewriteRequest())

    assert f"不超过 {MAX_REWRITE_CHARS} 字" in prompt


def test_deepseek_provider_reports_missing_key_when_used():
    provider = create_rewrite_provider(Settings(rewrite_provider="deepseek", deepseek_api_key=None))

    with pytest.raises(RuntimeError, match="services/api/.env"):
        provider.rewrite("原始文案", RewriteRequest())


def test_create_rewrite_provider_uses_deepseek_when_configured():
    provider = create_rewrite_provider(
        Settings(
            rewrite_provider="deepseek",
            deepseek_api_key="test-key",
            deepseek_model="deepseek-v4-flash",
        )
    )

    assert isinstance(provider, DeepSeekRewriteProvider)


def test_placeholder_rewrite_keeps_topic_without_prompt_preview():
    result = RewriteProvider().rewrite(
        "先讲痛点，再讲方法，最后引导行动。",
        RewriteRequest(style="知识口播", product_info="AI 视频工具"),
    )

    assert "痛点" in result
    assert "方法" in result
    assert "行动" in result
    assert "AI 视频工具" not in result
    assert "Prompt Preview" not in result


def test_placeholder_rewrite_reduces_first_video_similarity():
    original = "Hello 大家好今天终于鼓足勇气拍了第一条视频很荣幸第一条视频就被你刷到希望你能给我点个关注给我一点鼓励吧谢谢"

    result = RewriteProvider().rewrite(original, RewriteRequest(style="同款口播", product_info="智能口播软件"))

    assert "关注" in result
    assert "智能口播软件" not in result
    assert result != original
    similarity = _script_similarity(original, result)
    assert 0.80 <= similarity <= 0.90


def test_rewrite_output_removes_punctuation_but_keeps_lines():
    result = _format_spoken_lines("大家好，今天聊方法！\n先讲第一点；再讲第二点。")

    assert result == "大家好今天聊方法\n先讲第一点\n再讲第二点"
    assert not any(char in result for char in "，。！？；：,.!?;:")


def test_rewrite_outputs_simplified_chinese():
    result = RewriteProvider().rewrite("開直播後臺觀眾", RewriteRequest())

    assert to_simplified_chinese("開直播後臺觀眾") == "开直播后台观众"
    assert "開" not in result
    assert "後臺" not in result
