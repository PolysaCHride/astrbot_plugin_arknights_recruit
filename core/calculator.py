"""公招计算核心。

两条游戏机制决定了这里的算法：

1. **词条是"与"关系**：招募结果必须同时满足所选的全部词条。若所选组合下不存在
   任何干员，游戏会随机丢弃其中部分词条再抽。因此和 PRTS 的计算器一样，这里枚举
   所选词条的所有非空子集，对每个子集求干员交集。
2. **时长决定星级上下限**：官方 gacha_table.recruitRarityTable 规定

   ===============  ==============
   时长              可出现星级
   ===============  ==============
   0:10 ~ 3:50       1★ ~ 4★
   4:00 ~ 7:30       2★ ~ 5★
   7:40 ~ 9:00       3★ ~ 5★
   ===============  ==============

   另外"高级资深干员"可以让结果突破上限直接出 6★，"资深干员"可出 5★
   （specialTagRarityTable）。这就是为什么 9:00 时单选"支援"的保底是 4★——
   1★ 的 Castle-3 根本不在池子里。

默认（``recruit_time = all``）不按时长裁剪，展示该组合在**任意时长下**可能出现
的全部干员，这样 1★ 机械、2★ 新手这类只在短时长出现的干员不会被藏起来。把
``recruit_time`` 设成具体时间则按上表裁剪到该时长可出的星级。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import combinations
from typing import Sequence

from .data import Operator

# 游戏内一次最多选择 5 个词条
MAX_TAGS = 5

# 招募时长的上下限（分钟），见 recruitConstants.maxRecruitTime
MIN_MINUTES = 10
MAX_MINUTES = 540

# 时长分段的边界（分钟）
_BOUND_2 = 240  # 4:00 起最低 2★
_BOUND_3 = 460  # 7:40 起最低 3★

# 这两个词条能让结果突破时长决定的星级上限
_RARITY_UNLOCK: dict[str, int] = {"高级资深干员": 6, "资深干员": 5}

# 不限时长：取所有时长可出星级的并集，也就是 1★~5★
UNLIMITED_RARITIES = frozenset({1, 2, 3, 4, 5})

_UNLIMITED_WORDS = frozenset({"all", "any", "*", "全部", "不限", "不限时长", "所有"})

_TIME_RE = re.compile(r"^\s*(?:(\d+)\s*[:：]\s*(\d+)(?:\s*[:：]\s*(\d+))?|(\d+))\s*$")


def parse_time(value: object) -> int | None:
    """把 ``"9:00"`` / ``"540"`` 解析成分钟，``"all"`` 解析成 ``None``（不限时长）。

    无法识别时回落到不限时长；数值超出范围时夹到 [10, 540]。
    """
    text = str(value).strip() if value is not None else ""
    if not text or text.lower() in _UNLIMITED_WORDS:
        return None

    match = _TIME_RE.match(text)
    if not match:
        return None

    if match.group(4) is not None:
        minutes = int(match.group(4))
    else:
        minutes = int(match.group(1)) * 60 + int(match.group(2))

    return max(MIN_MINUTES, min(MAX_MINUTES, minutes))


def format_time(minutes: int | None) -> str:
    if minutes is None:
        return "不限时长"
    return f"{minutes // 60}:{minutes % 60:02d}"


def time_label(minutes: int | None) -> str:
    """给输出用的时长说明。"""
    return "不限时长" if minutes is None else f"时长 {format_time(minutes)}"


def rarity_bounds(minutes: int | None) -> tuple[int, int]:
    """时长对应的星级区间（含两端，1-indexed）。``None`` 表示不限时长。"""
    if minutes is None:
        return 1, 5
    if minutes < _BOUND_2:
        return 1, 4
    if minutes < _BOUND_3:
        return 2, 5
    return 3, 5


def allowed_rarities(minutes: int | None, tags: Sequence[str]) -> frozenset[int]:
    """在给定时长下，这组词条能招到的星级集合。"""
    if minutes is None:
        allowed = set(UNLIMITED_RARITIES)
    else:
        low, high = rarity_bounds(minutes)
        allowed = set(range(low, high + 1))

    for tag, rarity in _RARITY_UNLOCK.items():
        if tag in tags:
            allowed.add(rarity)
    return frozenset(allowed)


@dataclass(frozen=True)
class Combo:
    """一个词条组合及其可能出现的干员。"""

    tags: tuple[str, ...]
    operators: tuple[Operator, ...]

    @property
    def guarantee(self) -> int:
        """保底星级 = 该组合干员池中的最低星级。"""
        return min(op.rarity for op in self.operators)

    @property
    def ceiling(self) -> int:
        """该组合池子里的最高星级。"""
        return max(op.rarity for op in self.operators)

    @property
    def star_span(self) -> str:
        """星级区间文本，如 ``1★~5★``；上下限相同时只显示一个。"""
        low, high = self.guarantee, self.ceiling
        return f"{low}★" if low == high else f"{low}★~{high}★"

    def by_star(self) -> list[tuple[int, list[Operator]]]:
        """按星级从高到低分组，供文本/图片输出使用。"""
        grouped: dict[int, list[Operator]] = {}
        for op in self.operators:
            grouped.setdefault(op.rarity, []).append(op)
        return [
            (star, sorted(grouped[star], key=lambda op: op.name))
            for star in sorted(grouped, reverse=True)
        ]


@dataclass(frozen=True)
class FilteredOut:
    """词条能匹配到干员，但在当前时长下星级都不在可出范围内。"""

    tags: tuple[str, ...]
    rarities: tuple[int, ...]


@dataclass(frozen=True)
class Result:
    combos: list[Combo]
    filtered_out: list[FilteredOut]
    minutes: int | None

    @property
    def empty(self) -> bool:
        return not self.combos


def calculate(
    selected: Sequence[str],
    operators: Sequence[Operator],
    minutes: int | None = None,
) -> Result:
    """枚举所有非空子集，返回有干员的组合，按"值得选"的程度排序。"""
    if not selected:
        return Result(combos=[], filtered_out=[], minutes=minutes)

    results: list[Combo] = []
    filtered: list[FilteredOut] = []

    for size in range(1, len(selected) + 1):
        for subset in combinations(selected, size):
            matched = [op for op in operators if op.matches(subset)]
            if not matched:
                continue

            allowed = allowed_rarities(minutes, subset)
            pool = sorted(
                (op for op in matched if op.rarity in allowed),
                key=lambda op: (-op.rarity, op.name),
            )
            if pool:
                results.append(Combo(tags=subset, operators=tuple(pool)))
            else:
                filtered.append(
                    FilteredOut(
                        tags=subset,
                        rarities=tuple(sorted({op.rarity for op in matched})),
                    )
                )

    # 保底星级优先；其次词条越多越精确；再其次池子越小越"干净"。
    results.sort(
        key=lambda combo: (
            -combo.guarantee,
            -len(combo.tags),
            len(combo.operators),
            combo.tags,
        )
    )
    return Result(combos=results, filtered_out=filtered, minutes=minutes)
