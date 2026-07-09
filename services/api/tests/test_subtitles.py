from app.models import SubtitleStyle
from app.pipeline.subtitles import generate_srt, preview_subtitles
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_subtitle_style_defaults_to_small_wrapped_captions():
    style = SubtitleStyle()

    assert style.font_size == 12
    assert style.max_chars_per_line == 12
    assert style.outline_width == 2
    assert style.margin_v == 70


def test_preview_subtitles_wraps_long_sentence_inside_caption():
    lines = preview_subtitles("abcdefghijklmnopqr", SubtitleStyle(max_chars_per_line=8))

    assert lines == ["abcdefgh\nijklmnop", "qr"]


def test_preview_subtitles_outputs_simplified_chinese():
    lines = preview_subtitles("開直播後臺觀眾", SubtitleStyle(max_chars_per_line=20))

    assert lines == ["开直播后台观众"]


def test_generate_srt_keeps_separate_sentences_as_separate_cues(tmp_path):
    output = tmp_path / "subtitle.srt"

    generate_srt("first。second。", SubtitleStyle(max_chars_per_line=20), output)

    text = output.read_text(encoding="utf-8")
    assert "1\n00:00:00,000 --> 00:00:01,000\nfirst。\n" in text
    assert "2\n00:00:01,000 --> 00:00:02,000\nsecond。\n" in text


def test_subtitle_preview_endpoint_returns_multiline_caption_and_style():
    res = client.post(
        "/api/subtitles/preview",
        json={
            "script": "abcdefghijklmnopqr",
            "style": {
                "font_size": 12,
                "color": "#FFFFFF",
                "outline_color": "#000000",
                "position": "bottom",
                "max_chars_per_line": 8,
            },
        },
    )

    assert res.status_code == 200
    body = res.json()
    assert body["lines"] == ["abcdefgh\nijklmnop", "qr"]
    assert body["style"]["font_size"] == 12
