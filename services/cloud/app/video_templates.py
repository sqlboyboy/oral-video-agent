from __future__ import annotations

from copy import deepcopy
from typing import Any


VIDEO_TEMPLATE_CATALOG_VERSION = "2026.07.15.1"
DEFAULT_COVER_TEMPLATE = "bold-yellow-white"
DEFAULT_SUBTITLE_TEMPLATE = "renovation_pitfall_yellow"


COVER_TEMPLATES: dict[str, dict[str, Any]] = {
    "bold-yellow-white": {
        "name": "黄白重磅",
        "description": "白字、黄色重点、粗黑描边",
        "preview_copy": ["爆款标题", "这样写"],
        "style": {
            "alignment": "left",
            "fill": "#FFFFFF",
            "keyword_fill": "#FFD400",
            "stroke": "#111111",
            "stroke_width": 7,
            "shadow": {"color": "#111111", "x": 7, "y": 9},
            "font_sizes": [87, 69],
            "title_box": [56, 287, 608, 347],
            "max_chars": 14,
            "highlight": "last_line",
        },
    },
    "red-white-emphasis": {
        "name": "红白强调",
        "description": "白字、红色重点、粗黑描边",
        "preview_copy": ["别再这样做", "正确方法"],
        "style": {
            "alignment": "center",
            "fill": "#FFFFFF",
            "keyword_fill": "#FF3B30",
            "stroke": "#111111",
            "stroke_width": 7,
            "shadow": {"color": "#111111", "x": 5, "y": 8},
            "font_sizes": [97, 79],
            "title_box": [47, 287, 627, 373],
            "max_chars": 10,
            "highlight": "last_line",
        },
    },
    "black-white-clean": {
        "name": "黑白极简",
        "description": "纯白粗体、加重黑描边",
        "preview_copy": ["真正的高手", "都很简单"],
        "style": {
            "alignment": "left",
            "fill": "#FFFFFF",
            "keyword_fill": "#FFFFFF",
            "stroke": "#111111",
            "stroke_width": 9,
            "shadow": {"color": "#FFFFFF", "x": 0, "y": 0},
            "font_sizes": [70, 70],
            "title_box": [56, 293, 608, 347],
            "max_chars": 15,
            "highlight": "none",
            "line_gap": 15,
        },
    },
    "blue-white-clear": {
        "name": "蓝白清晰",
        "description": "蓝色数字或方法词、深蓝描边",
        "preview_copy": ["3个方法", "立刻学会"],
        "style": {
            "alignment": "center",
            "fill": "#FFFFFF",
            "keyword_fill": "#35B8FF",
            "stroke": "#08253F",
            "stroke_width": 8,
            "shadow": {"color": "#08253F", "x": 6, "y": 9},
            "font_sizes": [88, 80],
            "title_box": [47, 287, 627, 373],
            "max_chars": 12,
            "highlight": "number_or_first_line",
        },
    },
    "green-keyword": {
        "name": "荧光绿重点",
        "description": "白字、绿色关键词、黑色轮廓",
        "preview_copy": ["抓住重点", "效率翻倍"],
        "style": {
            "alignment": "left",
            "fill": "#FFFFFF",
            "keyword_fill": "#58E36D",
            "stroke": "#101514",
            "stroke_width": 7,
            "shadow": {"color": "#101514", "x": 5, "y": 8},
            "font_sizes": [72, 77],
            "title_box": [56, 287, 608, 360],
            "max_chars": 14,
            "highlight": "first_line_tail",
        },
    },
    "orange-black-impact": {
        "name": "橙黑冲击",
        "description": "橙色主标题、白色重点句",
        "preview_copy": ["生意增长", "关键一步"],
        "style": {
            "alignment": "left",
            "fill": "#FF7A22",
            "keyword_fill": "#FFFFFF",
            "stroke": "#17110D",
            "stroke_width": 8,
            "shadow": {"color": "#17110D", "x": 7, "y": 9},
            "font_sizes": [87, 64],
            "title_box": [56, 287, 608, 373],
            "max_chars": 15,
            "highlight": "last_line",
        },
    },
    "purple-yellow-outline": {
        "name": "紫黄双描边",
        "description": "紫色内描边、白色外轮廓",
        "preview_copy": ["流量密码", "马上告诉你"],
        "style": {
            "alignment": "center",
            "fill": "#FFFFFF",
            "keyword_fill": "#FFE65A",
            "stroke": "#4D267F",
            "stroke_width": 10,
            "outer_stroke": {"color": "#FFFFFF", "width": 3},
            "shadow": {"color": "#25123E", "x": 6, "y": 9},
            "font_sizes": [71, 63],
            "title_box": [47, 280, 627, 387],
            "max_chars": 15,
            "highlight": "first_line_tail",
        },
    },
    "offset-shadow": {
        "name": "黑白错位",
        "description": "白字、黑色错位硬阴影",
        "preview_copy": ["你以为", "其实不是"],
        "style": {
            "alignment": "center",
            "fill": "#FFFFFF",
            "keyword_fill": "#FFFFFF",
            "stroke": "#111111",
            "stroke_width": 5,
            "shadow": {"color": "#111111", "x": 12, "y": 13},
            "font_sizes": [83, 97],
            "title_box": [47, 293, 627, 360],
            "max_chars": 11,
            "highlight": "none",
        },
    },
    "gold-kaiti": {
        "name": "金色楷体",
        "description": "金色楷体、深色描边",
        "preview_copy": ["东方智慧", "尽在其中"],
        "style": {
            "alignment": "center",
            "fill": "#E7C36A",
            "keyword_fill": "#FFF3C4",
            "stroke": "#182A35",
            "stroke_width": 6,
            "shadow": {"color": "#182A35", "x": 5, "y": 7},
            "font_sizes": [81, 68],
            "title_box": [47, 287, 627, 373],
            "max_chars": 14,
            "highlight": "last_line_tail",
            "font_kind": "kai",
        },
    },
    "vertical-kaiti": {
        "name": "竖排楷体",
        "description": "双列竖排、白金配色",
        "preview_copy": ["答案", "藏在细节"],
        "style": {
            "alignment": "vertical_center",
            "fill": "#FFFFFF",
            "keyword_fill": "#D9B45B",
            "stroke": "#17241F",
            "stroke_width": 5,
            "shadow": {"color": "#17241F", "x": 5, "y": 7},
            "font_sizes": [77, 77],
            "title_box": [173, 247, 373, 600],
            "max_chars": 9,
            "highlight": "last_column_tail",
            "font_kind": "kai",
        },
    },
}


SUBTITLE_TEMPLATES: dict[str, dict[str, Any]] = {
    "renovation_pitfall_yellow": {
        "name": "装修·避坑警示黄",
        "industry": "装修",
        "description": "强钩子、避坑清单、预算警示",
        "preview_copy": ["这3个装修坑", "千万别踩"],
        "style": {"font_size": 64, "color": "#FFFFFF", "keyword_color": "#FFE23B", "outline_color": "#111111", "outline_width": 5, "font_family": "Microsoft YaHei", "position": "bottom", "margin_v": 390, "max_chars_per_line": 9},
    },
    "renovation_editorial_gray": {
        "name": "装修·设计高级灰",
        "industry": "装修",
        "description": "设计理念、案例讲解、高客单审美",
        "preview_copy": ["高级感不靠堆钱", "靠的是细节"],
        "style": {"font_size": 54, "color": "#F7F3EA", "keyword_color": "#D8895B", "outline_color": "#232323", "outline_width": 2, "font_family": "Microsoft YaHei UI", "position": "bottom", "margin_v": 360, "max_chars_per_line": 10},
    },
    "renovation_inspection_blueprint": {
        "name": "装修·工地验收蓝",
        "industry": "装修",
        "description": "工艺标准、验收步骤、材料参数",
        "preview_copy": ["水电验收", "先看这4点"],
        "style": {"font_size": 60, "color": "#FFFFFF", "keyword_color": "#43B8FF", "outline_color": "#0B2239", "outline_width": 4, "font_family": "SimHei", "position": "bottom", "margin_v": 380, "max_chars_per_line": 9},
    },
    "restaurant_owner_billboard": {
        "name": "餐饮·老板大字报",
        "industry": "餐饮",
        "description": "老板观点、经营反差、加盟避坑",
        "preview_copy": ["菜品好吃", "不等于生意好"],
        "style": {"font_size": 68, "color": "#FFD82E", "keyword_color": "#FFFFFF", "outline_color": "#16100A", "outline_width": 6, "font_family": "SimHei", "position": "middle", "margin_v": 0, "max_chars_per_line": 8},
    },
    "restaurant_price_tag_red": {
        "name": "餐饮·红火价签",
        "industry": "餐饮",
        "description": "团购价格、午市套餐、限时活动",
        "preview_copy": ["工作日午市", "只要29.9元"],
        "style": {"font_size": 58, "color": "#FFFFFF", "keyword_color": "#FFE873", "outline_color": "#6E130F", "outline_width": 2, "font_family": "Microsoft YaHei", "position": "bottom", "margin_v": 370, "max_chars_per_line": 9},
    },
    "restaurant_wok_fire_warm": {
        "name": "餐饮·烟火探店暖白",
        "industry": "餐饮",
        "description": "后厨实拍、老店故事、菜品工艺",
        "preview_copy": ["这口锅气", "才是老店灵魂"],
        "style": {"font_size": 56, "color": "#FFF8E7", "keyword_color": "#FFB547", "outline_color": "#27160D", "outline_width": 4, "font_family": "Microsoft YaHei UI", "position": "bottom", "margin_v": 400, "max_chars_per_line": 9},
    },
    "training_key_conclusion": {
        "name": "培训·重点结论黄",
        "industry": "培训",
        "description": "家庭教育、方法论、反常识结论",
        "preview_copy": ["孩子学不会", "往往不是不努力"],
        "style": {"font_size": 60, "color": "#FFFFFF", "keyword_color": "#FFE042", "outline_color": "#111111", "outline_width": 5, "font_family": "Microsoft YaHei", "position": "bottom", "margin_v": 380, "max_chars_per_line": 10},
    },
    "training_framework_blue": {
        "name": "培训·知识框架蓝",
        "industry": "培训",
        "description": "课程知识点、教师 IP、学习规划",
        "preview_copy": ["提分关键", "是建立知识框架"],
        "style": {"font_size": 54, "color": "#F8FBFF", "keyword_color": "#59BFFF", "outline_color": "#0F2841", "outline_width": 3, "font_family": "Microsoft YaHei UI", "position": "bottom", "margin_v": 360, "max_chars_per_line": 10},
    },
    "sinology_ink_gold": {
        "name": "国学·墨韵雅金",
        "industry": "国学",
        "description": "经典解读、修身智慧、中式美学",
        "preview_copy": ["心若安定", "万事从容"],
        "style": {"font_size": 58, "color": "#F6E7C7", "keyword_color": "#D9B45B", "outline_color": "#1A1712", "outline_width": 2, "font_family": "SimSun", "position": "bottom", "margin_v": 390, "max_chars_per_line": 8},
    },
    "sinology_minimal_vermilion": {
        "name": "国学·留白朱砂",
        "industry": "国学",
        "description": "短句箴言、人物故事、情绪疗愈",
        "preview_copy": ["知止不殆", "可以长久"],
        "style": {"font_size": 54, "color": "#F8F1E2", "keyword_color": "#B6382B", "outline_color": "#241F19", "outline_width": 1, "font_family": "KaiTi", "position": "bottom", "margin_v": 420, "max_chars_per_line": 8},
    },
}


def _catalog_items(templates: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"id": template_id, **deepcopy(template)} for template_id, template in templates.items()]


def video_template_catalog() -> dict[str, Any]:
    return {
        "version": VIDEO_TEMPLATE_CATALOG_VERSION,
        "cover_render_mode": "transparent_text_on_first_frame",
        "cover_design_size": [720, 1280],
        "subtitle_design_size": [1080, 1920],
        "default_cover_template_id": DEFAULT_COVER_TEMPLATE,
        "default_subtitle_template_id": DEFAULT_SUBTITLE_TEMPLATE,
        "cover_templates": _catalog_items(COVER_TEMPLATES),
        "subtitle_templates": _catalog_items(SUBTITLE_TEMPLATES),
    }


def resolve_render_template_payload(payload: dict[str, Any]) -> dict[str, Any]:
    resolved = deepcopy(payload)
    resolved.pop("cover_template", None)
    resolved["template_catalog_version"] = VIDEO_TEMPLATE_CATALOG_VERSION

    cover_id = str(resolved.get("cover_template_id") or "").strip()
    if cover_id:
        cover = COVER_TEMPLATES.get(cover_id)
        if cover is None:
            raise ValueError("unknown cover template")
        resolved["cover_template_id"] = cover_id
        resolved["cover_template"] = deepcopy(cover)

    supplied_style = dict(resolved.get("subtitle_style") or {})
    subtitle_id = str(
        resolved.get("subtitle_template_id")
        or supplied_style.get("template_id")
        or ""
    ).strip()
    if subtitle_id and subtitle_id != "custom":
        subtitle = SUBTITLE_TEMPLATES.get(subtitle_id)
        if subtitle is None:
            raise ValueError("unknown subtitle template")
        style = deepcopy(subtitle["style"])
        style.update({key: value for key, value in supplied_style.items() if value is not None})
        style["template_id"] = subtitle_id
        style["design_width"] = 1080
        style["design_height"] = 1920
        resolved["subtitle_template_id"] = subtitle_id
        resolved["subtitle_style"] = style
    elif supplied_style:
        resolved["subtitle_style"] = supplied_style
    return resolved
