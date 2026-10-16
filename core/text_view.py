"""文本形式的计算结果（图片渲染失败或配置为纯文本时使用）。

每个词条组合一行标题，下面按星级从高到低分组列出干员。
"""

from __future__ import annotations

from typing import Sequence

from .calculator import Combo

# 单条消息的目标长度上限，超长时按组合切分成多条发送
DEFAULT_CHUNK_LIMIT = 1200


def _combo_block(index: int, combo: Combo) -> list[str]:
    lines = [f"{index}. {' + '.join(combo.tags)}"]
    for star, operators in combo.by_star():
        lines.append(f"   ★{star}：{' '.join(op.name for op in operators)}")
    return lines


def render_chunks(
    selected: Sequence[str],
    combos: Sequence[Combo],
    limit: int = DEFAULT_CHUNK_LIMIT,
    time_text: str = "",
) -> list[str]:
    """把结果渲染成一条或多条文本消息。"""
    head = f"输入：{' '.join(selected)}"
    if time_text:
        head += f" · {time_text}"
    header = ["📋 公开招募 · 计算结果", head, ""]

    chunks: list[str] = []
    current: list[str] = list(header)

    def flush() -> None:
        nonlocal current
        text = "\n".join(current).rstrip()
        if text.strip():
            chunks.append(text)
        current = []

    for index, combo in enumerate(combos, start=1):
        block = _combo_block(index, combo)
        block_size = sum(len(line) + 1 for line in block)

        if len("\n".join(current)) + block_size > limit and len(current) > len(header):
            flush()

        # 极端情况下单个组合本身就超长（例如"近战位"单选有 80+ 名干员），
        # 按星级逐行拆开，避免单条消息被平台截断。
        if block_size > limit:
            for line in block:
                if len("\n".join(current)) + len(line) + 1 > limit:
                    flush()
                current.append(line)
        else:
            current.extend(block)

    flush()
    return chunks or ["\n".join(header).rstrip()]
