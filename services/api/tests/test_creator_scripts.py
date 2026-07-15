from fastapi.testclient import TestClient

from app import main as main_module
from app.main import app
from app.models import CreatorScriptCandidate, CreatorStyleProfile
from app.providers.creator_scripts import (
    PlaceholderCreatorScriptProvider,
    _extract_json_object,
    create_creator_script_provider,
)
from app.providers.douyin_creator import (
    DouyinCreatorSnapshot,
    DouyinCreatorWork,
)
from app.settings import Settings


client = TestClient(app)


def _snapshot() -> DouyinCreatorSnapshot:
    return DouyinCreatorSnapshot(
        profile_url="https://www.douyin.com/user/sec-test",
        sec_uid="sec-test",
        nickname="装修创作者",
        signature="分享装修经验，帮助大家少踩坑",
        recent_works=[
            DouyinCreatorWork(description="瓷砖进场记住这6个验收细节"),
            DouyinCreatorWork(description="全屋定制安装盯紧这5个地方"),
        ],
    )


def _style_profile() -> CreatorStyleProfile:
    return CreatorStyleProfile(
        creator_name="装修创作者",
        summary="实用经验型口播",
        tone=["直接", "务实"],
        hook_patterns=["数字清单开场"],
        structure_patterns=["痛点", "分点建议", "行动提醒"],
        language_features=["短句", "口语化"],
        audience="准备装修的普通用户",
        cta_patterns=["建议收藏"],
        source_count=2,
        sec_uid="sec-test",
    )


def _candidates(round_number: int = 1) -> list[CreatorScriptCandidate]:
    return [
        CreatorScriptCandidate(
            candidate_id=f"candidate-{round_number}-{index}",
            title=f"装修候选{round_number}-{index}",
            angle=f"角度{index}",
            script=f"这是第{index}篇围绕装修生成的完整口播文案。",
            reason=f"采用不同的角度{index}",
        )
        for index in range(1, 9)
    ]


def test_placeholder_provider_analyzes_snapshot_and_generates_eight_unique_scripts():
    provider = PlaceholderCreatorScriptProvider()

    profile = provider.analyze_style(_snapshot())
    items = provider.generate_scripts(
        profile,
        keyword="装修",
        count=8,
        duration_seconds=60,
        generation_round=1,
        exclude_titles=[],
    )

    assert profile.creator_name == "装修创作者"
    assert profile.source_count == 2
    assert len(items) == 8
    assert len({item.title for item in items}) == 8
    assert len({item.angle for item in items}) == 8
    assert all("装修" in item.script for item in items)


def test_provider_factory_falls_back_to_placeholder_without_deepseek_key():
    provider = create_creator_script_provider(
        Settings(rewrite_provider="deepseek", deepseek_api_key=None)
    )

    assert isinstance(provider, PlaceholderCreatorScriptProvider)


def test_json_parser_accepts_markdown_code_fence():
    result = _extract_json_object('```json\n{"items": []}\n```')

    assert result == {"items": []}


def test_generate_endpoint_collects_analyzes_and_returns_frontend_contract(monkeypatch):
    calls = {"collect": 0, "analyze": 0, "generate": 0}

    class FakeCollector:
        def collect(self, share_text):
            calls["collect"] += 1
            assert share_text.startswith("4-")
            return _snapshot()

    class FakeProvider:
        def analyze_style(self, snapshot):
            calls["analyze"] += 1
            assert snapshot.nickname == "装修创作者"
            return _style_profile()

        def generate_scripts(self, style_profile, **kwargs):
            calls["generate"] += 1
            assert style_profile.sec_uid == "sec-test"
            assert kwargs == {
                "keyword": "装修",
                "count": 8,
                "duration_seconds": 60,
                "generation_round": 1,
                "exclude_titles": [],
            }
            return _candidates()

    monkeypatch.setattr(main_module, "douyin_creator_collector", FakeCollector())
    monkeypatch.setattr(main_module, "creator_script_provider", FakeProvider())

    response = client.post(
        "/api/creator-scripts/generate",
        json={
            "share_text": (
                "4- 长按复制此条消息，打开抖音搜索，查看TA的更多作品。 "
                "https://v.douyin.com/0gML0Mg7Utw/ user@example.com :5pm"
            ),
            "keyword": "装修",
            "count": 8,
            "duration_seconds": 60,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["batch_id"]
    assert body["creator_name"] == "装修创作者"
    assert body["keyword"] == "装修"
    assert body["generation_round"] == 1
    assert body["style_profile"]["sec_uid"] == "sec-test"
    assert len(body["items"]) == 8
    assert calls == {"collect": 1, "analyze": 1, "generate": 1}


def test_regenerate_endpoint_reuses_style_profile_without_collecting_or_analyzing(monkeypatch):
    calls = {"generate": 0}

    class ForbiddenCollector:
        def collect(self, _share_text):
            raise AssertionError("重新生成不应再次抓取主页")

    class RegenerateProvider:
        def analyze_style(self, _snapshot):
            raise AssertionError("重新生成不应再次分析风格")

        def generate_scripts(self, style_profile, **kwargs):
            calls["generate"] += 1
            assert style_profile.creator_name == "装修创作者"
            assert kwargs["generation_round"] == 2
            assert kwargs["exclude_titles"] == ["装修候选1-1"]
            return _candidates(round_number=2)

    monkeypatch.setattr(main_module, "douyin_creator_collector", ForbiddenCollector())
    monkeypatch.setattr(main_module, "creator_script_provider", RegenerateProvider())

    response = client.post(
        "/api/creator-scripts/generate",
        json={
            "share_text": "",
            "keyword": "装修",
            "count": 8,
            "duration_seconds": 60,
            "style_profile": _style_profile().model_dump(),
            "generation_round": 2,
            "exclude_titles": ["装修候选1-1"],
        },
    )

    assert response.status_code == 200
    assert response.json()["generation_round"] == 2
    assert response.json()["items"][0]["candidate_id"] == "candidate-2-1"
    assert calls == {"generate": 1}


def test_generate_endpoint_rejects_missing_profile_share_text():
    response = client.post(
        "/api/creator-scripts/generate",
        json={"share_text": "", "keyword": "装修", "count": 8},
    )

    assert response.status_code == 400
    assert "抖音主页链接" in response.json()["detail"]


def test_generate_endpoint_requires_exactly_eight_candidates():
    response = client.post(
        "/api/creator-scripts/generate",
        json={"share_text": "ignored", "keyword": "装修", "count": 7},
    )

    assert response.status_code == 422


def test_create_task_from_selected_script_persists_cloud_deep_task():
    response = client.post(
        "/api/tasks/from-script",
        json={
            "title": "装修避坑清单",
            "original_script": "",
            "rewritten_script": "装修之前先把需求和预算写清楚，再逐项核对现场细节。",
        },
    )

    assert response.status_code == 200
    task = response.json()
    task_id = task["task_id"]
    try:
        assert task_id.startswith("cloud-deep-")
        assert task["title"] == "装修避坑清单"
        assert task["status"] == "rewritten"
        assert task["rewritten_script"].startswith("装修之前")

        fetched = client.get(f"/api/tasks/{task_id}")
        assert fetched.status_code == 200
        assert fetched.json()["rewritten_script"] == task["rewritten_script"]
    finally:
        client.delete(f"/api/tasks/{task_id}")


def test_create_task_from_script_rejects_blank_rewritten_script():
    response = client.post(
        "/api/tasks/from-script",
        json={"rewritten_script": "   "},
    )

    assert response.status_code == 400
