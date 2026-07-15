import pytest

from app.providers.douyin_creator import (
    DouyinCreatorCollector,
    DouyinCreatorFetchError,
    DouyinCreatorInputError,
    _parse_post_payloads,
    _parse_profile_payload,
)


FULL_PROFILE_SHARE_TEXT = (
    "4- 长按复制此条消息，打开抖音搜索，查看TA的更多作品。 "
    "https://v.douyin.com/0gML0Mg7Utw/ user@example.com :5pm"
)


def test_parse_profile_payload_supports_public_profile_response():
    result = _parse_profile_payload(
        {
            "user": {
                "nickname": "老邱讲装修",
                "unique_id": "32522517400",
                "signature": "分享真实的装修经验给大家",
                "sec_uid": "sec-test",
                "follower_count": 12345,
            }
        }
    )

    assert result == {
        "nickname": "老邱讲装修",
        "unique_id": "32522517400",
        "signature": "分享真实的装修经验给大家",
        "sec_uid": "sec-test",
        "follower_count": 12345,
    }


def test_parse_post_payloads_deduplicates_and_limits_descriptions():
    result = _parse_post_payloads(
        [
            {
                "aweme_list": [
                    {"aweme_id": "1", "desc": "装修瓷砖进场，记住这6个验收细节#装修避坑 #装修分享"},
                    {"aweme_id": "2", "desc": "装修瓷砖进场，记住这6个验收细节"},
                    {"aweme_id": "3", "desc": "阳台封窗户避坑指南"},
                ]
            }
        ],
        max_works=2,
    )

    assert [item.aweme_id for item in result] == ["1", "3"]
    assert [item.description for item in result] == [
        "装修瓷砖进场，记住这6个验收细节",
        "阳台封窗户避坑指南",
    ]


def test_collector_accepts_entire_share_message_and_builds_snapshot(monkeypatch):
    collector = DouyinCreatorCollector(max_works=12)
    profile_payload = {
        "user": {
            "nickname": "老邱讲装修",
            "unique_id": "32522517400",
            "signature": "分享真实装修经验",
            "sec_uid": "sec-test",
            "follower_count": 99,
        }
    }
    post_payload = {
        "aweme_list": [
            {"aweme_id": "work-1", "desc": "全屋定制安装盯紧这6个细节"},
            {"aweme_id": "work-2", "desc": "乳胶漆施工前必须说清的要求"},
        ]
    }
    seen_urls = []

    def fake_browse(url):
        seen_urls.append(url)
        return [profile_payload], [post_payload], "https://www.douyin.com/user/sec-test"

    monkeypatch.setattr(collector, "_browse", fake_browse)

    snapshot = collector.collect(FULL_PROFILE_SHARE_TEXT)

    assert seen_urls == ["https://v.douyin.com/0gML0Mg7Utw/"]
    assert snapshot.nickname == "老邱讲装修"
    assert snapshot.sec_uid == "sec-test"
    assert snapshot.unique_id == "32522517400"
    assert len(snapshot.recent_works) == 2


def test_collector_rejects_text_without_douyin_profile_url():
    with pytest.raises(DouyinCreatorInputError, match="抖音主页链接"):
        DouyinCreatorCollector().collect("这里只有普通文字，没有链接")


def test_collector_requires_public_profile_payload(monkeypatch):
    collector = DouyinCreatorCollector()
    monkeypatch.setattr(
        collector,
        "_browse",
        lambda _url: ([], [], "https://www.douyin.com/user/sec-test"),
    )

    with pytest.raises(DouyinCreatorFetchError, match="公开资料"):
        collector.collect(FULL_PROFILE_SHARE_TEXT)
