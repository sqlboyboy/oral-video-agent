from app.models import SubtitleStyle
from app.pipeline.subtitles import generate_ass, generate_srt, preview_subtitles
from app.pipeline.subtitle_templates import SUBTITLE_TEMPLATES
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_subtitle_style_defaults_to_first_template():
    style = SubtitleStyle()

    assert style.template_id == "renovation_pitfall_yellow"
    assert style.font_size == 64
    assert style.max_chars_per_line == 9
    assert style.outline_width == 5
    assert style.margin_v == 510


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


def test_generate_srt_applies_template_keyword_color_to_second_line(tmp_path):
    output = tmp_path / "subtitle-highlight.srt"

    generate_srt(
        "abcdefghijkl",
        SubtitleStyle(max_chars_per_line=6, keyword_color="#FFE23B"),
        output,
    )

    text = output.read_text(encoding="utf-8")
    assert 'abcdef\n<font color="#FFE23B">ghijkl</font>' in text


def test_generate_ass_uses_portrait_canvas_and_exact_drag_position(tmp_path):
    output = tmp_path / "subtitle.ass"

    generate_ass(
        "abcdefghijkl",
        SubtitleStyle(
            font_size=54,
            position="custom",
            position_x=0.7,
            position_y=0.31,
            max_chars_per_line=6,
            keyword_color="#43B8FF",
        ),
        output,
    )

    text = output.read_text(encoding="utf-8")
    assert "PlayResX: 1080" in text
    assert "PlayResY: 1920" in text
    assert "Style: Default,Microsoft YaHei,54" in text
    assert r"{\an8\pos(756,595)}abcdef\N" in text
    assert r"{\c&H00FFB843&}ghijkl" in text


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


def test_subtitle_templates_endpoint_returns_researched_presets():
    res = client.get("/api/subtitles/templates")

    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 10
    assert {item["industry"] for item in items} == {"装修", "餐饮", "培训", "国学"}
    assert items[0]["template_id"] == "renovation_pitfall_yellow"


def test_all_subtitle_template_base_styles_are_valid():
    for template_id, item in SUBTITLE_TEMPLATES.items():
        style = SubtitleStyle(template_id=template_id, **item["style"])

        assert style.template_id == template_id
        assert style.font_size >= 54
        assert style.max_chars_per_line in {8, 9, 10}
