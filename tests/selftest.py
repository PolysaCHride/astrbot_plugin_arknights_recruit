"""离线自测：不装 AstrBot 也能跑，验证词条解析、时长规则、计算与版面。

    python tests/selftest.py

依赖：jinja2（仅用于把模板渲染成 HTML 做检查）。计算部分只用到标准库。
"""

import os
import sys
import tempfile
import types

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PLUGIN)

# ---- astrbot 桩：core.data 需要 astrbot.api.logger ----
astrbot = types.ModuleType("astrbot")
api = types.ModuleType("astrbot.api")


class _Logger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


api.logger = _Logger()
api.AstrBotConfig = dict
astrbot.api = api
sys.modules["astrbot"] = astrbot
sys.modules["astrbot.api"] = api

from core import image_view  # noqa: E402
from core.calculator import (  # noqa: E402
    calculate,
    format_time,
    parse_time,
    rarity_bounds,
    time_label,
)
from core.data import RecruitData  # noqa: E402
from core.image_view import build_layout, template_path  # noqa: E402
from core.tags import TAGS, resolve_all  # noqa: E402
from core.text_view import render_chunks  # noqa: E402

TMP = tempfile.mkdtemp(prefix="gz_selftest_")
data = RecruitData(os.path.join(PLUGIN, "data", "recruit_operators.json"), TMP)
assert len(data.operators) == 160, len(data.operators)
assert len(TAGS) == 29
print(f"数据源={data.source} 干员数={len(data.operators)} 词条数={len(TAGS)}")


def names(combo):
    return [op.name for op in combo.operators]


def calc(tags, minutes=None):
    matched, failures = resolve_all(tags)
    assert not failures, (tags, failures)
    return matched, calculate(matched, data.operators, minutes)


print("\n### 时长解析")
for value, expect in [
    ("all", None), ("ALL", None), ("", None), ("abc", None), ("不限", None),
    ("9:00", 540), ("9:00:00", 540), ("540", 540), ("1:00", 60), ("3:50", 230),
    ("4:00", 240), ("7:40", 460), ("10:00", 540), ("0:01", 10),
]:
    minutes = parse_time(value)
    assert minutes == expect, (value, minutes, expect)
    print(f"   {value!r:10s} -> {format_time(minutes):8s} 星级区间={rarity_bounds(minutes)} "
          f"标签={time_label(minutes)}")

print("\n### 词条别名解析")
for case, expect in [
    (["高姿", "输出"], ["高级资深干员", "输出"]),
    (["高资", "回费"], ["高级资深干员", "费用回复"]),
    (["防御", "支援器械"], ["防护", "支援机械"]),
    (["近战", "远程"], ["近战位", "远程位"]),
    (["近卫", "狙击"], ["近卫干员", "狙击干员"]),
    (["资深"], ["资深干员"]),
    (["快速"], ["快速复活"]),
    (["支援"], ["支援"]),
]:
    matched, failures = resolve_all(case)
    assert matched == expect and not failures, (case, matched, failures)
    print(f"   {str(case):26s} -> {matched}")

for case in (["高薪"], ["干员"]):
    matched, failures = resolve_all(case)
    assert failures, case
    print(f"   {str(case):26s} -> 报错 {[(r, c[:2]) for r, c in failures]}")

print("\n### 默认（不限时长）：所有时长可能出现的干员")
matched, res = calc(["支援"])
assert len(res.combos) == 1 and res.minutes is None
combo = res.combos[0]
assert combo.star_span == "1★~5★", combo.star_span
assert set(names(combo)) == {
    "杜宾", "清流", "诗怀雅", "白面鸮", "华法琳", "凛冬", "极境", "月禾",
    "Castle-3", "正义骑士号",
}, sorted(names(combo))
assert combo.guarantee == 1 and combo.ceiling == 5
print(f"   支援 -> {combo.star_span} {len(combo.operators)} 人（含 1★ 机械）")

for tag, span, count in (
    ("支援机械", "1★", 8),
    ("新手", "2★", 5),
    ("元素", "1★", 1),
    ("高级资深干员", "6★", 35),
):
    _, r = calc([tag])
    assert not r.empty, tag
    assert r.combos[0].star_span == span, (tag, r.combos[0].star_span)
    assert len(r.combos[0].operators) == count, (tag, len(r.combos[0].operators))
    print(f"   {tag:8s} -> {span:9s} {count} 人")

_, r = calc(["输出"])
assert r.combos[0].guarantee == 3, r.combos[0].guarantee  # 没有 1★/2★ 带"输出"
print(f"   输出 -> {r.combos[0].star_span}（1★/2★ 里没有带输出的干员）")

_, r = calc(["支援", "输出", "近战位"])
assert len(r.combos) == 7, len(r.combos)
assert all(op.rarity >= 1 for c in r.combos for op in c.operators)
print(f"   支援 输出 近战位 -> {len(r.combos)} 个组合")

print("\n### 指定时长：按星级区间裁剪")
for value, tag, expect in (
    ("9:00", "支援", (4, 5, 8)),
    ("9:00", "高级资深干员", (6, 6, 35)),
    ("9:00", "近战位", (3, 5, 57)),
    ("1:00", "支援机械", (1, 1, 8)),
    ("1:00", "支援", (1, 4, 4)),  # 1★~4★，5★ 的凛冬/极境等被挡掉
    ("4:00", "支援", (4, 5, 8)),  # 2★~5★，1★ 机械被挡掉
):
    minutes = parse_time(value)
    _, r = calc([tag], minutes)
    combo = r.combos[0]
    assert (combo.guarantee, combo.ceiling, len(combo.operators)) == expect, (
        value, tag, combo.guarantee, combo.ceiling, len(combo.operators),
    )
    print(f"   {value} {tag:8s} -> {combo.star_span:9s} {len(combo.operators)} 人")

for tag in ("新手", "支援机械", "元素"):
    _, r = calc([tag], 540)
    assert r.empty and r.filtered_out, tag
    print(f"   9:00 {tag} -> 无结果（{r.filtered_out[0].rarities}）")

print("\n### 文本输出")
matched, res = calc(["支援", "输出", "近战位"])
chunks = render_chunks(matched, res.combos, 1200, time_label(res.minutes))
assert chunks[0].startswith("📋 公开招募 · 计算结果")
assert "· 不限时长" in chunks[0]
assert "★5：诗怀雅" in chunks[0] and "1. 支援 + 输出 + 近战位" in chunks[0]
assert "保底" not in chunks[0] and "💡" not in chunks[0]
print(f"   {len(chunks)} 条消息，首条 {len(chunks[0])} 字")

print("\n### 图片版面自洽性")
for case in (["支援机械"], ["支援", "输出", "近战位"], ["高级资深干员", "输出", "近战位"],
             ["近战位", "输出", "生存", "防护", "群攻"]):
    matched, result = calc(case)
    for show_star in (False, True):
        layout = build_layout(matched, result.combos, show_star, time_label(result.minutes))
        tdata = layout.data
        assert tdata["show_star"] is show_star
        assert len(tdata["cards"]) == len(result.combos)
        expect = (
            2 * image_view.PAD
            + tdata["head_h"]
            + sum(c["height"] for c in tdata["cards"])
            + (len(tdata["cards"]) - 1) * image_view.CARD_GAP
        )
        assert expect == layout.height, (show_star, expect, layout.height)
        assert tdata["width"] == layout.width
        # 卡片宽度自洽：色条 + 内边距 + 内容宽
        assert tdata["card_w"] == (
            image_view.BAR_W + 2 * image_view.CARD_PAD_X + tdata["inner_w"]
        )
        # 每行至少一个干员；行宽落在内容宽内（与折行函数同一套估算）
        lines = [line for c in tdata["cards"] for line in c["op_lines"]]
        assert all(len(line) for line in lines)
        for line in lines:
            used = 0.0
            for op in line:
                used += (
                    image_view.text_width(op["name"], image_view.CHIP_FONT)
                    + (image_view._star_width(op["rarity"]) + 3 if show_star else 0)
                    + 2 * image_view.CHIP_PAD_X
                    + 2
                    + image_view.CHIP_GAP
                )
            assert used <= tdata["inner_w"], (show_star, used, tdata["inner_w"])
        # 徽章必须放得下
        assert all(
            image_view.text_width(c["span"], image_view.BADGE_FONT)
            + 2 * image_view.BADGE_PAD_X
            <= tdata["badge_w"]
            for c in tdata["cards"]
        )
    layout = build_layout(matched, result.combos, False, time_label(result.minutes))
    spans = [c["span"] for c in layout.data["cards"]]
    print(f"   {' '.join(matched):28s} 组合={len(result.combos):2d} "
          f"图片={layout.width}x{layout.height}px 区间={spans[:4]}")

print("\n### 模板渲染")
try:
    from jinja2 import Environment
except ImportError:
    print("   跳过（未安装 jinja2）")
else:
    env = Environment(autoescape=True)
    tmpl = env.from_string(open(template_path(), encoding="utf-8").read())
    matched, result = calc(["支援", "输出", "近战位"])
    for show_star in (False, True):
        layout = build_layout(matched, result.combos, show_star, time_label(result.minutes))
        html = tmpl.render(**layout.data)
        assert "{{" not in html and "{%" not in html
        assert html.count('class="dc"') == len(result.combos)
        assert "不限时长" in html
        assert ("<em>★" in html) is show_star
        out = os.path.join(TMP, f"preview-{'star' if show_star else 'plain'}.html")
        with open(out, "w", encoding="utf-8") as fp:
            fp.write(html)
        print(f"   show_star={str(show_star):5s} -> {out}")

print("\n全部自测通过 ✓")
