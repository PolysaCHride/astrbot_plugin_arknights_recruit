"""明日方舟公开招募计算插件。

指令只有一个：``/公招 <词条> [词条 ...]``，词条之间用空格分隔，最多 5 个。
"""

from __future__ import annotations

import asyncio
import os
import time

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register

try:
    # GreedyStr 让处理器一次拿到指令后的全部文本，AstrBot 内置指令也是这么用的。
    from astrbot.core.star.filter.command import GreedyStr

    _HAS_GREEDY = True
except ImportError:  # 老版本没有这个标记类型，退回手动从消息里剥指令
    GreedyStr = str
    _HAS_GREEDY = False

from .core.calculator import (
    MAX_TAGS,
    calculate,
    rarity_bounds,
    parse_time,
    time_label,
)
from .core.data import RecruitData
from .core.image_view import build_layout, build_render_options, template_path
from .core.tags import TAGS, resolve_all
from .core.text_view import DEFAULT_CHUNK_LIMIT, render_chunks

NO_TAG_REPLY = "算公招连Tag都不给我，那我只能给你算一卦了"

PLUGIN_NAME = "astrbot_plugin_arknights_recruit"

_COMMAND_PREFIXES = ("/公招", "公招")


def _strip_command(message_str: str) -> str:
    """仅在拿不到 GreedyStr 时使用：从整条消息里剥掉指令名。"""
    text = (message_str or "").strip()
    for prefix in _COMMAND_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix) :].strip()
    return text


@register(
    PLUGIN_NAME,
    "PolysaCHride",
    "明日方舟公开招募词条组合计算",
    "1.0.0",
    "https://github.com/PolysaCHride/astrbot_plugin_arknights_recruit",
)
class ArknightsRecruitPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config or {}

        bundled = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data", "recruit_operators.json"
        )
        self.data = RecruitData(bundled, str(StarTools.get_data_dir()))

        self._template: str | None = None
        self._update_task: asyncio.Task | None = None

    async def initialize(self) -> None:
        if self.config.get("auto_update", False):
            self._update_task = asyncio.create_task(self._auto_update())

    async def terminate(self) -> None:
        if self._update_task and not self._update_task.done():
            self._update_task.cancel()

    # ------------------------------------------------------------------ 指令

    @filter.command("公招")
    async def recruit(self, event: AstrMessageEvent, tags: GreedyStr):
        """计算公开招募词条组合可能出现的干员。"""
        raw = (tags or "").strip()
        if not _HAS_GREEDY:
            raw = _strip_command(event.message_str)
        if not raw:
            yield event.plain_result(NO_TAG_REPLY)
            return

        tokens = raw.split()
        if len(tokens) > MAX_TAGS:
            yield event.plain_result(
                f"公开招募一次最多只能选 {MAX_TAGS} 个词条，你给了 {len(tokens)} 个。"
            )
            return

        selected, failures = resolve_all(tokens)
        if failures:
            yield event.plain_result(self._failure_reply(failures))
            return

        minutes = parse_time(self.config.get("recruit_time", "all"))
        time_text = time_label(minutes)
        result = calculate(selected, self.data.operators, minutes)

        if result.empty:
            yield event.plain_result(self._empty_reply(selected, result))
            return

        image_url = await self._render_image(event, selected, result.combos, time_text)
        if image_url:
            yield event.image_result(image_url)
            return

        limit = int(
            self.config.get("text_chunk_limit", DEFAULT_CHUNK_LIMIT) or DEFAULT_CHUNK_LIMIT
        )
        for chunk in render_chunks(selected, result.combos, limit, time_text):
            yield event.plain_result(chunk)

    # ------------------------------------------------------------------ 输出

    async def _render_image(
        self,
        event: AstrMessageEvent,
        selected: list[str],
        combos: list,
        time_text: str,
    ) -> str | None:
        """渲染结果图；关闭、超限或渲染失败时返回 None，由调用方降级为文本。"""
        if str(self.config.get("output_mode", "image")).lower() != "image":
            return None

        show_star = bool(self.config.get("image_show_star", False))
        layout = build_layout(selected, combos, show_star, time_text)
        max_height = int(self.config.get("max_image_height", 8000) or 8000)
        if layout.height > max_height:
            logger.warning(
                f"[公招] 图片高度 {layout.height}px 超过上限 {max_height}px，改用文本输出"
            )
            return None

        try:
            url = await self.html_render(
                self._load_template(),
                layout.data,
                options=build_render_options(
                    layout, precise=bool(self.config.get("precise_image_size", True))
                ),
                umo=event.unified_msg_origin,
            )
        except Exception as exc:  # noqa: BLE001 - 渲染服务不稳定，降级即可
            logger.warning(f"[公招] 图片渲染失败，改用文本输出：{exc}")
            return None

        return url or None

    def _load_template(self) -> str:
        if self._template is None:
            with open(template_path(), encoding="utf-8") as fp:
                self._template = fp.read()
        return self._template

    @staticmethod
    def _failure_reply(failures: list[tuple[str, list[str]]]) -> str:
        lines = ["有词条没认出来："]
        for raw, candidates in failures:
            if candidates:
                lines.append(f"· 「{raw}」→ 是想说 {' / '.join(candidates)} 吗？")
            else:
                lines.append(f"· 「{raw}」不在公开招募词条里")
        lines.append("")
        lines.append(f"可选词条：{' '.join(TAGS)}")
        return "\n".join(lines)

    @staticmethod
    def _empty_reply(selected: list[str], result) -> str:
        """词条本身有效，但当前时长下招不到干员。"""
        combo = " + ".join(selected)
        if result.minutes is None:
            return f"「{combo}」没有任何干员能同时满足，换个组合试试。"

        label = time_label(result.minutes)
        lines = [f"「{combo}」在{label}下没有符合条件的干员。"]
        if result.filtered_out:
            low, high = rarity_bounds(result.minutes)
            detail = "；".join(
                f"{' + '.join(item.tags)}（只有 "
                + " / ".join(f"{rarity}★" for rarity in item.rarities)
                + "）"
                for item in result.filtered_out[:4]
            )
            lines.append(f"能匹配到的组合是：{detail}")
            lines.append(
                f"公招时长决定星级下限，{label}只能出 {low}★ ~ {high}★ 干员。"
                "把配置 recruit_time 改成 all，就能看到全部时长下的可能结果。"
            )
        else:
            lines.append("这几个词条没有任何干员能同时满足，换个组合试试。")
        return "\n".join(lines)

    # ------------------------------------------------------------------ 数据更新

    async def _auto_update(self) -> None:
        try:
            interval = int(self.config.get("update_interval_days", 7) or 7)
            age_days = (time.time() - self.data.updated_at) / 86400
            if age_days < interval:
                return
            await asyncio.sleep(10)  # 避开启动高峰
            ok, message = await self.data.refresh()
            logger.info(f"[公招] 自动更新{'成功' if ok else '失败'}：{message}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[公招] 自动更新异常：{exc}")
