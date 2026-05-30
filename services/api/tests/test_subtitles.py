from app.models import SubtitleStyle
from app.pipeline.subtitles import generate_srt, preview_subtitles
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_preview_subtitles_wraps_text_by_style():
    lines = preview_subtitles("一二三四五六七八九十十一十二", SubtitleStyle(max_chars_per_line=8))

    assert lines == ["一二三四五六七八", "九十十一十二"]


def test_generate_srt_uses_preview_lines(tmp_path):
    output = tmp_path / "subtitle.srt"

    generate_srt("第一句。第二句。", SubtitleStyle(max_chars_per_line=20), output)

    text = output.read_text(encoding="utf-8")
    assert "1\n00:00:00,000 --> 00:00:01,000\n第一句。" in text
    assert "2\n00:00:01,000 --> 00:00:02,000\n第二句。" in text


def test_subtitle_preview_endpoint_returns_lines_and_style():
    res = client.post(
        "/api/subtitles/preview",
        json={
            "script": "智能口播可以自动生成字幕效果",
            "style": {
                "font_size": 36,
                "color": "#FFFFFF",
                "outline_color": "#000000",
                "position": "bottom",
                "max_chars_per_line": 8,
            },
        },
    )

    assert res.status_code == 200
    body = res.json()
    assert body["lines"] == ["智能口播可以自动", "生成字幕效果"]
    assert body["style"]["font_size"] == 36
