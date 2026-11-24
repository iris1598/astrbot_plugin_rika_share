"""解析结果卡片渲染器（Pillow 实现，无需浏览器）。

本模块只负责编排：底卡缓存、并发取图、解析样式、调用样式的 ``render()``、
跨人格页脚水印合成，以及供 WebUI 使用的内存实时预览。
具体版式全部在 :mod:`~link_parser.services.card_render.styles` 包里，一种样式一个模块
（自动发现 + 自注册），新增样式不需要改本文件。

所有绘图操作均为 CPU 密集的同步任务，由调用方通过 ``asyncio.to_thread``
放到后台线程执行，避免阻塞 AstrBot 事件循环。
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any

from astrbot.api import logger

from ...models import ImageContent, ParseResult
from ...models.task import PathTask
from ...utils.persona import DEFAULT_BRAND_NAME
from .styles import DEFAULT_STYLE, StyleSpec, get_style, iter_styles
from .theme import THEMES, Image
from .toolkit import FontBook, draw_watermark_on_canvas


def _save_png_atomic(canvas: Any, target: Path) -> Path:
    """将画布原子保存为 PNG。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.stem}.{os.getpid()}.tmp.png")
    try:
        canvas.save(tmp, "PNG", optimize=True)
        tmp.replace(target)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target


class ShareCardRenderer:
    """将 ParseResult 渲染为精美卡片图片。"""

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
        font_book: FontBook | None = None,
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
        self._font_book = (
            font_book
            if font_book is not None and getattr(font_book, "font_path", None) == font_path
            else FontBook(font_path)
        )
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
        watermark: str = DEFAULT_BRAND_NAME,
    ) -> Path | None:
        """异步渲染卡片，失败时返回 None（由调用方回退到文本输出）。

        当样式支持动态页脚时，主体内容与视觉背景渲染为一份无水印底卡并复用：
        同一内容在不同会话人格下首次渲染时，直接从底卡在内存中叠印 ``<人格>解析``
        并保存成图，避免重复解析、取图与整卡重绘。
        """
        if not self.enabled:
            return None
        try:
            if existing is not None and existing.exists():
                return existing

            wm = (watermark or DEFAULT_BRAND_NAME).strip() or DEFAULT_BRAND_NAME
            spec = self._resolve_style()
            if spec is None:
                return None

            base_digest = self._base_digest(cache_key, result, salt, spec)
            base_path, anchor_path, final_path = self._paths_for(base_digest, wm)
            if final_path.exists():
                return final_path

            if (
                spec.style_cls.supports_dynamic_footer
                and base_path.exists()
                and anchor_path.exists()
            ):
                composed = await asyncio.to_thread(
                    self._compose_from_base_sync,
                    base_path,
                    anchor_path,
                    final_path,
                    wm,
                )
                if composed is not None:
                    return composed

            images = await self._collect_images(result)
            return await asyncio.to_thread(
                self._render_full_sync,
                result,
                images,
                base_path,
                anchor_path,
                final_path,
                wm,
            )
        except Exception:
            logger.exception("解析卡片渲染失败，已回退到文本输出")
            return None

    async def render_preview_png(
        self,
        result: ParseResult,
        images: dict[str, Any] | None = None,
        *,
        watermark: str = DEFAULT_BRAND_NAME,
    ) -> tuple[bytes, str]:
        """在内存中渲染实时预览 PNG，返回 ``(png_bytes, 实际使用样式名)``。"""
        if Image is None:
            raise RuntimeError("Pillow 未安装，无法渲染预览卡片")
        collected = images if images is not None else await self._collect_images(result)
        wm = (watermark or DEFAULT_BRAND_NAME).strip() or DEFAULT_BRAND_NAME
        return await asyncio.to_thread(self._render_preview_sync, result, collected, wm)

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

    def _base_digest(
        self,
        cache_key: str | None,
        result: ParseResult,
        salt: str | None,
        spec: StyleSpec,
    ) -> str:
        warnings_str = "|".join(result.extra.get("limit_warnings") or [])
        payload = (
            cache_key
            or f"{result.platform.name}|{result.title}|{result.timestamp}|{result.url}"
        )
        if salt:
            payload = f"{payload}#{salt}"
        return hashlib.md5(
            f"{spec.name}|{spec.version}|{self.theme_name}|{self.width}|"
            f"{self.cover_full_size}|{payload}|{warnings_str}".encode("utf-8")
        ).hexdigest()[:16]

    def _paths_for(self, base_digest: str, watermark: str) -> tuple[Path, Path, Path]:
        wm_digest = hashlib.md5(watermark.encode("utf-8")).hexdigest()[:8]
        base_path = self.cache_dir / f"card_{base_digest}_base.png"
        anchor_path = self.cache_dir / f"card_{base_digest}_base.anchor.json"
        final_path = self.cache_dir / f"card_{base_digest}_w_{wm_digest}.png"
        return base_path, anchor_path, final_path

    def _output_path(
        self,
        cache_key: str | None,
        result: ParseResult,
        salt: str | None = None,
        watermark: str = DEFAULT_BRAND_NAME,
    ) -> Path:
        """兼容外部或脚本检查默认成品路径。"""
        spec = self._resolve_style()
        if spec is None:
            raise RuntimeError("没有可用的卡片样式")
        base_digest = self._base_digest(cache_key, result, salt, spec)
        _, _, final_path = self._paths_for(base_digest, watermark)
        return final_path

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
        *,
        watermark_text: str | None = DEFAULT_BRAND_NAME,
        in_memory: bool = False,
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
            watermark_text=watermark_text,
            in_memory=in_memory,
        )

    def _instantiate_effective_style(
        self,
        result: ParseResult,
        images: dict[str, Any],
        out_path: Path,
        *,
        watermark_text: str | None,
        in_memory: bool = False,
    ) -> tuple[Any, StyleSpec]:
        spec = self._resolve_style()
        if spec is None:
            raise RuntimeError("没有可用的卡片样式")

        style = self._create_style(
            spec,
            result,
            images,
            out_path,
            watermark_text=watermark_text,
            in_memory=in_memory,
        )
        if not style.can_render():
            fallback = get_style(style.fallback or DEFAULT_STYLE)
            if fallback is None or fallback.name == spec.name:
                raise RuntimeError(
                    f"卡片样式 {spec.name} 当前内容不适用，且没有可用回退样式"
                )
            spec = fallback
            style = self._create_style(
                fallback,
                result,
                images,
                out_path,
                watermark_text=watermark_text,
                in_memory=in_memory,
            )
        return style, spec

    def _compose_from_base_sync(
        self,
        base_path: Path,
        anchor_path: Path,
        final_path: Path,
        watermark: str,
    ) -> Path | None:
        """读取无水印底卡与锚点 JSON，叠印指定署名后保存成图。"""
        try:
            anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
            foot_y = int(anchor["foot_y"])
            pad = int(anchor["pad"])
            accent = str(anchor["accent"])
            font_size = int(anchor["font_size"])
            with Image.open(base_path) as im:
                im.load()
                canvas = im.convert("RGBA") if im.mode != "RGBA" else im.copy()
            draw_watermark_on_canvas(
                canvas,
                self._font_book,
                watermark=watermark,
                foot_y=foot_y,
                pad=pad,
                accent=accent,
                font_size=font_size,
            )
            saved = _save_png_atomic(canvas, final_path)
            try:
                os.utime(base_path, None)
                os.utime(anchor_path, None)
            except OSError:
                pass
            return saved
        except Exception:
            logger.debug("[link_parser] 复用底卡叠印署名失败，回退整卡渲染", exc_info=True)
            return None

    def _render_full_sync(
        self,
        result: ParseResult,
        images: dict[str, Any],
        base_path: Path,
        anchor_path: Path,
        final_path: Path,
        watermark: str,
    ) -> Path:
        spec = self._resolve_style()
        if spec is None:
            raise RuntimeError("没有可用的卡片样式")

        if not spec.style_cls.supports_dynamic_footer:
            style, _ = self._instantiate_effective_style(
                result, images, final_path, watermark_text=watermark
            )
            return style.render()

        style, effective_spec = self._instantiate_effective_style(
            result, images, base_path, watermark_text=None
        )
        rendered_base = style.render()
        anchor = getattr(style, "_footer_anchor", None)
        last_canvas = getattr(style, "_last_canvas", None)

        if not effective_spec.style_cls.supports_dynamic_footer or anchor is None:
            # 样式实际未走 footer_block 锚点：退回直接带水印整卡渲染到 final_path
            direct, _ = self._instantiate_effective_style(
                result, images, final_path, watermark_text=watermark
            )
            return direct.render()

        anchor_path.parent.mkdir(parents=True, exist_ok=True)
        anchor_path.write_text(json.dumps(anchor, ensure_ascii=False), encoding="utf-8")

        if last_canvas is None:
            composed = self._compose_from_base_sync(
                rendered_base, anchor_path, final_path, watermark
            )
            if composed is not None:
                return composed
            direct, _ = self._instantiate_effective_style(
                result, images, final_path, watermark_text=watermark
            )
            return direct.render()

        canvas = (
            last_canvas.convert("RGBA")
            if last_canvas.mode != "RGBA"
            else last_canvas.copy()
        )
        draw_watermark_on_canvas(
            canvas,
            self._font_book,
            watermark=watermark,
            foot_y=int(anchor["foot_y"]),
            pad=int(anchor["pad"]),
            accent=str(anchor["accent"]),
            font_size=int(anchor["font_size"]),
        )
        return _save_png_atomic(canvas, final_path)

    def _render_preview_sync(
        self,
        result: ParseResult,
        images: dict[str, Any],
        watermark: str,
    ) -> tuple[bytes, str]:
        style, effective_spec = self._instantiate_effective_style(
            result,
            images,
            self.cache_dir / "_preview.png",
            watermark_text=watermark,
            in_memory=True,
        )
        style.render()
        raw = getattr(style, "_memory_bytes", None)
        if raw is None and getattr(style, "_last_canvas", None) is not None:
            buf = io.BytesIO()
            style._last_canvas.save(buf, "PNG", optimize=True)
            raw = buf.getvalue()
        if not raw:
            raise RuntimeError(f"样式 {effective_spec.name} 未产出有效的预览图像")
        return raw, effective_spec.name
