"""干员招募数据的加载与更新。

插件自带一份离线数据集（``data/recruit_operators.json``），数据来源为
MaaAssistantArknights 维护的 ``resource/recruitment.json``，它同时包含公招池
成员和每名干员的完整词条。默认不联网，配置里可以开启定时/手动更新。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

from astrbot.api import logger

from .tags import TAGS

# MAA 的原始数据，主源 + 镜像
REMOTE_SOURCES: tuple[str, ...] = (
    "https://raw.githubusercontent.com/MaaAssistantArknights/MaaAssistantArknights/master/resource/recruitment.json",
    "https://cdn.jsdelivr.net/gh/MaaAssistantArknights/MaaAssistantArknights@master/resource/recruitment.json",
)

# 公招界面不提供、需要从数据里剔除的标签
_IGNORED_TAGS = frozenset({"男性干员", "女性干员"})


@dataclass(frozen=True)
class Operator:
    name: str
    rarity: int
    tags: frozenset[str]

    def matches(self, required: tuple[str, ...]) -> bool:
        return all(tag in self.tags for tag in required)


class RecruitData:
    """持有当前生效的干员列表，并负责把它持久化 / 从上游更新。"""

    def __init__(self, bundled_path: str, cache_dir: str) -> None:
        self.bundled_path = bundled_path
        self.cache_path = os.path.join(cache_dir, "recruit_operators.json")
        self.operators: list[Operator] = []
        self.source = "bundled"
        self.updated_at: float = 0.0
        self.load()

    # ------------------------------------------------------------------ 加载

    def load(self) -> None:
        """优先读缓存，其次读插件自带的数据。"""
        for path, source in ((self.cache_path, "cache"), (self.bundled_path, "bundled")):
            if not os.path.exists(path):
                continue
            try:
                with open(path, encoding="utf-8") as fp:
                    payload = json.load(fp)
                self.operators = self._parse(payload)
                self.source = source
                self.updated_at = os.path.getmtime(path)
                logger.info(
                    f"[公招] 已载入 {len(self.operators)} 名干员（来源：{source}）"
                )
                return
            except Exception as exc:  # noqa: BLE001 - 坏数据不应该拖垮插件
                logger.warning(f"[公招] 载入 {path} 失败：{exc}")

        raise RuntimeError("无法载入公招干员数据，请检查 data/recruit_operators.json")

    @staticmethod
    def _parse(payload: dict[str, Any]) -> list[Operator]:
        raw_operators = payload.get("operators")
        if not isinstance(raw_operators, list) or not raw_operators:
            raise ValueError("数据缺少 operators 字段")

        known = set(TAGS)
        operators: list[Operator] = []
        for item in raw_operators:
            name = str(item["name"]).strip()
            rarity = int(item["rarity"])
            tags = frozenset(t for t in item.get("tags", ()) if t in known)
            if not name or not 1 <= rarity <= 6 or not tags:
                continue
            operators.append(Operator(name=name, rarity=rarity, tags=tags))

        if not operators:
            raise ValueError("数据里没有解析出任何干员")
        return operators

    # ------------------------------------------------------------------ 更新

    async def refresh(self) -> tuple[bool, str]:
        """从上游拉取最新数据。返回 ``(是否成功, 说明)``。"""
        try:
            import httpx
        except ImportError:  # pragma: no cover - AstrBot 环境自带
            return False, "缺少 httpx 依赖，无法在线更新"

        last_error = ""
        for url in REMOTE_SOURCES:
            try:
                async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    payload = resp.json()
                operators = self._parse(payload)
            except Exception as exc:  # noqa: BLE001 - 换下一个源
                last_error = f"{url} -> {exc}"
                logger.warning(f"[公招] 更新源失败：{last_error}")
                continue

            payload = {
                "source": url,
                "generated": time.strftime("%Y-%m-%d", time.localtime()),
                "tags": list(TAGS),
                "operators": sorted(
                    (
                        {"name": op.name, "rarity": op.rarity, "tags": sorted(op.tags)}
                        for op in operators
                    ),
                    key=lambda item: (-item["rarity"], item["name"]),
                ),
            }
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as fp:
                json.dump(payload, fp, ensure_ascii=False, indent=1)

            self.operators = operators
            self.source = "remote"
            self.updated_at = time.time()
            logger.info(f"[公招] 在线更新成功，共 {len(operators)} 名干员")
            return True, f"已更新至 {len(operators)} 名干员"

        return False, last_error or "所有更新源均不可用"
