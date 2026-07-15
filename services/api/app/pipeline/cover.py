import math
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


COVER_SIZE = (720, 1280)
DEFAULT_COVER_TEMPLATE = "bold-yellow-white"
COVER_TEMPLATES = {
    "bold-yellow-white": {
        "name": "黄白重磅",
        "description": "白字、黄色重点、粗黑描边",
    },
    "red-white-emphasis": {
        "name": "红白强调",
        "description": "白字、红色重点、粗黑描边",
    },
    "black-white-clean": {
        "name": "黑白极简",
        "description": "纯白粗体、加重黑描边",
    },
    "blue-white-clear": {
        "name": "蓝白清晰",
        "description": "蓝色数字或方法词、深蓝描边",
    },
    "green-keyword": {
        "name": "荧光绿重点",
        "description": "白字、绿色关键词、黑色轮廓",
    },
    "orange-black-impact": {
        "name": "橙黑冲击",
        "description": "橙色主标题、白色重点句",
    },
    "purple-yellow-outline": {
        "name": "紫黄双描边",
        "description": "紫色内描边、白色外轮廓",
    },
    "offset-shadow": {
        "name": "黑白错位",
        "description": "白字、黑色错位硬阴影",
    },
    "gold-kaiti": {
        "name": "金色楷体",
        "description": "金色楷体、深色描边",
    },
    "vertical-kaiti": {
        "name": "竖排楷体",
        "description": "双列竖排、白金配色",
    },
}


# The values below are the 1080 x 1920 research templates scaled to the
# 720 x 1280 render canvas used by the current video pipeline.
_TEMPLATE_STYLES = {
    "bold-yellow-white": {
        "alignment": "left",
        "fill": "#FFFFFF",
        "keyword_fill": "#FFD400",
        "stroke": "#111111",
        "stroke_width": 7,
        "shadow": ("#111111", 7, 9),
        "sizes": (87, 69),
        "title_box": (56, 287, 608, 347),
        "max_chars": 14,
        "highlight": "last_line",
    },
    "red-white-emphasis": {
        "alignment": "center",
        "fill": "#FFFFFF",
        "keyword_fill": "#FF3B30",
        "stroke": "#111111",
        "stroke_width": 7,
        "shadow": ("#111111", 5, 8),
        "sizes": (97, 79),
        "title_box": (47, 287, 627, 373),
        "max_chars": 10,
        "highlight": "last_line",
    },
    "black-white-clean": {
        "alignment": "left",
        "fill": "#FFFFFF",
        "keyword_fill": "#FFFFFF",
        "stroke": "#111111",
        "stroke_width": 9,
        "shadow": ("#FFFFFF", 0, 0),
        "sizes": (70, 70),
        "title_box": (56, 293, 608, 347),
        "max_chars": 15,
        "highlight": "none",
        "line_gap": 15,
    },
    "blue-white-clear": {
        "alignment": "center",
        "fill": "#FFFFFF",
        "keyword_fill": "#35B8FF",
        "stroke": "#08253F",
        "stroke_width": 8,
        "shadow": ("#08253F", 6, 9),
        "sizes": (88, 80),
        "title_box": (47, 287, 627, 373),
        "max_chars": 12,
        "highlight": "number_or_first_line",
    },
    "green-keyword": {
        "alignment": "left",
        "fill": "#FFFFFF",
        "keyword_fill": "#58E36D",
        "stroke": "#101514",
        "stroke_width": 7,
        "shadow": ("#101514", 5, 8),
        "sizes": (72, 77),
        "title_box": (56, 287, 608, 360),
        "max_chars": 14,
        "highlight": "first_line_tail",
    },
    "orange-black-impact": {
        "alignment": "left",
        "fill": "#FF7A22",
        "keyword_fill": "#FFFFFF",
        "stroke": "#17110D",
        "stroke_width": 8,
        "shadow": ("#17110D", 7, 9),
        "sizes": (87, 64),
        "title_box": (56, 287, 608, 373),
        "max_chars": 15,
        "highlight": "last_line",
    },
    "purple-yellow-outline": {
        "alignment": "center",
        "fill": "#FFFFFF",
        "keyword_fill": "#FFE65A",
        "stroke": "#4D267F",
        "stroke_width": 10,
        "outer_stroke": ("#FFFFFF", 3),
        "shadow": ("#25123E", 6, 9),
        "sizes": (71, 63),
        "title_box": (47, 280, 627, 387),
        "max_chars": 15,
        "highlight": "first_line_tail",
    },
    "offset-shadow": {
        "alignment": "center",
        "fill": "#FFFFFF",
        "keyword_fill": "#FFFFFF",
        "stroke": "#111111",
        "stroke_width": 5,
        "shadow": ("#111111", 12, 13),
        "sizes": (83, 97),
        "title_box": (47, 293, 627, 360),
        "max_chars": 11,
        "highlight": "none",
    },
    "gold-kaiti": {
        "alignment": "center",
        "fill": "#E7C36A",
        "keyword_fill": "#FFF3C4",
        "stroke": "#182A35",
        "stroke_width": 6,
        "shadow": ("#182A35", 5, 7),
        "sizes": (81, 68),
        "title_box": (47, 287, 627, 373),
        "max_chars": 14,
        "highlight": "last_line_tail",
        "font_kind": "kai",
    },
    "vertical-kaiti": {
        "alignment": "vertical_center",
        "fill": "#FFFFFF",
        "keyword_fill": "#D9B45B",
        "stroke": "#17241F",
        "stroke_width": 5,
        "shadow": ("#17241F", 5, 7),
        "sizes": (77, 77),
        "title_box": (173, 247, 373, 600),
        "max_chars": 9,
        "highlight": "last_column_tail",
        "font_kind": "kai",
    },
}


def _font_candidates(font_kind: str = "bold") -> list[Path]:
    if font_kind == "kai":
        return [
            Path("C:/Windows/Fonts/STKAITI.TTF"),
            Path("C:/Windows/Fonts/simkai.ttf"),
            Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"),
        ]
    return [
        Path("C:/Windows/Fonts/msyhbd.ttc"),
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]


def _load_font(size: int, font_kind: str = "bold") -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _font_candidates(font_kind):
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _clean_text(value: str) -> str:
    text = re.sub(r"[\t\r ]+", "", value or "").strip()
    text = re.sub(r"\n+", "\n", text)
    return text


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    left, _, right, _ = draw.textbbox((0, 0), text, font=font)
    return right - left


def _balanced_lines(value: str, max_chars: int) -> list[str]:
    text = _clean_text(value).replace("\n", "")
    text = re.sub(r"^[，。！？、；：,.!?;:]+|[，。！？、；：,.!?;:]+$", "", text)
    text = text[:max_chars]
    if not text:
        return ["视频标题"]
    if len(text) <= 6:
        return [text]

    ideal = math.ceil(len(text) / 2)
    punctuation = "，。！？、；：,.!?;:"
    candidates = [index + 1 for index, char in enumerate(text[:-1]) if char in punctuation]
    split_at = min(candidates, key=lambda index: abs(index - ideal)) if candidates else ideal
    first = text[:split_at].strip(punctuation)
    second = text[split_at:].strip(punctuation)
    return [line for line in (first, second) if line]


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    desired_size: int,
    max_width: int,
    font_kind: str,
) -> ImageFont.ImageFont:
    size = desired_size
    while size > 38:
        font = _load_font(size, font_kind)
        if _text_width(draw, text, font) <= max_width:
            return font
        size -= 2
    return _load_font(size, font_kind)


def _highlight_text(template_id: str, lines: list[str]) -> str:
    style = _TEMPLATE_STYLES[template_id]
    mode = style["highlight"]
    if mode == "none":
        return ""
    if mode == "last_line":
        return lines[-1]
    if mode == "number_or_first_line":
        number = re.search(r"\d+[个条种步招点项]?", "".join(lines))
        return number.group(0) if number else lines[0]
    if mode == "first_line_tail":
        return lines[0][-min(3, len(lines[0])) :]
    if mode in {"last_line_tail", "last_column_tail"}:
        return lines[-1][-min(2, len(lines[-1])) :]
    return ""


def _split_highlight(line: str, keyword: str) -> list[tuple[str, bool]]:
    if not keyword or keyword not in line:
        return [(line, False)]
    before, after = line.split(keyword, 1)
    parts: list[tuple[str, bool]] = []
    if before:
        parts.append((before, False))
    parts.append((keyword, True))
    if after:
        parts.append((after, False))
    return parts


def _draw_effect_line(
    overlay: Image.Image,
    template_id: str,
    line: str,
    keyword: str,
    *,
    y: int,
    desired_size: int,
    left: int,
    width: int,
) -> int:
    style = _TEMPLATE_STYLES[template_id]
    draw = ImageDraw.Draw(overlay)
    font_kind = style.get("font_kind", "bold")
    font = _fit_font(draw, line, desired_size, width, font_kind)
    parts = _split_highlight(line, keyword)
    widths = [_text_width(draw, value, font) for value, _ in parts]
    total_width = sum(widths)
    x = left if style["alignment"] == "left" else left + (width - total_width) // 2
    stroke_width = style["stroke_width"]
    shadow_color, shadow_x, shadow_y = style["shadow"]

    for (value, highlighted), part_width in zip(parts, widths):
        fill = style["keyword_fill"] if highlighted else style["fill"]
        if shadow_x or shadow_y:
            draw.text(
                (x + shadow_x, y + shadow_y),
                value,
                font=font,
                fill=shadow_color,
                stroke_width=stroke_width,
                stroke_fill=shadow_color,
            )
        outer = style.get("outer_stroke")
        if outer:
            outer_color, outer_width = outer
            draw.text(
                (x, y),
                value,
                font=font,
                fill=fill,
                stroke_width=stroke_width + outer_width,
                stroke_fill=outer_color,
            )
        draw.text(
            (x, y),
            value,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=style["stroke"],
        )
        x += part_width

    box = draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width)
    return box[3] - box[1]


def _draw_horizontal_template(overlay: Image.Image, template_id: str, title: str) -> None:
    style = _TEMPLATE_STYLES[template_id]
    left, top, width, _ = style["title_box"]
    lines = _balanced_lines(title, style["max_chars"])
    keyword = _highlight_text(template_id, lines)
    sizes = style["sizes"]
    line_gap = style.get("line_gap", 23)
    y = top
    for index, line in enumerate(lines):
        desired_size = sizes[min(index, len(sizes) - 1)]
        line_height = _draw_effect_line(
            overlay,
            template_id,
            line,
            keyword,
            y=y,
            desired_size=desired_size,
            left=left,
            width=width,
        )
        y += line_height + line_gap


def _draw_vertical_template(overlay: Image.Image, template_id: str, title: str) -> None:
    style = _TEMPLATE_STYLES[template_id]
    text = _clean_text(title).replace("\n", "")[: style["max_chars"]] or "视频标题"
    split_at = min(2, max(1, len(text) // 2))
    columns = [text[:split_at], text[split_at:]]
    columns = [column for column in columns if column]
    keyword = _highlight_text(template_id, columns)
    draw = ImageDraw.Draw(overlay)
    font = _load_font(style["sizes"][0], "kai")
    stroke_width = style["stroke_width"]
    shadow_color, shadow_x, shadow_y = style["shadow"]
    column_x = [413, 293]

    for column_index, column in enumerate(columns):
        x = column_x[column_index]
        y = 287 if column_index == 0 else 340
        for char in column:
            fill = style["keyword_fill"] if char in keyword else style["fill"]
            draw.text(
                (x + shadow_x, y + shadow_y),
                char,
                font=font,
                fill=shadow_color,
                stroke_width=stroke_width,
                stroke_fill=shadow_color,
            )
            draw.text(
                (x, y),
                char,
                font=font,
                fill=fill,
                stroke_width=stroke_width,
                stroke_fill=style["stroke"],
            )
            y += 88


def _cover_background(background_image_path: Path | None) -> Image.Image:
    if background_image_path and background_image_path.exists():
        try:
            with Image.open(background_image_path) as source:
                image = ImageOps.fit(
                    source.convert("RGBA"),
                    COVER_SIZE,
                    Image.Resampling.LANCZOS,
                )
            return image
        except Exception:
            pass
    return Image.new("RGBA", COVER_SIZE, (0, 0, 0, 0))


def generate_cover_png(
    title: str,
    script: str,
    output_path: Path,
    *,
    background_image_path: Path | None = None,
    template_id: str = DEFAULT_COVER_TEMPLATE,
) -> Path:
    template_id = template_id if template_id in COVER_TEMPLATES else DEFAULT_COVER_TEMPLATE
    title_source = _clean_text(title) or _clean_text(script)[:32] or "视频标题"
    overlay = Image.new("RGBA", COVER_SIZE, (0, 0, 0, 0))
    if _TEMPLATE_STYLES[template_id]["alignment"] == "vertical_center":
        _draw_vertical_template(overlay, template_id, title_source)
    else:
        _draw_horizontal_template(overlay, template_id, title_source)

    image = Image.alpha_composite(_cover_background(background_image_path), overlay)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "PNG", optimize=True)
    return output_path


def extract_first_frame_cover_png(video_path: Path, output_path: Path) -> Path:
    from .renderer import _ffmpeg_executable

    ffmpeg = _ffmpeg_executable()
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required to extract video cover")
    if not video_path.exists():
        raise FileNotFoundError(video_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-update",
        "1",
        str(output_path),
    ]
    subprocess.run(command, check=True, capture_output=True)
    return output_path
