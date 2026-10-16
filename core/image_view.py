"""图片形式的计算结果（卡片版式）。

渲染走 AstrBot 的 ``html_render``（服务端 Jinja2 + Playwright 截图）。由于文转图
服务只能整页截图，这里在 Python 侧把版面算好：卡片宽度、每张卡片占几行、整图总
宽总高，然后通过 ``clip`` 精确裁切，做到"干员多就画大、干员少就画小"。

字体宽度按经验值估算（CJK 记 1em，其余记 0.75em），一律向上取整——估宽只会让
换行更早、行数更多，版面依然自洽；估窄才会溢出。
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Sequence

from .calculator import Combo
from .data import Operator

# 星级配色，与模板 CSS 中的 .r1~.r6 保持一致
RARITY_COLORS: dict[int, str] = {
    1: "#98a2b3",
    2: "#3fbf7f",
    3: "#4a9be8",
    4: "#9b6fe0",
    5: "#dfae2b",
    6: "#ef7d2b",
}

# --- 版式常量，必须与 render/recruit/card.html 中的 CSS 保持一致 ---
PAD = 16
CARD_GAP = 8
BAR_W = 4
CARD_PAD_X = 12
CARD_PAD_Y = 10
HEAD_LINE_H = 20
OPS_GAP_TOP = 8
CHIP_H = 21
CHIP_GAP = 6
CHIP_PAD_X = 7
COMBO_FONT = 13
CHIP_FONT = 12
BADGE_FONT = 11
BADGE_PAD_X = 6
BADGE_GAP = 12
MIN_INNER, MAX_INNER = 250, 600

TITLE_H = 22
HEAD_GAP = 8
INPUT_CHIP_H = 22
HEAD_PAD_BOTTOM = 12
INPUT_FONT = 12
INPUT_CHIP_PAD = 8
CHIP_GAP_INPUT = 5

STAR_FONT = 11

_WIDE_RANGES = (
    (0x1100, 0x115F),
    (0x2600, 0x27BF),
    (0x2E80, 0xA4CF),
    (0xAC00, 0xD7A3),
    (0xF900, 0xFAFF),
    (0xFE30, 0xFE6F),
    (0xFF00, 0xFF60),
    (0xFFE0, 0xFFE6),
    (0x20000, 0x3FFFD),
)


def _is_wide(char: str) -> bool:
    code = ord(char)
    return any(low <= code <= high for low, high in _WIDE_RANGES)


def text_width(text: str, font_size: float) -> float:
    """估算一段文字的像素宽度，宁可高估。

    CJK 字形在等宽意义上是 1em，拉丁字母/数字在无衬线字体下不超过 0.75em。
    估宽只会让换行更早、行数更多，版面依然自洽；估窄才会让文字溢出列宽。
    """
    return sum(font_size if _is_wide(ch) else font_size * 0.75 for ch in text)


def _star_width(rarity: int) -> float:
    return text_width(f"★{rarity}", STAR_FONT) if rarity else 0.0


@dataclass
class Layout:
    width: int
    height: int
    data: dict = field(default_factory=dict)


# ---------------------------------------------------------------- 折行工具


def _wrap_combo(tags: Sequence[str], max_width: int) -> list[str]:
    """把 "A + B + C" 按 " + " 折行。"""
    lines: list[str] = []
    current = tags[0]
    for tag in tags[1:]:
        candidate = f"{current} + {tag}"
        if text_width(candidate, COMBO_FONT) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = tag
    lines.append(current)
    return lines


def _wrap_chips(
    operators: Sequence[Operator], max_width: int, show_star: bool
) -> list[list[dict]]:
    """干员做成带底色的小块，按行排布。"""
    lines: list[list[dict]] = []
    current: list[dict] = []
    used = 0.0
    for op in operators:
        width = (
            text_width(op.name, CHIP_FONT)
            + (_star_width(op.rarity) + 3 if show_star else 0)
            + 2 * CHIP_PAD_X
            + 2
            + CHIP_GAP
        )
        if current and used + width > max_width:
            lines.append(current)
            current, used = [], 0.0
        current.append({"name": op.name, "rarity": op.rarity})
        used += width
    if current:
        lines.append(current)
    return lines


def _wrap_input_chips(tags: Sequence[str], max_width: int) -> list[list[str]]:
    lines: list[list[str]] = []
    current: list[str] = []
    used = 0.0
    for tag in tags:
        width = text_width(tag, INPUT_FONT) + 2 * INPUT_CHIP_PAD + 2 + CHIP_GAP_INPUT
        if current and used + width > max_width:
            lines.append(current)
            current, used = [], 0.0
        current.append(tag)
        used += width
    if current:
        lines.append(current)
    return lines


# ---------------------------------------------------------------- 版面


def build_layout(
    selected: Sequence[str],
    combos: Sequence[Combo],
    show_star: bool = False,
    time_text: str = "",
) -> Layout:
    """算出整张图应该有多宽多高，以及内容怎么摆。"""
    spans = [combo.star_span for combo in combos]
    badge_w = math.ceil(max(text_width(span, BADGE_FONT) for span in spans)) + 2 * BADGE_PAD_X

    widest_pool = max(
        sum(
            text_width(op.name, CHIP_FONT)
            + (_star_width(op.rarity) + 3 if show_star else 0)
            + 2 * CHIP_PAD_X
            + 2
            + CHIP_GAP
            for op in combo.operators
        )
        for combo in combos
    )
    inner_w = math.ceil(min(max(MIN_INNER, widest_pool), MAX_INNER))

    # 标题行要同时放得下"词条组合"和星级徽章
    longest_combo = max(text_width(" + ".join(c.tags), COMBO_FONT) for c in combos)
    inner_w = math.ceil(
        min(max(inner_w, longest_combo + badge_w + BADGE_GAP), MAX_INNER)
    )

    card_w = BAR_W + 2 * CARD_PAD_X + inner_w
    width = card_w + 2 * PAD
    input_lines = _wrap_input_chips(selected, card_w)
    head_h = (
        TITLE_H
        + HEAD_GAP
        + len(input_lines) * INPUT_CHIP_H
        + (len(input_lines) - 1) * CHIP_GAP_INPUT
        + HEAD_PAD_BOTTOM
    )

    combo_max_w = inner_w - badge_w - BADGE_GAP
    cards = []
    for combo in combos:
        combo_lines = _wrap_combo(combo.tags, combo_max_w)
        op_lines = _wrap_chips(combo.operators, inner_w, show_star)
        op_area = len(op_lines) * CHIP_H + (len(op_lines) - 1) * CHIP_GAP
        cards.append(
            {
                "combo_lines": combo_lines,
                "span": combo.star_span,
                "op_lines": op_lines,
                "color": RARITY_COLORS[combo.guarantee],
                "height": 2 * CARD_PAD_Y
                + max(len(combo_lines), 1) * HEAD_LINE_H
                + OPS_GAP_TOP
                + op_area,
            }
        )

    height = (
        2 * PAD
        + head_h
        + sum(card["height"] for card in cards)
        + (len(cards) - 1) * CARD_GAP
    )
    return Layout(
        width=width,
        height=height,
        data={
            "width": width,
            "height": height,
            "pad": PAD,
            "inner_w": inner_w,
            "body_w": inner_w + 2 * CARD_PAD_X,
            "card_w": card_w,
            "card_gap": CARD_GAP,
            "bar_w": BAR_W,
            "card_pad_x": CARD_PAD_X,
            "card_pad_y": CARD_PAD_Y,
            "head_line_h": HEAD_LINE_H,
            "ops_gap_top": OPS_GAP_TOP,
            "chip_h": CHIP_H,
            "chip_gap": CHIP_GAP,
            "chip_pad_x": CHIP_PAD_X,
            "badge_w": badge_w,
            "badge_pad_x": BADGE_PAD_X,
            "head_h": head_h,
            "title_h": TITLE_H,
            "head_gap": HEAD_GAP,
            "input_chip_h": INPUT_CHIP_H,
            "input_chip_pad": INPUT_CHIP_PAD,
            "chip_gap_input": CHIP_GAP_INPUT,
            "show_star": show_star,
            "time_text": time_text,
            "input_lines": input_lines,
            "cards": cards,
        },
    )


def template_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "render",
        "recruit",
        "card.html",
    )


def build_render_options(layout: Layout, *, precise: bool = True) -> dict:
    """截图参数。``precise`` 时用 clip 精确裁到内容尺寸。"""
    options: dict = {"type": "png"}
    if precise:
        options["full_page"] = False
        options["clip"] = {
            "x": 0,
            "y": 0,
            "width": layout.width,
            "height": layout.height,
        }
    else:
        options["full_page"] = True
    return options
