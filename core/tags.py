"""公招词条的归一化与别名匹配。

玩家输入的写法五花八门（高姿 / 高资 / 回费 / 防御 / 支援器械），这里把它们
统一映射到游戏内的 29 个正式词条上。匹配顺序为：

    正式词条全等 -> 别名表 -> 唯一前缀

任何一步都无法确定唯一结果时都不做猜测，交给调用方报错。
"""

from __future__ import annotations

import re
import unicodedata

# 公开招募界面可选的 29 个词条，与游戏 gachaTags 一致。
TAGS: tuple[str, ...] = (
    "先锋干员",
    "近卫干员",
    "狙击干员",
    "重装干员",
    "医疗干员",
    "辅助干员",
    "术师干员",
    "特种干员",
    "近战位",
    "远程位",
    "高级资深干员",
    "资深干员",
    "新手",
    "费用回复",
    "输出",
    "防护",
    "生存",
    "群攻",
    "减速",
    "治疗",
    "支援",
    "削弱",
    "位移",
    "召唤",
    "快速复活",
    "爆发",
    "控场",
    "支援机械",
    "元素",
)

# 别名表：玩家常用简写 -> 正式词条名。
# 键必须是规范化后的形式（无空白、半角）。
ALIASES: dict[str, str] = {
    # 资质
    "高姿": "高级资深干员",
    "高资": "高级资深干员",
    "资深": "资深干员",
    # 职业（PRTS 界面本身也只写职业名，不带"干员"）
    "先锋": "先锋干员",
    "近卫": "近卫干员",
    "狙击": "狙击干员",
    "重装": "重装干员",
    "医疗": "医疗干员",
    "辅助": "辅助干员",
    "术师": "术师干员",
    "特种": "特种干员",
    # 位置
    "近战": "近战位",
    "远程": "远程位",
    # 词缀
    "回费": "费用回复",
    "费回": "费用回复",
    "防御": "防护",
    "支援器械": "支援机械",
    "器械": "支援机械",
    "复活": "快速复活",
    "快活": "快速复活",
}


def normalize(raw: str) -> str:
    """去掉空白、统一全角，得到用于匹配的紧凑形式。"""
    text = unicodedata.normalize("NFKC", raw or "")
    return re.sub(r"\s+", "", text)


def resolve(raw: str) -> tuple[str | None, list[str]]:
    """把一个输入片段解析成正式词条。

    返回 ``(词条名, 候选列表)``：

    * 命中时返回 ``(词条名, [])``
    * 无法唯一确定时返回 ``(None, 候选)``，候选为空表示完全不认识这个词条
    """
    token = normalize(raw)
    if not token:
        return None, []

    if token in TAGS:
        return token, []

    alias = ALIASES.get(token)
    if alias is not None:
        return alias, []

    candidates = [tag for tag in TAGS if tag.startswith(token)]
    if len(candidates) == 1:
        return candidates[0], []

    return None, candidates


def resolve_all(raw_tags: list[str]) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """批量解析，返回 ``(成功命中的词条, [(原始片段, 候选)])``。

    重复词条会被去重，但保持首次出现的顺序。
    """
    matched: list[str] = []
    failures: list[tuple[str, list[str]]] = []
    for raw in raw_tags:
        tag, candidates = resolve(raw)
        if tag is None:
            failures.append((raw, candidates))
        elif tag not in matched:
            matched.append(tag)
    return matched, failures
