from pathlib import Path

from PIL import Image, ImageDraw

from app.pipeline.cover import COVER_SIZE, COVER_TEMPLATES, generate_cover_png


def test_cover_templates_only_draw_user_title_and_create_distinct_layouts(
    tmp_path: Path,
    monkeypatch,
):
    background = tmp_path / "background.png"
    Image.new("RGB", COVER_SIZE, (80, 100, 120)).save(background)
    drawn_text: list[str] = []
    original_text = ImageDraw.ImageDraw.text

    def capture_text(self, xy, text, *args, **kwargs):
        drawn_text.append(str(text))
        return original_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture_text)
    outputs: list[bytes] = []
    for template_id in COVER_TEMPLATES:
        output = tmp_path / f"{template_id}.png"
        generate_cover_png(
            "朋友一起见证成长",
            "",
            output,
            background_image_path=background,
            template_id=template_id,
        )
        with Image.open(output) as image:
            assert image.size == COVER_SIZE
            assert image.getpixel((0, 0))[:3] == (80, 100, 120)
            assert image.getpixel((COVER_SIZE[0] - 1, COVER_SIZE[1] - 1))[:3] == (
                80,
                100,
                120,
            )
        outputs.append(output.read_bytes())

    assert len(set(outputs)) == len(COVER_TEMPLATES)
    assert "杰速口播" not in drawn_text
    assert "口播干货" not in drawn_text
    assert "让好内容更容易被看见" not in drawn_text
    assert drawn_text


def test_cover_without_video_frame_is_a_transparent_text_overlay(tmp_path: Path):
    output = tmp_path / "transparent.png"

    generate_cover_png(
        "这件事越早知道越好",
        "",
        output,
        template_id="bold-yellow-white",
    )

    with Image.open(output) as image:
        assert image.mode == "RGBA"
        alpha = image.getchannel("A")
        assert alpha.getpixel((0, 0)) == 0
        assert alpha.getpixel((COVER_SIZE[0] - 1, COVER_SIZE[1] - 1)) == 0
        assert alpha.getbbox() is not None
