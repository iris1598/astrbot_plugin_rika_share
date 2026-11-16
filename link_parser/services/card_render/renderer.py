"""解析结果卡片渲染器（Pillow 实现，无需浏览器）。

本模块只负责编排：缓存路径、并发取图、解析样式、调用样式的 ``render()`` 并保存。
具体版式全部在 :mod:`~link_parser.services.card_render.styles` 包里，一种样式一个模块
（自动发现 + 自注册），新增样式不需要改本文件。

所有绘图操作均为 CPU 密集的同步任务，由调用方通过 ``asyncio.to_thread``
放到后台线程执行，避免阻塞 AstrBot 事件循环。
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

from astrbot.api import logger

from ...models import ImageContent, ParseResult
from ...models.task import PathTask
from .styles import DEFAULT_STYLE, StyleSpec, get_style, iter_styles
from .theme import THEMES, Image
from .toolkit import FontBook


class ShareCardRenderer:
    """将 ParseResult 渲染为精美卡片图片"""

    def __init__(
        self,
        cache_dir: Path,
        *,
        enabled: bool = True,
        width: int = 800,
        theme: str = "dark",
        font_path: str | None = None,
        layout: str | None = None,
        cover_full_size: bool = False,
        style: str | None = None,
    ):
        self.cache_dir = cache_dir
        self.enabled = enabled and Image is not None and bool(iter_styles())
        self.width = max(520, min(1080, int(width)))
        self.theme_name = theme if theme in THEMES else "dark"
        # ``style`` 是新参数；``layout`` 保留为旧调用方的别名
        requested = (style or layout or DEFAULT_STYLE).strip().lower()
        self.style_name = requested or DEFAULT_STYLE
        self.font_path = font_path
        self.cover_full_size = cover_full_size
        self._font_book = FontBook(font_path)
        if get_style(self.style_name) is None:
            logger.warning(
                f"[link_parser] 卡片样式 {self.style_name!r} 未注册，"
                f"渲染时回退 {DEFAULT_STYLE}"
            )

    @property
    def layout_name(self) -> str:
        """兼容旧字段名：当前实际生效的样式名。"""
        spec = self._resolve_style()
        return spec.name if spec is not None else self.style_name

    # ---------- 主流程 ----------

    async def render(
        self,
        result: ParseResult,
        cache_key: str | None = None,
        existing: Path | None = None,
        salt: str | None = None,
    ) -> Path | None:
        """异步渲染卡片，失败时返回 None（由调用方回退到文本输出）。

        ``salt`` 用于内容被重新解析的场景（如结果缓存已过期）：带上它会让输出
        文件名变化，从而绕开磁盘上的旧卡片；调用方此时还应把 ``existing`` 传
        ``None``，否则会直接复用内存里记录的旧图。
        """
        if not self.enabled:
            return None
        try:
            if existing is not None and existing.exists():
                return existing
            out_path = self._output_path(cache_key, result, salt)
            if out_path.exists():
                return out_path
            images = await self._collect_images(result)
            return await asyncio.to_thread(self._render_sync, result, images, out_path)
        except Exception:
            logger.exception("解析卡片渲染失败，已回退到文本输出")
            return None

    def _resolve_style(self) -> StyleSpec | None:
        """按配置的样式名取注册表条目；未知时回退默认样式，再回退第一个。"""
        spec = get_style(self.style_name)
        if spec is not None:
            return spec
        spec = get_style(DEFAULT_STYLE)
        if spec is not None:
            return spec
        styles = iter_styles()
        return styles[0] if styles else None

    def _output_path(
        self, cache_key: str | None, result: ParseResult, salt: str | None = None
    ) -> Path:
        warnings_str = "|".join(result.extra.get("limit_warnings") or [])
        payload = (
            cache_key
            or f"{result.platform.name}|{result.title}|{result.timestamp}|{result.url}"
        )
        if salt:
            payload = f"{payload}#{salt}"
        spec = self._resolve_style()
        style_name = spec.name if spec is not None else self.style_name
        style_version = spec.version if spec is not None else 0
        digest = hashlib.md5(
            f"{style_name}|{style_version}|{self.theme_name}|{self.width}|"
            f"{self.cover_full_size}|{payload}|{warnings_str}".encode("utf-8")
        ).hexdigest()[:16]
        return self.cache_dir / f"card_{digest}.png"

    async def _collect_images(self, result: ParseResult) -> dict[str, Any]:
        """并发获取头像 / 视频封面 / 图集图片的本地路径。"""
        images: dict[str, Any] = {"avatar": None, "hero": None, "grid": []}

        tasks: list[tuple[str, PathTask]] = []
        if result.author and result.author.avatar:
            tasks.append(("avatar", result.author.avatar))

        video = result.video
        hero_task: PathTask | None = None
        if video is not None and video.cover is not None:
            hero_task = video.cover
            tasks.append(("hero", hero_task))

        grid_tasks: list[PathTask] = []
        seen: set[int] = set()
        for t in result.all_grid_images:
            if id(t) not in seen:
                seen.add(id(t))
                grid_tasks.append(t)
        for g in result.graphics:
            if isinstance(g, ImageContent) and id(g.path_task) not in seen:
                seen.add(id(g.path_task))
                grid_tasks.append(g.path_task)

        # 图集中可能已包含视频封面，去重后单独取封面
        hero_id = id(hero_task) if hero_task else None
        for t in grid_tasks:
            if id(t) == hero_id:
                continue
            tasks.append(("grid", t))

        if not tasks:
            return images

        results = await asyncio.gather(
            *[t.safe_get() for _, t in tasks], return_exceptions=True
        )
        for (kind, _), path in zip(tasks, results):
            if not path:
                continue
            if kind == "avatar":
                images["avatar"] = path
            elif kind == "hero":
                images["hero"] = path
            else:
                images["grid"].append(path)
        return images

    # ---------- 同步绘制 ----------

    def _create_style(
        self,
        spec: StyleSpec,
        result: ParseResult,
        images: dict[str, Any],
        out_path: Path,
    ):
        """按样式声明解析配色并实例化样式（每次渲染一个新实例）。"""
        palette_name = self.theme_name
        palettes = spec.style_cls.palettes
        if palettes is not None and palettes and palette_name not in palettes:
            palette_name = palettes[0]
        return spec.create(
            self._font_book,
            width=self.width,
            theme=THEMES.get(palette_name, THEMES[self.theme_name]),
            theme_name=palette_name,
            cover_full_size=self.cover_full_size,
            result=result,
            images=images,
            out_path=out_path,
        )

    def _render_sync(
        self,
        result: ParseResult,
        images: dict[str, Any],
        out_path: Path,
    ) -> Path:
        """按注册表解析样式并渲染；样式不适用时按 fallback 回退。"""
        spec = self._resolve_style()
        if spec is None:
            raise RuntimeError("没有可用的卡片样式")

        style = self._create_style(spec, result, images, out_path)
        if not style.can_render():
            fallback = get_style(style.fallback or DEFAULT_STYLE)
            if fallback is None or fallback.name == spec.name:
                raise RuntimeError(
                    f"卡片样式 {spec.name} 当前内容不适用，且没有可用回退样式"
                )
            style = self._create_style(fallback, result, images, out_path)
        return style.render()
