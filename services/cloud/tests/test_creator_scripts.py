from __future__ import annotations

import importlib

from fastapi.testclient import TestClient

from app.creator_scripts import (
    DeepSeekCreatorScriptProvider,
    PlaceholderCreatorScriptProvider,
)
from app.douyin_creator import (
    DouyinCreatorSnapshot,
    DouyinCreatorWork,
    _parse_post_payloads,
    _parse_profile_payload,
)


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("CLOUD_DATABASE_PATH", str(tmp_path / "cloud.sqlite3"))
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("REWRITE_PROVIDER", "placeholder")
    monkeypatch.setenv("DOUYIN_CHROMIUM_EXECUTABLE", "")

    import app.settings as settings_module
    import app.main as main_module

    importlib.reload(settings_module)
    importlib.reload(main_module)
    return TestClient(main_module.app), main_module


def _snapshot() -> DouyinCreatorSnapshot:
    return DouyinCreatorSnapshot(
        profile_url="https://www.douyin.com/user/example",
        sec_uid="example",
        nickname="测试创作者",
        signature="分享实用经验",
        recent_works=[
            DouyinCreatorWork(description=f"作品 {index} 的公开描述")
            for index in range(1, 13)
        ],
    )


def test_parses_creator_profile_and_deduplicates_recent_works():
    profile = _parse_profile_payload(
        {
            "user": {
                "nickname": "老邱讲装修",
                "signature": "装修避坑",
                "sec_uid": "creator-sec-uid",
                "follower_count": "12345",
            }
        }
    )
    works = _parse_post_payloads(
        [
            {
                "aweme_list": [
                    {"aweme_id": "1", "desc": "验收记住三点 #装修 #避坑"},
                    {"aweme_id": "2", "desc": "验收记住三点 #装修 #避坑"},
                    {"aweme_id": "3", "desc": "预算别只看总价 #装修"},
                ]
            }
        ]
    )

    assert profile["nickname"] == "老邱讲装修"
    assert profile["follower_count"] == 12345
    assert [work.description for work in works] == [
        "验收记住三点",
        "预算别只看总价",
    ]


def test_creator_scripts_endpoint_requires_cloud_account(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/client/creator-scripts/generate",
        json={"share_text": "https://v.douyin.com/example/", "keyword": "装修"},
    )

    assert response.status_code == 401


def test_first_generation_returns_eight_candidates_and_reuses_profile(
    monkeypatch, tmp_path
):
    client, main_module = _client(monkeypatch, tmp_path)

    class FakeCollector:
        calls = 0

        def collect(self, share_text: str) -> DouyinCreatorSnapshot:
            assert "v.douyin.com" in share_text
            self.calls += 1
            return _snapshot()

    collector = FakeCollector()
    main_module.douyin_creator_collector = collector
    main_module.creator_script_provider = PlaceholderCreatorScriptProvider()
    main_module.app.dependency_overrides[main_module.require_cloud_account] = lambda: {
        "user": {"user_id": "test-user"}
    }

    first = client.post(
        "/api/client/creator-scripts/generate",
        json={
            "share_text": "4- 复制主页 https://v.douyin.com/example/ user@example.com :5pm",
            "keyword": "装修",
            "count": 8,
            "duration_seconds": 60,
        },
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["creator_name"] == "测试创作者"
    assert first_body["style_profile"]["source_count"] == 12
    assert len(first_body["items"]) == 8
    assert len({item["title"] for item in first_body["items"]}) == 8
    assert collector.calls == 1

    second = client.post(
        "/api/client/creator-scripts/generate",
        json={
            "share_text": "",
            "keyword": "装修",
            "count": 8,
            "duration_seconds": 60,
            "generation_round": 2,
            "style_profile": first_body["style_profile"],
            "exclude_titles": [item["title"] for item in first_body["items"]],
        },
    )
    assert second.status_code == 200, second.text
    assert len(second.json()["items"]) == 8
    assert collector.calls == 1

    main_module.app.dependency_overrides.clear()


def test_deepseek_invalid_json_is_retried(monkeypatch):
    import app.creator_scripts as creator_scripts_module

    responses = iter(
        [
            {"choices": [{"message": {"content": '{"items": [invalid}'}}]},
            {"choices": [{"message": {"content": '{"items": []}'}}]},
        ]
    )
    calls = []

    def fake_post_json(url, payload, **kwargs):
        calls.append((url, payload, kwargs))
        return next(responses)

    monkeypatch.setattr(creator_scripts_module, "post_json", fake_post_json)
    provider = DeepSeekCreatorScriptProvider(
        api_key="test-key",
        model="test-model",
        base_url="https://example.invalid",
    )

    result = provider._call_json(
        system_prompt="system",
        user_prompt="user",
        max_tokens=100,
        temperature=0.9,
    )

    assert result == {"items": []}
    assert len(calls) == 2
    assert "上一次返回的 JSON 无法解析" in calls[1][1]["messages"][-1]["content"]
