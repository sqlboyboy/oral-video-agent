from __future__ import annotations

import json

from app.douyin_transcriber import (
    _extract_aweme_id,
    _find_video_url_in_payload,
    _is_aweme_detail_api,
    _parse_router_data_video_url,
    extract_douyin_share_url,
)


def test_extracts_douyin_url_and_aweme_id_from_share_text():
    share_text = (
        "复制打开抖音 https://www.douyin.com/video/7602450741786360310 "
        "直接观看视频"
    )
    url = extract_douyin_share_url(share_text)

    assert url == "https://www.douyin.com/video/7602450741786360310"
    assert _extract_aweme_id(url) == "7602450741786360310"
    assert _extract_aweme_id("https://www.iesdouyin.com/share/video/7602450741786360310/") == (
        "7602450741786360310"
    )


def test_detail_api_match_uses_path_instead_of_query_string():
    assert _is_aweme_detail_api(
        "https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=123"
    )
    assert not _is_aweme_detail_api(
        "https://www.douyin.com/aweme/v1/web/seo/inner/link/?next=aweme/detail"
    )


def test_finds_video_url_in_nested_mobile_router_payload():
    payload = {
        "loaderData": {
            "video_(id)/page": {
                "videoInfoRes": {
                    "item_list": [
                        {
                            "video": {
                                "play_addr": {
                                    "uri": "video-id",
                                    "url_list": [
                                        "https://aweme.snssdk.com/aweme/v1/playwm/?video_id=video-id"
                                    ],
                                }
                            }
                        }
                    ]
                }
            }
        }
    }
    html = (
        "<html><script>window._ROUTER_DATA = "
        + json.dumps(payload, ensure_ascii=False)
        + "</script></html>"
    )

    assert _parse_router_data_video_url(html) == (
        "https://aweme.snssdk.com/aweme/v1/playwm/?video_id=video-id"
    )


def test_prefers_direct_douyin_cdn_video_url():
    payload = {
        "first": {
            "play_addr": {
                "url_list": [
                    "https://aweme.snssdk.com/aweme/v1/playwm/?video_id=watermark"
                ]
            }
        },
        "second": {
            "download_addr": {
                "url_list": ["https://v3-web.douyinvod.com/video/tos/example"]
            }
        },
    }

    assert _find_video_url_in_payload(payload) == (
        "https://v3-web.douyinvod.com/video/tos/example"
    )
