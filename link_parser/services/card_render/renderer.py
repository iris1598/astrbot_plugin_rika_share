"""解析结果卡片渲染器（Pillow 实现，无需浏览器）。

按 ``layout`` 分发到 standard / magazine / immersive / feed 四种布局，
所有绘图操作均为 CPU 密集的同步任务，由调用方通过 ``asyncio.to_thread``
放到后台线程执行，避免阻塞 AstrBot 事件循环。
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import sys
import unicodedata
from pathlib import Path
from typing import Any

from astrbot.api import logger

from ...models import ImageContent, ParseResult
from ...models.task import PathTask
from .fonts import (
    FONT_DIRS,
    SYMBOL_FONT_CANDIDATES,
    UNCOVERED_WARNED,
    TTFont,
    discover_fonts,
    font_cmap,
    fontconfig_lookup,
)
from .text import format_timestamp, one_line, parse_stats_line, short_url, strip_emoji
from .theme import (
    L,
    LANCZOS,
    LAYOUT_NAMES,
    PLATFORM_COLORS,
    THEMES,
    Theme,
    Image,
    ImageDraw,
    ImageFilter,
    ImageFont,
    ImageOps,
    hex_to_rgb,
    mix,
    with_alpha,
)


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
        layout: str = "standard",
        cover_full_size: bool = False,
    ):
        self.cache_dir = cache_dir
        self.enabled = enabled and Image is not None
        self.width = max(520, min(1080, int(width)))
        self.theme_name = theme if theme in THEMES else "dark"
        self.layout_name = layout if layout in LAYOUT_NAMES else "standard"
        self.font_path = font_path
        self.cover_full_size = cover_full_size
        self._regular_font: str | None = None
        self._bold_font: str | None = None
        self._font_cache: dict[tuple[int, bool], Any] = {}
        # id(font) -> (size, bold)，供 _text_width 反查字号
        self._font_meta: dict[int, tuple[int, bool]] = {}
        # 符号回退字体：[(路径, cmap)]，None 表示尚未加载
        self._fallback_specs: list[tuple[str, frozenset[int]]] | None = None
        # 主字体 cmap，None 表示尚未加载
        self._primary_cmap: frozenset[int] | None = None
        # 回退字体对象缓存 (路径, 字号) -> font
        self._fallback_font_cache: dict[tuple[str, int], Any] = {}
        self._measure = ImageDraw.Draw(Image.new("RGBA", (1, 1))) if Image else None

    # ---------- 字体 ----------

    def _load_fonts(self) -> None:
        self._regular_font, self._bold_font = discover_fonts(self.font_path)
        self._primary_cmap = None  # 主字体变化后重新加载 cmap
        if not self._regular_font:
            logger.warning(
                "未找到可用的中文字体，解析卡片文字可能显示为方块，"
                "可在插件配置 RENDER_FONT_PATH 中指定字体文件"
            )

    def _font(self, size: int, bold: bool = False) -> Any:
        key = (size, bold)
        if key in self._font_cache:
            return self._font_cache[key]
        if self._regular_font is None:
            self._load_fonts()
        path = self._bold_font if bold and self._bold_font else self._regular_font
        try:
            if path:
                font = ImageFont.truetype(str(path), size)
            else:
                font = ImageFont.load_default()
        except Exception:
            logger.exception(f"加载字体失败: {path}")
            font = ImageFont.load_default()
        self._font_cache[key] = font
        self._font_meta[id(font)] = (size, bold)
        return font

    def _get_primary_cmap(self) -> frozenset[int]:
        """主字体（常规字重）的码点覆盖集合。"""
        if self._primary_cmap is None:
            if self._regular_font is None:
                self._load_fonts()
            self._primary_cmap = (
                font_cmap(self._regular_font) if self._regular_font else frozenset()
            )
        return self._primary_cmap

    def _load_fallbacks(self) -> list[tuple[str, frozenset[int]]]:
        """加载符号回退字体链（懒加载，仅加载一次）。"""
        if self._fallback_specs is not None:
            return self._fallback_specs
        specs: list[tuple[str, frozenset[int]]] = []
        if TTFont is not None:
            # 用户自定义字体目录中的字体优先作为回退
            if self.font_path:
                p = Path(self.font_path).expanduser()
                if p.is_dir():
                    for ext in ("*.ttf", "*.ttc", "*.otf"):
                        for f in sorted(p.glob(ext)):
                            cmap = font_cmap(str(f))
                            if cmap:
                                specs.append((str(f), cmap))
            names = SYMBOL_FONT_CANDIDATES.get(
                sys.platform, SYMBOL_FONT_CANDIDATES["linux"]
            )
            dirs = [Path(d) for d in FONT_DIRS]
            for name in names:
                for d in dirs:
                    candidate = d / name
                    if candidate.exists():
                        cmap = font_cmap(str(candidate))
                        if cmap:
                            specs.append((str(candidate), cmap))
                        break
        self._fallback_specs = specs
        if specs:
            logger.debug(f"符号回退字体链已加载: {[p for p, _ in specs]}")
        return specs

    def _fallback_font(self, path: str, size: int) -> Any:
        """按路径与字号加载（并缓存）回退字体对象。"""
        key = (path, size)
        font = self._fallback_font_cache.get(key)
        if font is None:
            try:
                font = ImageFont.truetype(str(path), size)
            except Exception:
                logger.warning(f"加载回退字体失败: {path}", exc_info=True)
                font = ImageFont.load_default()
            self._fallback_font_cache[key] = font
        return font

    def _split_runs(self, text: str, size: int, bold: bool) -> list[tuple[str, Any, bool]]:
        """按字体覆盖情况将文本切分为渲染段。

        返回 [(段文本, 字体对象, 是否主字体)]。主字体缺失字形的字符
        会切换到第一个覆盖它的回退字体；组合附标（如 ̫）始终跟随
        前一段，避免拆开后错位。无 fontTools 或无可用回退时退化为单段。
        """
        primary = self._font(size, bold)
        fallbacks = self._load_fallbacks()
        if not fallbacks or not text:
            return [(text, primary, True)]
        primary_cmap = self._get_primary_cmap()

        runs: list[tuple[str, Any, bool]] = []
        cur_text = ""
        cur_path: str | None = None  # None 表示主字体
        cur_font = primary

        for ch in text:
            if unicodedata.combining(ch) and cur_text:
                # 组合附标跟随前一段，不单独成段
                cur_text += ch
                continue
            cp = ord(ch)
            path: str | None = None
            if cp not in primary_cmap:
                for fp, cmap in fallbacks:
                    if cp in cmap:
                        path = fp
                        break
                else:
                    # 预设回退链未覆盖：尝试 fontconfig 动态查找并补入链中
                    fc_path = fontconfig_lookup(cp)
                    if fc_path and cp in font_cmap(fc_path):
                        fallbacks.append((fc_path, font_cmap(fc_path)))
                        path = fc_path
                    elif cp not in UNCOVERED_WARNED and cp != 0x0A:
                        UNCOVERED_WARNED.add(cp)
                        logger.debug(
                            f"主字体与回退字体均不含字符 U+{cp:04X} {ch!r}，将显示为占位方块"
                        )
            if path == cur_path:
                cur_text += ch
            else:
                if cur_text:
                    runs.append((cur_text, cur_font, cur_path is None))
                cur_text = ch
                cur_path = path
                cur_font = self._fallback_font(path, size) if path else primary
        if cur_text:
            runs.append((cur_text, cur_font, cur_path is None))
        return runs

    def _bold_stroke(self, bold: bool) -> int:
        """使用常规字体模拟粗体时的描边宽度。"""
        return 2 if bold and not self._bold_font and self._regular_font else 0

    # ---------- 文本工具 ----------

    def _text_width(self, text: str, font: Any) -> int:
        meta = self._font_meta.get(id(font))
        if meta is not None and self._load_fallbacks():
            total = 0.0
            for run_text, run_font, _ in self._split_runs(text, meta[0], meta[1]):
                total += self._measure.textlength(run_text, font=run_font)
            return math.ceil(total)
        return math.ceil(self._measure.textlength(text, font=font))

    def _wrap(self, text: str, font: Any, max_width: int) -> list[str]:
        """按字符宽度换行，兼容中日韩文本。"""
        lines: list[str] = []
        for raw in text.split("\n"):
            if not raw:
                lines.append("")
                continue
            current = ""
            for ch in raw:
                if self._text_width(current + ch, font) <= max_width:
                    current += ch
                else:
                    lines.append(current)
                    current = ch
            lines.append(current)
        return lines

    def _fit_lines(
        self, text: str, font: Any, max_width: int, max_lines: int
    ) -> list[str]:
        lines = self._wrap(text, font, max_width)
        if len(lines) <= max_lines:
            return lines
        result = lines[: max_lines - 1]
        last = lines[max_lines - 1]
        ellipsis = "…"
        while last and self._text_width(last + ellipsis, font) > max_width:
            last = last[:-1]
        result.append(last + ellipsis)
        return result

    def _line_height(self, font: Any) -> int:
        ascent, descent = font.getmetrics()
        return ascent + descent

    def _draw_text(
        self,
        draw: Any,
        xy: tuple[int, int],
        text: str,
        size: int,
        fill: str | tuple[int, int, int],
        bold: bool = False,
        stroke_width: int | None = None,
        stroke_fill: str | tuple[int, int, int] | None = None,
    ) -> None:
        # 单行文本绘制：换行会导致 PIL 无法测量宽度
        text = text.replace("\r", " ").replace("\n", " ")
        font = self._font(size, bold)
        if stroke_width is None:
            stroke_width = self._bold_stroke(bold)
        if stroke_fill is None:
            stroke_fill = fill
        runs = self._split_runs(text, size, bold)
        if len(runs) == 1:
            draw.text(
                xy,
                text,
                font=runs[0][1],
                fill=fill,
                stroke_width=stroke_width,
                stroke_fill=stroke_fill,
            )
            return
        # 多字体混排：逐段绘制并按主字体基线对齐
        x, y = xy
        base_ascent = font.getmetrics()[0]
        for run_text, run_font, _ in runs:
            try:
                run_ascent = run_font.getmetrics()[0]
            except Exception:
                run_ascent = base_ascent
            draw.text(
                (x, y + base_ascent - run_ascent),
                run_text,
                font=run_font,
                fill=fill,
                stroke_width=stroke_width,
                stroke_fill=stroke_fill,
            )
            x += self._measure.textlength(run_text, font=run_font)

    # ---------- 图片工具 ----------

    @staticmethod
    def _open_image(path: Path) -> Image.Image:
        with Image.open(path) as im:
            im.load()
            im = ImageOps.exif_transpose(im)
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA")
            return im.copy()

    @staticmethod
    def _cover_fit(image: Image.Image, box_w: int, box_h: int) -> Image.Image:
        """等比缩放并居中裁剪填满目标区域。"""
        img = image.convert("RGB")
        iw, ih = img.size
        if iw <= 0 or ih <= 0:
            raise ValueError("invalid image size")
        scale = max(box_w / iw, box_h / ih)
        nw, nh = math.ceil(iw * scale), math.ceil(ih * scale)
        img = img.resize((nw, nh), LANCZOS)
        x = (nw - box_w) // 2
        y = (nh - box_h) // 2
        return img.crop((x, y, x + box_w, y + box_h))

    @staticmethod
    def _rounded_image(image: Image.Image, radius: int) -> Image.Image:
        img = image.convert("RGBA")
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, img.size[0] - 1, img.size[1] - 1), radius=radius, fill=255
        )
        img.putalpha(mask)
        return img

    @staticmethod
    def _circle_avatar(image: Image.Image, size: int) -> Image.Image:
        img = image.convert("RGBA").resize((size, size), LANCZOS)
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
        img.putalpha(mask)
        return img

    @staticmethod
    def _gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
        w, h = size
        grad = Image.new("RGB", (1, max(h, 1)))
        for y in range(max(h, 1)):
            ratio = y / max(h - 1, 1)
            color = tuple(round(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3))
            grad.putpixel((0, y), color)
        return grad.resize((w, h))

    # ---------- 毛玻璃与光影 ----------

    @staticmethod
    def _glass(
        canvas: Image.Image,
        box: tuple[int, int, int, int],
        radius: int,
        tint_rgb: tuple[int, int, int],
        tint_alpha: int,
        border_rgb: tuple[int, int, int],
        border_alpha: int,
        blur: int = L.GLASS_BLUR,
    ) -> None:
        """在画布指定区域绘制毛玻璃圆角块（真实背景模糊 +  tint + 细描边）。"""
        x0, y0, x1, y1 = box
        if x1 <= x0 or y1 <= y0:
            return
        region = canvas.crop(box).filter(ImageFilter.GaussianBlur(blur))
        region.alpha_composite(
            Image.new("RGBA", region.size, (*tint_rgb, tint_alpha))
        )
        mask = Image.new("L", region.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, region.size[0] - 1, region.size[1] - 1), radius=radius, fill=255
        )
        canvas.paste(region, (x0, y0), mask)
        if border_alpha > 0:
            # 描边先画到透明层再混合，避免直接 Draw 替换像素产生半透明空洞
            border_layer = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
            ImageDraw.Draw(border_layer).rounded_rectangle(
                (0, 0, x1 - x0 - 1, y1 - y0 - 1), radius=radius,
                outline=(*border_rgb, border_alpha), width=1,
            )
            canvas.alpha_composite(border_layer, (x0, y0))

    @staticmethod
    def _radial_glow(
        w: int, h: int, rgb: tuple[int, int, int], alpha: int
    ) -> Image.Image:
        """生成一团柔和的径向光晕（品牌色渗透渐变用）。"""
        base = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(base).ellipse(
            (-w // 3, -h // 2, w // 2, h // 2), fill=(*rgb, alpha)
        )
        return base.filter(ImageFilter.GaussianBlur(max(w, h) // 5))

    @staticmethod
    def _scrim(
        w: int,
        h: int,
        *,
        start: float,
        max_alpha: int,
        power: float = 1.6,
        invert: bool = False,
    ) -> Image.Image:
        """生成垂直渐变黑色遮罩。invert=True 时从顶部开始衰减。"""
        mask = Image.new("L", (1, max(h, 1)))
        for yy in range(max(h, 1)):
            t = yy / max(h - 1, 1)
            if invert:
                ratio = max(0.0, 1.0 - t / max(start, 1e-6))
            else:
                ratio = max(0.0, (t - start) / max(1.0 - start, 1e-6))
            alpha = int(max_alpha * (ratio ** power))
            mask.putpixel((0, yy), min(255, alpha))
        mask = mask.resize((w, h))
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 255))
        layer.putalpha(mask)
        return layer

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
        digest = hashlib.md5(
            f"{self.theme_name}|{self.width}|{self.layout_name}|{self.cover_full_size}|{payload}|{warnings_str}".encode("utf-8")
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

    # ---------- 布局辅助 ----------

    @staticmethod
    def _rounded_image_top(image: Image.Image, radius: int) -> Image.Image:
        """仅保留顶部圆角的图片（用于全宽横幅）。"""
        img = image.convert("RGBA")
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, img.size[0] - 1, img.size[1] - 1), radius=radius,
            corners=(True, True, False, False), fill=255,
        )
        img.putalpha(mask)
        return img

    def _grid_metrics(
        self, n: int, inner_w: int, gap: int
    ) -> tuple[int, int, int, int]:
        """计算图集网格的 (总高度, 列数, 行数, 单元格边长)。"""
        if n <= 0:
            return 0, 0, 0, 0
        if n == 1:
            cols, rows, cell_h = 1, 1, min(inner_w, L.GRID_SINGLE_MAX)
        elif n == 2:
            cols, rows, cell_h = 2, 1, (inner_w - gap) // 2
        elif n == 3:
            cols, rows, cell_h = 3, 1, (inner_w - gap * 2) // 3
        elif n == 4:
            cols, rows, cell_h = 2, 2, (inner_w - gap) // 2
        else:
            cols, rows, cell_h = 3, 2, (inner_w - gap * 2) // 3
        grid_h = rows * cell_h + (rows - 1) * gap
        return grid_h, cols, rows, cell_h

    def _stat_pill_width(self, label: str, value: str) -> int:
        """统计药丸宽度：水平内边距 + 标签 + 间距 + 数值。"""
        w = L.STAT_PAD_X * 2
        w += self._text_width(label, self._font(L.F_STAT_LABEL))
        if value:
            w += L.STAT_LABEL_VALUE_GAP
            w += self._text_width(value, self._font(L.F_STAT_VALUE, bold=True))
        return w

    def _build_stat_rows(
        self, stats: list[tuple[str, str]], inner_w: int
    ) -> list[list[tuple[str, str]]]:
        """将统计项按宽度拆分为多行徽章。"""
        rows: list[list[tuple[str, str]]] = []
        if not stats:
            return rows
        pills: list[tuple[str, str]] = []
        row_w = 0
        for label, value in stats:
            w = self._stat_pill_width(label, value)
            if pills and row_w + w + L.STAT_GAP > inner_w:
                rows.append(pills)
                pills = []
                row_w = 0
            pills.append((label, value))
            row_w += w + L.STAT_GAP
        if pills:
            rows.append(pills)
        return rows

    def _platform_pill_width(self, text: str) -> int:
        """平台徽标（accent 圆点 + 平台名）宽度。"""
        font = self._font(L.F_PLATFORM, bold=True)
        return 18 + 12 + 8 + self._text_width(text, font) + 18

    # ---------- 同步绘制 ----------

    def _render_sync(
        self,
        result: ParseResult,
        images: dict[str, Any],
        out_path: Path,
    ) -> Path:
        """按 self.layout_name 分发到具体布局实现。"""
        if self.layout_name == "magazine":
            return self._render_magazine(result, images, out_path)
        if self.layout_name == "immersive":
            return self._render_immersive(result, images, out_path)
        if self.layout_name == "feed":
            return self._render_feed(result, images, out_path)
        return self._render_standard(result, images, out_path)

    def _render_standard(
        self,
        result: ParseResult,
        images: dict[str, Any],
        out_path: Path,
    ) -> Path:
        """标准布局：顶部全宽横幅 + 纵向信息流。"""
        theme = THEMES[self.theme_name]
        accent = PLATFORM_COLORS.get(result.platform.name, PLATFORM_COLORS["default"])
        accent_rgb = hex_to_rgb(accent)

        pad = L.PAD
        inner_w = self.width - pad * 2
        gap = L.GRID_GAP

        # ================= 数据准备 =================
        is_video_hero = images.get("hero") is not None
        hero = images.get("hero")
        grid = list(images.get("grid") or [])
        if hero is None and grid:
            # 没有视频封面时，用图集首图作为顶部横幅
            hero = grid.pop(0)
        hero_h = round(self.width * L.HERO_RATIO) if hero else 0
        if hero and self.cover_full_size:
            hero_h = self._hero_aspect_height(hero, self.width, hero_h)

        grid_h, cols, rows, cell_h = self._grid_metrics(len(grid), inner_w, gap)

        # 头部文字
        platform_text = result.platform.display_name
        platform_pill_w = self._platform_pill_width(platform_text)

        content_type = result.content_type or "动态"
        chip_font = self._font(L.F_CHIP, bold=True)
        type_pill_w = self._text_width(content_type, chip_font) + 36

        ts = format_timestamp(result.timestamp)
        ts_font = self._font(L.F_TIME)

        # 标题
        title_font = self._font(L.F_TITLE, bold=True)
        title = strip_emoji(result.title)
        title_lines: list[str] = []
        if title:
            title_lines = self._fit_lines(
                title, title_font, inner_w, 2 if hero else 3
            )

        # 简介
        desc_font = self._font(L.F_DESC)
        text = strip_emoji(result.text)
        desc_lines: list[str] = []
        if text:
            desc_lines = self._fit_lines(text, desc_font, inner_w, 6)

        # 作者
        author = result.author
        avatar_size = L.AVATAR
        name = strip_emoji(author.name) or "未知作者" if author else ""
        author_desc = one_line(author.description)[:40] if author else ""

        # 统计（时长并入统计徽章）
        stats = parse_stats_line(result.extra.get("stats_line"))
        if dur := result.extra.get("duration"):
            stats.insert(0, ("时长", str(dur)))
        online_text = strip_emoji(result.extra.get("online") or "")
        limit_warnings = result.extra.get("limit_warnings") or []
        warnings_h = self._warning_block_height(limit_warnings, inner_w)
        stat_rows = self._build_stat_rows(stats, inner_w)

        quote_h = self._measure_quote(result.repost, inner_w) if result.repost else 0

        # ================= 高度计算 =================
        if hero:
            y = hero_h + 20
        else:
            y = L.HEAD_BAR_TOP + L.HEAD_BAR_H + 18 + L.HEAD_PILL_H + 18
        if author:
            y += avatar_size + 20
        else:
            y += 12
        if not hero and title_lines:
            y += len(title_lines) * L.F_TITLE_LINE_H + 14
        if desc_lines:
            y += len(desc_lines) * L.F_DESC_LINE_H + 16
        if stat_rows:
            y += len(stat_rows) * (L.STAT_H + L.STAT_ROW_GAP) - L.STAT_ROW_GAP + 18
        if online_text:
            y += 38
        if warnings_h:
            y += warnings_h + 16
        if grid:
            y += grid_h + 16
        if quote_h:
            y += quote_h + 16
        y += L.FOOTER_H
        card_h = y
        total_h = card_h + 14

        # ================= 绘制底层 =================
        canvas = Image.new("RGBA", (self.width, total_h), (0, 0, 0, 0))

        # 阴影
        shadow = Image.new("RGBA", (self.width, total_h), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            (L.SHADOW_INSET, L.SHADOW_INSET, self.width - L.SHADOW_INSET, total_h - 2),
            radius=L.RADIUS + 2,
            fill=(0, 0, 0, theme.shadow_alpha),
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(L.SHADOW_BLUR))
        canvas.alpha_composite(shadow)

        # 卡片主体（垂直渐变 + 品牌色渗透光晕 + 圆角）
        grad = self._gradient(
            (self.width, card_h), theme.gradient_top, theme.gradient_bottom
        )
        glow = self._radial_glow(self.width, round(self.width * 0.9), accent_rgb, theme.glow_alpha)
        grad_rgba = grad.convert("RGBA")
        # 光晕与卡片同宽并从 (0,0) 覆盖，避免图层左缘产生内部接缝
        grad_rgba.alpha_composite(glow, (0, 0))
        mask = Image.new("L", (self.width, card_h), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, self.width - 1, card_h - 1), radius=L.RADIUS, fill=255
        )
        card = grad_rgba
        card.putalpha(mask)
        canvas.alpha_composite(card, (0, 0))

        draw = ImageDraw.Draw(canvas)
        # 卡片描边同样先画到透明层再混合，保证输出像素不透明
        border_layer = Image.new("RGBA", (self.width, card_h), (0, 0, 0, 0))
        ImageDraw.Draw(border_layer).rounded_rectangle(
            (0, 0, self.width - 1, card_h - 1), radius=L.RADIUS,
            outline=with_alpha(theme.border, theme.border_alpha), width=1,
        )
        canvas.alpha_composite(border_layer, (0, 0))

        y = 0
        if hero:
            # ============ 顶部横幅 ============
            hero_img = None
            try:
                hero_img = self._cover_fit(self._open_image(hero), self.width, hero_h)
                hero_img = self._rounded_image_top(hero_img, L.RADIUS)
            except Exception:
                hero_img = None
                logger.warning("横幅图片渲染失败，使用占位背景", exc_info=True)
            if hero_img is not None:
                canvas.alpha_composite(hero_img, (0, 0))
            else:
                ph = self._gradient(
                    (self.width, hero_h),
                    theme.placeholder_top, theme.placeholder_bottom,
                ).convert("RGBA")
                tint = Image.new(
                    "RGBA", (self.width, hero_h), (*accent_rgb, 40)
                )
                ph.alpha_composite(tint)
                ph = self._rounded_image_top(ph, L.RADIUS)
                canvas.alpha_composite(ph, (0, 0))

            # 柔和渐变 scrim：顶部保证徽章可读，底部保证标题可读
            canvas.alpha_composite(
                self._scrim(
                    self.width, hero_h,
                    start=L.TOP_SCRIM_END, max_alpha=L.TOP_SCRIM_ALPHA,
                    power=1.4, invert=True,
                ),
                (0, 0),
            )
            canvas.alpha_composite(
                self._scrim(
                    self.width, hero_h,
                    start=L.SCRIM_START, max_alpha=L.SCRIM_ALPHA,
                    power=L.SCRIM_POWER,
                ),
                (0, 0),
            )

            # 悬浮徽章组：平台徽标 + 类型 chip（毛玻璃）
            badge_y = L.HERO_BADGE_TOP
            badge_h = L.HERO_BADGE_H
            self._draw_hero_badge(
                canvas, pad, badge_y, badge_h, platform_pill_w,
                text=platform_text, accent_rgb=accent_rgb, dot=True,
                font_size=L.F_PLATFORM,
            )
            chip_x = pad + platform_pill_w + L.HERO_BADGE_GAP
            self._draw_hero_badge(
                canvas, chip_x, badge_y, badge_h, type_pill_w,
                text=content_type, accent_rgb=accent_rgb, dot=False,
                font_size=L.F_CHIP,
            )
            if ts:
                ts_w = self._text_width(ts, ts_font) + 32
                ts_x = self.width - pad - ts_w
                self._draw_hero_badge(
                    canvas, ts_x, badge_y, badge_h, ts_w,
                    text=ts, accent_rgb=accent_rgb, dot=False,
                    font_size=L.F_TIME, bold=False,
                )

            # 视频播放按钮（毛玻璃圆环）
            if is_video_hero:
                play_r = L.PLAY_R
                cx, cy = self.width // 2, hero_h // 2
                box = (cx - play_r, cy - play_r, cx + play_r, cy + play_r)
                self._glass(
                    canvas, box, play_r,
                    tint_rgb=(255, 255, 255), tint_alpha=34,
                    border_rgb=(255, 255, 255), border_alpha=110,
                    blur=8,
                )
                pd = ImageDraw.Draw(canvas)
                pd.polygon(
                    [
                        (cx - 12, cy - 18),
                        (cx - 12, cy + 18),
                        (cx + 20, cy),
                    ],
                    fill=(255, 255, 255, 245),
                )

            # 标题白色浮层（柔和投影 + 轻描边）
            if title_lines:
                ty = hero_h - len(title_lines) * L.F_TITLE_LINE_H - L.HERO_TITLE_BOTTOM
                shadow_layer = Image.new("RGBA", (self.width, hero_h), (0, 0, 0, 0))
                sd = ImageDraw.Draw(shadow_layer)
                sy = ty
                for line in title_lines:
                    self._draw_text(
                        sd, (pad, sy + 2), line, L.F_TITLE,
                        (0, 0, 0, 140), bold=True,
                    )
                    sy += L.F_TITLE_LINE_H
                canvas.alpha_composite(
                    shadow_layer.filter(ImageFilter.GaussianBlur(4)), (0, 0)
                )
                # 标题与描边画到独立层后整体混合，避免半透明描边像素直接替换
                text_layer = Image.new("RGBA", (self.width, hero_h), (0, 0, 0, 0))
                td = ImageDraw.Draw(text_layer)
                for line in title_lines:
                    self._draw_text(
                        td, (pad, ty), line, L.F_TITLE,
                        (255, 255, 255, 255), bold=True,
                        stroke_width=1, stroke_fill=(0, 0, 0, 80),
                    )
                    ty += L.F_TITLE_LINE_H
                canvas.alpha_composite(text_layer, (0, 0))
                draw = ImageDraw.Draw(canvas)
            y = hero_h + 20
        else:
            # ============ 纯文本卡片头部 ============
            # accent 短横条（品牌色渐变淡出）
            bar = Image.new("RGBA", (L.HEAD_BAR_W, L.HEAD_BAR_H), (0, 0, 0, 0))
            for xx in range(L.HEAD_BAR_W):
                a = int(230 * (1 - xx / max(L.HEAD_BAR_W - 1, 1)) ** 1.3)
                ImageDraw.Draw(bar).line(
                    [(xx, 0), (xx, L.HEAD_BAR_H)], fill=(*accent_rgb, a)
                )
            bar = self._rounded_image(bar, L.HEAD_BAR_H // 2)
            canvas.alpha_composite(bar, (pad, L.HEAD_BAR_TOP))

            y = L.HEAD_BAR_TOP + L.HEAD_BAR_H + 18
            # 平台徽标（毛玻璃 + accent 圆点）
            self._draw_flat_badge(
                canvas, theme, pad, y, L.HEAD_PILL_H, platform_pill_w,
                text=platform_text, accent_rgb=accent_rgb, dot=True,
                font_size=L.F_PLATFORM, bold=True, text_rgb=theme.text_primary,
            )
            # 类型与时间弱化为辅助文字
            type_x = pad + platform_pill_w + 16
            type_lh = self._line_height(chip_font)
            self._draw_text(
                draw,
                (type_x, y + (L.HEAD_PILL_H - type_lh) // 2),
                content_type, L.F_CHIP, theme.text_tertiary, bold=True,
            )
            if ts:
                ts_w = self._text_width(ts, ts_font)
                ts_lh = self._line_height(ts_font)
                self._draw_text(
                    draw,
                    (self.width - pad - ts_w, y + (L.HEAD_PILL_H - ts_lh) // 2),
                    ts, L.F_TIME, theme.text_tertiary,
                )
            y += L.HEAD_PILL_H + 18

        # ============ 作者行 ============
        if author:
            avatar_path = images.get("avatar")
            avatar = None
            if avatar_path:
                try:
                    avatar = self._circle_avatar(
                        self._open_image(avatar_path), avatar_size
                    )
                except Exception:
                    avatar = None
            if avatar is not None:
                canvas.alpha_composite(avatar, (pad, y))
                ring = Image.new("RGBA", (avatar_size, avatar_size), (0, 0, 0, 0))
                ImageDraw.Draw(ring).ellipse(
                    (1, 1, avatar_size - 2, avatar_size - 2),
                    outline=with_alpha(accent_rgb, 170), width=L.AVATAR_RING_W,
                )
                canvas.alpha_composite(ring, (pad, y))
            else:
                # 无头像时绘制 accent 渐变首字母占位圆
                placeholder = self._gradient(
                    (avatar_size, avatar_size),
                    accent_rgb, mix(accent_rgb, (0, 0, 0), 0.35),
                ).convert("RGBA")
                pmask = Image.new("L", (avatar_size, avatar_size), 0)
                ImageDraw.Draw(pmask).ellipse(
                    (0, 0, avatar_size - 1, avatar_size - 1), fill=255
                )
                placeholder.putalpha(pmask)
                canvas.alpha_composite(placeholder, (pad, y))
                first = name[:1].upper()
                f_font = self._font(L.F_INITIAL, bold=True)
                fw = self._text_width(first, f_font)
                self._draw_text(
                    draw,
                    (pad + (avatar_size - fw) // 2, y + (avatar_size - self._line_height(f_font)) // 2),
                    first, L.F_INITIAL, "#FFFFFF", bold=True,
                )
            name_x = pad + avatar_size + 20
            self._draw_text(
                draw, (name_x, y + 6), name, L.F_NAME, theme.text_primary, bold=True
            )
            if author_desc:
                self._draw_text(
                    draw, (name_x, y + avatar_size - 26),
                    author_desc, L.F_SIGN, theme.text_tertiary,
                )
            y += avatar_size + 20
        else:
            y += 12

        # ============ 标题（非横幅模式） ============
        if not hero and title_lines:
            for line in title_lines:
                self._draw_text(
                    draw, (pad, y), line, L.F_TITLE, theme.text_primary, bold=True
                )
                y += L.F_TITLE_LINE_H
            y += 14

        # ============ 简介 ============
        if desc_lines:
            for line in desc_lines:
                self._draw_text(draw, (pad, y), line, L.F_DESC, theme.text_secondary)
                y += L.F_DESC_LINE_H
            y += 16

        # ============ 统计徽章（毛玻璃药丸：标签弱化 + 数值强调） ============
        if stat_rows:
            label_font = self._font(L.F_STAT_LABEL)
            value_font = self._font(L.F_STAT_VALUE, bold=True)
            for row in stat_rows:
                x = pad
                for label, value in row:
                    w = self._stat_pill_width(label, value)
                    self._glass(
                        canvas, (x, y, x + w, y + L.STAT_H), L.STAT_H // 2,
                        tint_rgb=theme.stat_pill_bg, tint_alpha=theme.frost_alpha,
                        border_rgb=theme.stat_pill_bg,
                        border_alpha=theme.frost_border_alpha,
                        blur=6,
                    )
                    label_w = self._text_width(label, label_font)
                    tx = x + L.STAT_PAD_X
                    if value:
                        self._draw_text(
                            draw,
                            (tx, y + (L.STAT_H - self._line_height(label_font)) // 2),
                            label, L.F_STAT_LABEL, theme.text_tertiary,
                        )
                        self._draw_text(
                            draw,
                            (tx + label_w + L.STAT_LABEL_VALUE_GAP,
                             y + (L.STAT_H - self._line_height(value_font)) // 2),
                            value, L.F_STAT_VALUE, theme.text_primary, bold=True,
                        )
                    else:
                        self._draw_text(
                            draw,
                            (tx, y + (L.STAT_H - self._line_height(label_font)) // 2),
                            label, L.F_STAT_LABEL, theme.text_secondary,
                        )
                    x += w + L.STAT_GAP
                y += L.STAT_H + L.STAT_ROW_GAP
            y += 18 - L.STAT_ROW_GAP

        # ============ 在线人数（accent 圆点 + 文字） ============
        if online_text:
            online_font = self._font(L.F_ONLINE)
            if self._text_width(online_text, online_font) <= inner_w - 18:
                dot_r = 4
                dot_cy = y + self._line_height(online_font) // 2
                draw.ellipse(
                    (pad, dot_cy - dot_r, pad + dot_r * 2, dot_cy + dot_r),
                    fill=accent,
                )
                self._draw_text(
                    draw, (pad + 18, y), online_text, L.F_ONLINE, accent
                )
            y += 38

        # ============ 警告提示块 ============
        if limit_warnings:
            y = self._draw_warning_block(canvas, draw, theme, limit_warnings, y, inner_w) + 16
            draw = ImageDraw.Draw(canvas)

        # ============ 图集网格 ============
        if grid:
            try:
                show = cols * rows
                over = len(grid) - show if len(grid) > show else 0
                for idx, path in enumerate(grid[:show]):
                    r, c = divmod(idx, cols)
                    x = pad + c * (cell_h + gap)
                    yy = y + r * (cell_h + gap)
                    try:
                        img = self._cover_fit(self._open_image(path), cell_h, cell_h)
                        img = self._rounded_image(img, L.GRID_RADIUS)
                        canvas.alpha_composite(img, (x, yy))
                    except Exception:
                        ph_layer = Image.new(
                            "RGBA", (cell_h, cell_h), (0, 0, 0, 0)
                        )
                        ImageDraw.Draw(ph_layer).rounded_rectangle(
                            (0, 0, cell_h - 1, cell_h - 1), radius=L.GRID_RADIUS,
                            fill=with_alpha(theme.pill_bg, 14),
                        )
                        canvas.alpha_composite(ph_layer, (x, yy))
                    if idx == show - 1 and over > 0:
                        canvas.alpha_composite(
                            self._scrim(
                                cell_h, cell_h, start=0.0, max_alpha=150, power=1.2
                            ),
                            (x, yy),
                        )
                        plus_font = self._font(L.F_PLUS, bold=True)
                        plus_text = f"+{over}"
                        pw = self._text_width(plus_text, plus_font)
                        self._draw_text(
                            draw,
                            (x + (cell_h - pw) // 2, yy + (cell_h - self._line_height(plus_font)) // 2),
                            plus_text, L.F_PLUS, "#FFFFFF", bold=True,
                        )
                y += grid_h + 20
            except Exception:
                logger.warning("图集渲染失败，已跳过", exc_info=True)
                y -= grid_h + 20

        # ============ 转发引用（毛玻璃容器 + accent 竖条） ============
        if result.repost and quote_h:
            qy = y
            self._glass(
                canvas, (pad, qy, pad + inner_w, qy + quote_h), L.QUOTE_RADIUS,
                tint_rgb=theme.quote_bg, tint_alpha=theme.frost_alpha,
                border_rgb=theme.quote_bg, border_alpha=theme.frost_border_alpha,
                blur=6,
            )
            bar_layer = Image.new(
                "RGBA", (L.QUOTE_BAR_W + 2, quote_h - 32), (0, 0, 0, 0)
            )
            ImageDraw.Draw(bar_layer).rounded_rectangle(
                (0, 0, L.QUOTE_BAR_W + 1, quote_h - 33),
                radius=L.QUOTE_BAR_W // 2,
                fill=with_alpha(accent_rgb, 230),
            )
            canvas.alpha_composite(bar_layer, (pad + 18, qy + 16))
            self._draw_quote_text(
                draw, result.repost, pad + 18 + L.QUOTE_BAR_W + 16, qy + 16,
                inner_w - 18 * 2 - L.QUOTE_BAR_W - 16, theme,
            )
            y += quote_h + 20

        # ============ 页脚（链接 + 「莉卡解析」徽标水印） ============
        divider_layer = Image.new("RGBA", (inner_w, 1), (0, 0, 0, 0))
        ImageDraw.Draw(divider_layer).line(
            (0, 0, inner_w - 1, 0),
            fill=with_alpha(theme.divider, 14 if self.theme_name == "dark" else 12),
            width=1,
        )
        canvas.alpha_composite(divider_layer, (pad, y + 12))
        foot_y = y + 28

        wm_text = "莉卡解析"
        wm_font = self._font(L.F_FOOT, bold=True)
        wm_text_w = self._text_width(wm_text, wm_font)
        wm_lh = self._line_height(wm_font)
        dot_d = L.WM_DOT
        wm_group_w = dot_d + L.WM_DOT_GAP + wm_text_w
        wm_x = self.width - pad - wm_group_w
        # 水印：accent 小圆点 + 文字
        dot_cy = foot_y + wm_lh // 2
        draw.ellipse(
            (wm_x, dot_cy - dot_d // 2, wm_x + dot_d, dot_cy + dot_d // 2),
            fill=(*accent_rgb, 255),
        )
        self._draw_text(
            draw, (wm_x + dot_d + L.WM_DOT_GAP, foot_y),
            wm_text, L.F_FOOT, accent, bold=True,
        )

        url_text = short_url(result.url)
        if url_text:
            url_font = self._font(L.F_FOOT)
            avail_w = wm_x - pad - 20
            while url_text and self._text_width(url_text, url_font) > avail_w:
                url_text = url_text[:-1]
            if url_text:
                self._draw_text(
                    draw, (pad, foot_y), url_text, L.F_FOOT, theme.text_tertiary
                )

        # ---------- 保存 ----------
        out_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(out_path, "PNG", optimize=True)
        return out_path

    # ---------- 徽章组件 ----------

    def _draw_hero_badge(
        self,
        canvas: Image.Image,
        x: int,
        y: int,
        h: int,
        w: int,
        *,
        text: str,
        accent_rgb: tuple[int, int, int],
        dot: bool,
        font_size: int,
        bold: bool = True,
    ) -> None:
        """横幅上的毛玻璃徽章（可选 accent 圆点），文字恒为白色。"""
        self._glass(
            canvas, (x, y, x + w, y + h), h // 2,
            tint_rgb=L.HERO_GLASS_TINT, tint_alpha=L.HERO_GLASS_TINT_ALPHA,
            border_rgb=(255, 255, 255), border_alpha=L.HERO_GLASS_BORDER_ALPHA,
        )
        draw = ImageDraw.Draw(canvas)
        font = self._font(font_size, bold)
        tx = x + 18
        if dot:
            dot_r = 6
            dot_cy = y + h // 2
            draw.ellipse(
                (tx, dot_cy - dot_r, tx + dot_r * 2, dot_cy + dot_r),
                fill=(*accent_rgb, 255),
            )
            tx += dot_r * 2 + 8
        self._draw_text(
            draw, (tx, y + (h - self._line_height(font)) // 2),
            text, font_size, "#FFFFFF", bold=bold,
        )

    def _draw_flat_badge(
        self,
        canvas: Image.Image,
        theme: Theme,
        x: int,
        y: int,
        h: int,
        w: int,
        *,
        text: str,
        accent_rgb: tuple[int, int, int],
        dot: bool,
        font_size: int,
        bold: bool,
        text_rgb: tuple[int, int, int],
    ) -> None:
        """卡片主体上的毛玻璃徽章（主题感知配色）。"""
        self._glass(
            canvas, (x, y, x + w, y + h), h // 2,
            tint_rgb=theme.pill_bg, tint_alpha=theme.frost_alpha,
            border_rgb=theme.pill_bg, border_alpha=theme.frost_border_alpha,
            blur=6,
        )
        draw = ImageDraw.Draw(canvas)
        font = self._font(font_size, bold)
        tx = x + 18
        if dot:
            dot_r = 6
            dot_cy = y + h // 2
            draw.ellipse(
                (tx, dot_cy - dot_r, tx + dot_r * 2, dot_cy + dot_r),
                fill=(*accent_rgb, 255),
            )
            tx += dot_r * 2 + 8
        self._draw_text(
            draw, (tx, y + (h - self._line_height(font)) // 2),
            text, font_size, text_rgb, bold=bold,
        )

    # ---------- 转发引用 ----------

    def _measure_quote(self, repost: ParseResult, inner_w: int) -> int:
        q_font = self._font(L.F_QUOTE)
        author = strip_emoji(repost.author.name) if repost.author else "原帖"
        text = strip_emoji(repost.title or repost.text or "")
        body = f"@{author}"
        if text:
            body += f"：{text}"
        max_w = inner_w - 18 * 2 - L.QUOTE_BAR_W - 16
        lines = self._fit_lines(body, q_font, max_w, 4)
        return max(80, len(lines) * L.F_QUOTE_LINE_H + 32)

    def _draw_quote_text(
        self,
        draw: Any,
        repost: ParseResult,
        x: int,
        y: int,
        max_width: int,
        theme: Theme,
    ) -> None:
        q_font = self._font(L.F_QUOTE)
        author = strip_emoji(repost.author.name) if repost.author else "原帖"
        text = strip_emoji(repost.title or repost.text or "")
        body = f"@{author}"
        if text:
            body += f"：{text}"
        lines = self._fit_lines(body, q_font, max_width, 4)
        for line in lines:
            self._draw_text(draw, (x, y), line, L.F_QUOTE, theme.text_secondary)
            y += L.F_QUOTE_LINE_H

    # ==================== 备选布局共享组件 ====================

    def _prep(self, result: ParseResult, images: dict[str, Any]) -> dict[str, Any]:
        """备选布局的公共数据准备。"""
        hero = images.get("hero")
        grid = list(images.get("grid") or [])
        if hero is None and grid:
            # 没有视频封面时，用图集首图作为视觉图
            hero = grid.pop(0)
        author = result.author
        stats = parse_stats_line(result.extra.get("stats_line"))
        if dur := result.extra.get("duration"):
            stats.insert(0, ("时长", str(dur)))
        return {
            "is_video_hero": images.get("hero") is not None,
            "hero": hero,
            "grid": grid,
            "platform_text": result.platform.display_name,
            "content_type": result.content_type or "动态",
            "ts": format_timestamp(result.timestamp),
            "title": strip_emoji(result.title),
            "text": strip_emoji(result.text),
            "author": author,
            "name": (strip_emoji(author.name) or "未知作者") if author else "",
            "author_desc": one_line(author.description)[:40] if author else "",
            "stats": stats,
            "online_text": strip_emoji(result.extra.get("online") or ""),
            "warnings": result.extra.get("limit_warnings") or [],
        }

    def _base_canvas(self, theme: Theme, accent_rgb: tuple[int, int, int], card_h: int):
        """阴影 + 渐变底 + 光晕 + 圆角 + 描边，返回 (canvas, draw)。"""
        total_h = card_h + 14
        canvas = Image.new("RGBA", (self.width, total_h), (0, 0, 0, 0))
        shadow = Image.new("RGBA", (self.width, total_h), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            (L.SHADOW_INSET, L.SHADOW_INSET, self.width - L.SHADOW_INSET, total_h - 2),
            radius=L.RADIUS + 2, fill=(0, 0, 0, theme.shadow_alpha),
        )
        canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(L.SHADOW_BLUR)))
        grad = self._gradient((self.width, card_h), theme.gradient_top, theme.gradient_bottom)
        grad_rgba = grad.convert("RGBA")
        glow = self._radial_glow(self.width, round(self.width * 0.9), accent_rgb, theme.glow_alpha)
        grad_rgba.alpha_composite(glow, (0, 0))
        mask = Image.new("L", (self.width, card_h), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, self.width - 1, card_h - 1), radius=L.RADIUS, fill=255
        )
        grad_rgba.putalpha(mask)
        canvas.alpha_composite(grad_rgba, (0, 0))
        border_layer = Image.new("RGBA", (self.width, card_h), (0, 0, 0, 0))
        ImageDraw.Draw(border_layer).rounded_rectangle(
            (0, 0, self.width - 1, card_h - 1), radius=L.RADIUS,
            outline=with_alpha(theme.border, theme.border_alpha), width=1,
        )
        canvas.alpha_composite(border_layer, (0, 0))
        return canvas, ImageDraw.Draw(canvas)

    def _header_badges(self, canvas, theme: Theme, accent_rgb, d: dict) -> int:
        """纯文本头部：accent 条 + 平台药丸 + 类型 + 时间，返回结束 y。"""
        pad = L.PAD
        bar = Image.new("RGBA", (L.HEAD_BAR_W, L.HEAD_BAR_H), (0, 0, 0, 0))
        for xx in range(L.HEAD_BAR_W):
            a = int(230 * (1 - xx / max(L.HEAD_BAR_W - 1, 1)) ** 1.3)
            ImageDraw.Draw(bar).line([(xx, 0), (xx, L.HEAD_BAR_H)], fill=(*accent_rgb, a))
        canvas.alpha_composite(self._rounded_image(bar, L.HEAD_BAR_H // 2), (pad, L.HEAD_BAR_TOP))
        y = L.HEAD_BAR_TOP + L.HEAD_BAR_H + 18
        pw = self._platform_pill_width(d["platform_text"])
        self._draw_flat_badge(
            canvas, theme, pad, y, L.HEAD_PILL_H, pw,
            text=d["platform_text"], accent_rgb=accent_rgb, dot=True,
            font_size=L.F_PLATFORM, bold=True, text_rgb=theme.text_primary,
        )
        chip_font = self._font(L.F_CHIP, bold=True)
        self._draw_text(
            ImageDraw.Draw(canvas),
            (pad + pw + 16, y + (L.HEAD_PILL_H - self._line_height(chip_font)) // 2),
            d["content_type"], L.F_CHIP, theme.text_tertiary, bold=True,
        )
        if d["ts"]:
            ts_font = self._font(L.F_TIME)
            ts_w = self._text_width(d["ts"], ts_font)
            self._draw_text(
                ImageDraw.Draw(canvas),
                (self.width - pad - ts_w, y + (L.HEAD_PILL_H - self._line_height(ts_font)) // 2),
                d["ts"], L.F_TIME, theme.text_tertiary,
            )
        return y + L.HEAD_PILL_H + 18

    def _avatar_block(self, canvas, draw, x: int, y: int, size: int,
                      images: dict, d: dict, accent_rgb) -> None:
        """绘制头像（含 accent 描边环或渐变首字母占位）。"""
        avatar_path = images.get("avatar")
        avatar = None
        if avatar_path:
            try:
                avatar = self._circle_avatar(self._open_image(avatar_path), size)
            except Exception:
                avatar = None
        if avatar is not None:
            canvas.alpha_composite(avatar, (x, y))
            ring = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            ImageDraw.Draw(ring).ellipse(
                (1, 1, size - 2, size - 2),
                outline=with_alpha(accent_rgb, 170), width=L.AVATAR_RING_W,
            )
            canvas.alpha_composite(ring, (x, y))
        else:
            placeholder = self._gradient(
                (size, size), accent_rgb, mix(accent_rgb, (0, 0, 0), 0.35)
            ).convert("RGBA")
            pmask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(pmask).ellipse((0, 0, size - 1, size - 1), fill=255)
            placeholder.putalpha(pmask)
            canvas.alpha_composite(placeholder, (x, y))
            first = d["name"][:1].upper()
            f_font = self._font(L.F_INITIAL, bold=True)
            fw = self._text_width(first, f_font)
            self._draw_text(
                ImageDraw.Draw(canvas),
                (x + (size - fw) // 2, y + (size - self._line_height(f_font)) // 2),
                first, L.F_INITIAL, "#FFFFFF", bold=True,
            )

    def _stat_rows_height(self, d: dict, inner_w: int):
        rows = self._build_stat_rows(d["stats"], inner_w)
        if not rows:
            return 0, []
        return len(rows) * (L.STAT_H + L.STAT_ROW_GAP) - L.STAT_ROW_GAP, rows

    def _draw_stat_rows(self, canvas, theme: Theme, rows, x0: int, y: int) -> int:
        """主题感知的统计药丸行，返回结束 y。"""
        label_font = self._font(L.F_STAT_LABEL)
        value_font = self._font(L.F_STAT_VALUE, bold=True)
        for row in rows:
            x = x0
            for label, value in row:
                w = self._stat_pill_width(label, value)
                self._glass(
                    canvas, (x, y, x + w, y + L.STAT_H), L.STAT_H // 2,
                    tint_rgb=theme.stat_pill_bg, tint_alpha=theme.frost_alpha,
                    border_rgb=theme.stat_pill_bg, border_alpha=theme.frost_border_alpha,
                    blur=6,
                )
                draw = ImageDraw.Draw(canvas)
                label_w = self._text_width(label, label_font)
                tx = x + L.STAT_PAD_X
                if value:
                    self._draw_text(draw, (tx, y + (L.STAT_H - self._line_height(label_font)) // 2),
                                    label, L.F_STAT_LABEL, theme.text_tertiary)
                    self._draw_text(draw, (tx + label_w + L.STAT_LABEL_VALUE_GAP,
                                           y + (L.STAT_H - self._line_height(value_font)) // 2),
                                    value, L.F_STAT_VALUE, theme.text_primary, bold=True)
                else:
                    self._draw_text(draw, (tx, y + (L.STAT_H - self._line_height(label_font)) // 2),
                                    label, L.F_STAT_LABEL, theme.text_secondary)
                x += w + L.STAT_GAP
            y += L.STAT_H + L.STAT_ROW_GAP
        return y - L.STAT_ROW_GAP

    def _draw_online(self, draw, d: dict, y: int, accent: str) -> int:
        """在线人数（accent 圆点 + 文字），返回结束 y。"""
        online_font = self._font(L.F_ONLINE)
        dot_cy = y + self._line_height(online_font) // 2
        draw.ellipse((L.PAD, dot_cy - 4, L.PAD + 8, dot_cy + 4), fill=accent)
        self._draw_text(draw, (L.PAD + 18, y), d["online_text"], L.F_ONLINE, accent)
        return y + 38

    def _warning_block_height(self, warnings: list[str], inner_w: int) -> int:
        """计算警告提示块的总高度。"""
        if not warnings:
            return 0
        font = self._font(20)
        line_h = self._line_height(font) + 4
        avail_w = inner_w - 46
        total_h = 0
        for raw_msg in warnings:
            msg = strip_emoji(raw_msg)
            lines = self._wrap(msg, font, avail_w)
            box_h = max(len(lines), 1) * line_h + 24
            total_h += box_h + 12
        return total_h - 12 if total_h > 0 else 0

    def _draw_warning_block(
        self, canvas: Image.Image, draw: ImageDraw.ImageDraw, theme: Theme,
        warnings: list[str], y: int, inner_w: int, on_image: bool = False
    ) -> int:
        """渲染精致的时长超出限制警告提示块，返回结束 y。"""
        if not warnings:
            return y
        pad = L.PAD
        font = self._font(20)
        line_h = self._line_height(font) + 4
        avail_w = inner_w - 46

        # 下移 8px：加大与上方“多少人观看”的间距，同时靠近下方分界线
        y += 8

        # 主题色彩适配：精致不张扬的琥珀警告色调
        if on_image:
            bg_rgb = (20, 24, 36)
            bg_alpha = 160
            border_rgb = (245, 158, 11)
            border_alpha = 75
            bar_rgb = (245, 158, 11, 230)
            text_color = (253, 230, 138)  # #FDE68A 柔金黄
        elif self.theme_name == "dark":
            bg_rgb = (245, 158, 11)
            bg_alpha = 22
            border_rgb = (245, 158, 11)
            border_alpha = 50
            bar_rgb = (245, 158, 11, 220)
            text_color = (252, 211, 77)   # #FCD34D 亮琥珀
        else:
            bg_rgb = (254, 243, 199)
            bg_alpha = 150
            border_rgb = (217, 119, 6)
            border_alpha = 60
            bar_rgb = (217, 119, 6, 220)
            text_color = (180, 83, 9)     # #B45309 深琥珀

        for raw_msg in warnings:
            msg = strip_emoji(raw_msg)
            lines = self._wrap(msg, font, avail_w)
            box_h = max(len(lines), 1) * line_h + 24

            # 毛玻璃圆角卡片底
            self._glass(
                canvas, (pad, y, pad + inner_w, y + box_h), 14,
                tint_rgb=bg_rgb, tint_alpha=bg_alpha,
                border_rgb=border_rgb, border_alpha=border_alpha, blur=6,
            )

            # 左侧 Warning Accent 竖条
            bar_layer = Image.new("RGBA", (4, max(box_h - 16, 8)), (0, 0, 0, 0))
            ImageDraw.Draw(bar_layer).rounded_rectangle(
                (0, 0, 3, max(box_h - 17, 7)), radius=2, fill=bar_rgb,
            )
            canvas.alpha_composite(bar_layer, (pad + 14, y + 8))

            # 警告文本
            draw = ImageDraw.Draw(canvas)
            ty = y + 12
            for line in lines:
                self._draw_text(draw, (pad + 28, ty), line, 20, text_color)
                ty += line_h

            y += box_h + 12

        return y - 24

    def _hero_aspect_height(self, hero_path: Path | None, box_w: int, default_h: int) -> int:
        """若开启了封面全尺寸模式 (cover_full_size)，按原图宽高比计算高度，否则使用 default_h。"""
        if not hero_path or not self.cover_full_size:
            return default_h
        try:
            with Image.open(hero_path) as im:
                w, h = im.size
                if w > 0 and h > 0:
                    return max(100, round(box_w * h / w))
        except Exception:
            pass
        return default_h

    def _footer_block(self, canvas, draw, theme: Theme, accent: str, accent_rgb,
                      result: ParseResult, y: int, inner_w: int,
                      on_image: bool = False) -> None:
        """页脚：分隔线 + 左链接 + 右「圆点 莉卡解析」水印。"""
        pad = L.PAD
        divider_layer = Image.new("RGBA", (inner_w, 1), (0, 0, 0, 0))
        ImageDraw.Draw(divider_layer).line(
            (0, 0, inner_w - 1, 0),
            fill=((255, 255, 255, 60) if on_image
                  else with_alpha(theme.divider, 14 if self.theme_name == "dark" else 12)),
            width=1,
        )
        canvas.alpha_composite(divider_layer, (pad, y + 12))
        foot_y = y + 28
        wm_font = self._font(L.F_FOOT, bold=True)
        wm_text_w = self._text_width("莉卡解析", wm_font)
        wm_group_w = L.WM_DOT + L.WM_DOT_GAP + wm_text_w
        wm_x = self.width - pad - wm_group_w
        wm_lh = self._line_height(wm_font)
        dot_cy = foot_y + wm_lh // 2
        draw.ellipse(
            (wm_x, dot_cy - L.WM_DOT // 2, wm_x + L.WM_DOT, dot_cy + L.WM_DOT // 2),
            fill=(*accent_rgb, 255),
        )
        self._draw_text(draw, (wm_x + L.WM_DOT + L.WM_DOT_GAP, foot_y),
                        "莉卡解析", L.F_FOOT, accent, bold=True)
        url_text = short_url(result.url)
        if url_text:
            url_font = self._font(L.F_FOOT)
            avail_w = wm_x - pad - 20
            while url_text and self._text_width(url_text, url_font) > avail_w:
                url_text = url_text[:-1]
            if url_text:
                color = (255, 255, 255, 160) if on_image else theme.text_tertiary
                self._draw_text(draw, (pad, foot_y), url_text, L.F_FOOT, color)

    def _draw_grid_block(self, canvas, draw, theme: Theme, grid: list,
                         y: int, inner_w: int, gap: int) -> int:
        """图集网格，返回结束 y（自带异常兜底）。"""
        pad = L.PAD
        grid_h, cols, rows, cell_h = self._grid_metrics(len(grid), inner_w, gap)
        if not grid_h:
            return y
        try:
            show = cols * rows
            over = len(grid) - show if len(grid) > show else 0
            for idx, path in enumerate(grid[:show]):
                r, c = divmod(idx, cols)
                x = pad + c * (cell_h + gap)
                yy = y + r * (cell_h + gap)
                try:
                    img = self._cover_fit(self._open_image(path), cell_h, cell_h)
                    img = self._rounded_image(img, L.GRID_RADIUS)
                    canvas.alpha_composite(img, (x, yy))
                except Exception:
                    ph = Image.new("RGBA", (cell_h, cell_h), (0, 0, 0, 0))
                    ImageDraw.Draw(ph).rounded_rectangle(
                        (0, 0, cell_h - 1, cell_h - 1), radius=L.GRID_RADIUS,
                        fill=with_alpha(theme.pill_bg, 14),
                    )
                    canvas.alpha_composite(ph, (x, yy))
                if idx == show - 1 and over > 0:
                    canvas.alpha_composite(
                        self._scrim(cell_h, cell_h, start=0.0, max_alpha=150, power=1.2),
                        (x, yy),
                    )
                    plus_font = self._font(L.F_PLUS, bold=True)
                    pw = self._text_width(f"+{over}", plus_font)
                    self._draw_text(
                        ImageDraw.Draw(canvas),
                        (x + (cell_h - pw) // 2, yy + (cell_h - self._line_height(plus_font)) // 2),
                        f"+{over}", L.F_PLUS, "#FFFFFF", bold=True,
                    )
            return y + grid_h + 20
        except Exception:
            logger.warning("图集渲染失败，已跳过", exc_info=True)
            return y

    def _draw_quote_block(self, canvas, draw, theme: Theme, accent_rgb,
                          result: ParseResult, y: int, inner_w: int) -> int:
        """转发引用（毛玻璃容器 + accent 竖条），返回结束 y。"""
        if not result.repost:
            return y
        pad = L.PAD
        quote_h = self._measure_quote(result.repost, inner_w)
        self._glass(
            canvas, (pad, y, pad + inner_w, y + quote_h), L.QUOTE_RADIUS,
            tint_rgb=theme.quote_bg, tint_alpha=theme.frost_alpha,
            border_rgb=theme.quote_bg, border_alpha=theme.frost_border_alpha, blur=6,
        )
        bar = Image.new("RGBA", (L.QUOTE_BAR_W, quote_h - 32), (0, 0, 0, 0))
        ImageDraw.Draw(bar).rounded_rectangle(
            (0, 0, L.QUOTE_BAR_W - 1, quote_h - 33), radius=L.QUOTE_BAR_W // 2,
            fill=(*accent_rgb, 230),
        )
        canvas.alpha_composite(bar, (pad + 18, y + 16))
        self._draw_quote_text(
            ImageDraw.Draw(canvas), result.repost,
            pad + 18 + L.QUOTE_BAR_W + 16, y + 16,
            inner_w - 18 * 2 - L.QUOTE_BAR_W - 16, theme,
        )
        return y + quote_h + 20

    # ==================== 布局：双栏杂志 ====================

    def _render_magazine(self, result, images, out_path) -> Path:
        """双栏杂志：封面缩为左侧方块，标题/作者在右侧栏。"""
        theme = THEMES[self.theme_name]
        accent = PLATFORM_COLORS.get(result.platform.name, PLATFORM_COLORS["default"])
        accent_rgb = hex_to_rgb(accent)
        pad = L.PAD
        inner_w = self.width - pad * 2
        gap = L.GRID_GAP
        d = self._prep(result, images)

        cover_w = round(inner_w * 0.42) if d["hero"] else 0
        cover_h = self._hero_aspect_height(d["hero"], cover_w, cover_w) if d["hero"] else 0
        right_x = pad + cover_w + 26
        right_w = inner_w - cover_w - 26 if d["hero"] else inner_w

        title_font = self._font(33, bold=True)
        title_lines = (
            self._fit_lines(d["title"], title_font, right_w, 4 if d["hero"] else 3)
            if d["title"] else []
        )
        desc_font = self._font(L.F_DESC)
        desc_lines = self._fit_lines(d["text"], desc_font, inner_w, 4) if d["text"] else []
        stats_h, stat_rows = self._stat_rows_height(d, inner_w)
        warnings_h = self._warning_block_height(d["warnings"], inner_w)
        grid_h = self._grid_metrics(len(d["grid"]), inner_w, gap)[0]
        quote_h = self._measure_quote(result.repost, inner_w) if result.repost else 0

        # ---- 高度 ----
        y = L.HEAD_BAR_TOP + L.HEAD_BAR_H + 18 + L.HEAD_PILL_H + 20
        if d["hero"]:
            right_h = len(title_lines) * 46 + (18 + 56 if d["author"] else 0)
            y += max(cover_h, right_h) + 22
        else:
            y += len(title_lines) * L.F_TITLE_LINE_H + 14
            if d["author"]:
                y += L.AVATAR + 20
        if desc_lines:
            y += len(desc_lines) * L.F_DESC_LINE_H + 16
        if stats_h:
            y += stats_h + 18
        if d["online_text"]:
            y += 38
        if warnings_h:
            y += warnings_h + 16
        if grid_h:
            y += grid_h + 20
        if quote_h:
            y += quote_h + 20
        y += L.FOOTER_H
        card_h = y

        canvas, draw = self._base_canvas(theme, accent_rgb, card_h)
        y = self._header_badges(canvas, theme, accent_rgb, d) + 2

        if d["hero"]:
            # 左侧封面方块
            try:
                img = self._cover_fit(self._open_image(d["hero"]), cover_w, cover_h)
                img = self._rounded_image(img, 20)
                canvas.alpha_composite(img, (pad, y))
            except Exception:
                ph = self._gradient(
                    (cover_w, cover_h), theme.placeholder_top, theme.placeholder_bottom
                ).convert("RGBA")
                ph.alpha_composite(Image.new("RGBA", (cover_w, cover_h), (*accent_rgb, 40)))
                canvas.alpha_composite(self._rounded_image(ph, 20), (pad, y))
            if d["is_video_hero"]:
                r_ = 38
                cx, cy = pad + cover_w // 2, y + cover_h // 2
                self._glass(canvas, (cx - r_, cy - r_, cx + r_, cy + r_), r_,
                            (255, 255, 255), 34, (255, 255, 255), 110, blur=8)
                ImageDraw.Draw(canvas).polygon(
                    [(cx - 10, cy - 15), (cx - 10, cy + 15), (cx + 17, cy)],
                    fill=(255, 255, 255, 245),
                )
            # 右栏：标题 + 作者
            ry = y + 4
            draw = ImageDraw.Draw(canvas)
            for line in title_lines:
                self._draw_text(draw, (right_x, ry), line, 33, theme.text_primary, bold=True)
                ry += 46
            if d["author"]:
                ry += 18
                self._avatar_block(canvas, draw, right_x, ry, 56, images, d, accent_rgb)
                draw = ImageDraw.Draw(canvas)
                self._draw_text(draw, (right_x + 72, ry + 2), d["name"], 24, theme.text_primary, bold=True)
                if d["author_desc"]:
                    self._draw_text(draw, (right_x + 72, ry + 56 - 22), d["author_desc"], 18, theme.text_tertiary)
            y += max(cover_h, len(title_lines) * 46 + (18 + 56 if d["author"] else 0)) + 22
        else:
            for line in title_lines:
                self._draw_text(draw, (pad, y), line, L.F_TITLE, theme.text_primary, bold=True)
                y += L.F_TITLE_LINE_H
            y += 14
            if d["author"]:
                self._avatar_block(canvas, draw, pad, y, L.AVATAR, images, d, accent_rgb)
                draw = ImageDraw.Draw(canvas)
                name_x = pad + L.AVATAR + 20
                self._draw_text(draw, (name_x, y + 6), d["name"], L.F_NAME, theme.text_primary, bold=True)
                if d["author_desc"]:
                    self._draw_text(draw, (name_x, y + L.AVATAR - 26), d["author_desc"], L.F_SIGN, theme.text_tertiary)
                y += L.AVATAR + 20

        if desc_lines:
            for line in desc_lines:
                self._draw_text(draw, (pad, y), line, L.F_DESC, theme.text_secondary)
                y += L.F_DESC_LINE_H
            y += 16
        if stat_rows:
            y = self._draw_stat_rows(canvas, theme, stat_rows, pad, y) + 18
            draw = ImageDraw.Draw(canvas)
        if d["online_text"]:
            y = self._draw_online(draw, d, y, accent)
        if d["warnings"]:
            y = self._draw_warning_block(canvas, draw, theme, d["warnings"], y, inner_w) + 16
            draw = ImageDraw.Draw(canvas)
        y = self._draw_grid_block(canvas, draw, theme, d["grid"], y, inner_w, gap)
        y = self._draw_quote_block(canvas, ImageDraw.Draw(canvas), theme, accent_rgb, result, y, inner_w)
        self._footer_block(canvas, ImageDraw.Draw(canvas), theme, accent, accent_rgb, result, y, inner_w)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(out_path, "PNG", optimize=True)
        return out_path

    # ==================== 布局：沉浸全屏 ====================

    def _render_immersive(self, result, images, out_path) -> Path:
        """沉浸全屏：封面铺满整卡，内容浮于渐变 scrim 上（无图回退标准布局）。"""
        if images.get("hero") is None and not images.get("grid"):
            return self._render_standard(result, images, out_path)

        theme = THEMES[self.theme_name]
        accent = PLATFORM_COLORS.get(result.platform.name, PLATFORM_COLORS["default"])
        accent_rgb = hex_to_rgb(accent)
        pad = L.PAD
        inner_w = self.width - pad * 2
        d = self._prep(result, images)

        title_font = self._font(L.F_TITLE, bold=True)
        title_lines = self._fit_lines(d["title"], title_font, inner_w, 2) if d["title"] else []
        stats_h, stat_rows = self._stat_rows_height(d, inner_w)
        warnings_h = self._warning_block_height(d["warnings"], inner_w)

        # 底部内容栈高度
        stack = 30
        if title_lines:
            stack += len(title_lines) * L.F_TITLE_LINE_H + 18
        if d["author"]:
            stack += 64 + 16
        if stats_h:
            stack += stats_h + 16
        if d["online_text"]:
            stack += 36
        if warnings_h:
            stack += warnings_h + 16
        stack += 96  # 页脚
        full_hero_h = self._hero_aspect_height(d["hero"], self.width, round(self.width * 1.02))
        card_h = max(full_hero_h, L.HERO_BADGE_TOP + L.HERO_BADGE_H + stack + 48)

        total_h = card_h + 14
        canvas = Image.new("RGBA", (self.width, total_h), (0, 0, 0, 0))
        shadow = Image.new("RGBA", (self.width, total_h), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            (L.SHADOW_INSET, L.SHADOW_INSET, self.width - L.SHADOW_INSET, total_h - 2),
            radius=L.RADIUS + 2, fill=(0, 0, 0, theme.shadow_alpha),
        )
        canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(L.SHADOW_BLUR)))

        # 封面铺满整卡
        try:
            img = self._cover_fit(self._open_image(d["hero"]), self.width, card_h)
            img = self._rounded_image(img, L.RADIUS)
            canvas.alpha_composite(img, (0, 0))
        except Exception:
            ph = self._gradient(
                (self.width, card_h), theme.placeholder_top, theme.placeholder_bottom
            ).convert("RGBA")
            ph.alpha_composite(Image.new("RGBA", (self.width, card_h), (*accent_rgb, 40)))
            canvas.alpha_composite(self._rounded_image(ph, L.RADIUS), (0, 0))

        # scrim：顶部徽章 + 底部内容区
        canvas.alpha_composite(
            self._scrim(self.width, card_h, start=0.22, max_alpha=110, power=1.4, invert=True), (0, 0)
        )
        content_top = card_h - stack
        scrim_start = max(0.0, (content_top - 70) / card_h)
        canvas.alpha_composite(
            self._scrim(self.width, card_h, start=scrim_start, max_alpha=225, power=1.5), (0, 0)
        )
        # 全卡极轻 accent 渗透
        tint_mask = self._scrim(self.width, card_h, start=0.0, max_alpha=26, power=1.0)
        tinted = Image.new("RGBA", (self.width, card_h), (*accent_rgb, 255))
        tinted.putalpha(tint_mask.split()[3])
        canvas.alpha_composite(tinted, (0, 0))

        draw = ImageDraw.Draw(canvas)
        # 顶部徽章
        pw = self._platform_pill_width(d["platform_text"])
        badge_y = L.HERO_BADGE_TOP
        self._draw_hero_badge(canvas, pad, badge_y, L.HERO_BADGE_H, pw,
                              text=d["platform_text"], accent_rgb=accent_rgb, dot=True,
                              font_size=L.F_PLATFORM)
        chip_font = self._font(L.F_CHIP, bold=True)
        type_w = self._text_width(d["content_type"], chip_font) + 36
        self._draw_hero_badge(canvas, pad + pw + L.HERO_BADGE_GAP, badge_y, L.HERO_BADGE_H, type_w,
                              text=d["content_type"], accent_rgb=accent_rgb, dot=False,
                              font_size=L.F_CHIP)
        if d["ts"]:
            ts_font = self._font(L.F_TIME)
            ts_w = self._text_width(d["ts"], ts_font) + 32
            self._draw_hero_badge(canvas, self.width - pad - ts_w, badge_y, L.HERO_BADGE_H, ts_w,
                                  text=d["ts"], accent_rgb=accent_rgb, dot=False,
                                  font_size=L.F_TIME, bold=False)

        # 播放按钮
        if d["is_video_hero"]:
            r_ = L.PLAY_R
            cx = self.width // 2
            cy = max(L.HERO_BADGE_TOP + L.HERO_BADGE_H + r_ + 20, content_top // 2 + 30)
            self._glass(canvas, (cx - r_, cy - r_, cx + r_, cy + r_), r_,
                        (255, 255, 255), 34, (255, 255, 255), 110, blur=8)
            ImageDraw.Draw(canvas).polygon(
                [(cx - 12, cy - 18), (cx - 12, cy + 18), (cx + 20, cy)],
                fill=(255, 255, 255, 245),
            )

        # ---- 底部内容栈（白色系文字） ----
        y = content_top + 10
        draw = ImageDraw.Draw(canvas)
        if title_lines:
            tl = Image.new("RGBA", (self.width, card_h), (0, 0, 0, 0))
            td = ImageDraw.Draw(tl)
            sy = y
            for line in title_lines:
                self._draw_text(td, (pad, sy + 2), line, L.F_TITLE,
                                (0, 0, 0, 130), bold=True)
                sy += L.F_TITLE_LINE_H
            canvas.alpha_composite(tl.filter(ImageFilter.GaussianBlur(4)), (0, 0))
            draw = ImageDraw.Draw(canvas)
            for line in title_lines:
                self._draw_text(draw, (pad, y), line, L.F_TITLE,
                                (255, 255, 255, 255), bold=True,
                                stroke_width=1, stroke_fill=(0, 0, 0, 70))
                y += L.F_TITLE_LINE_H
            y += 18
        if d["author"]:
            self._avatar_block(canvas, draw, pad, y, 64, images, d, accent_rgb)
            draw = ImageDraw.Draw(canvas)
            name_x = pad + 64 + 18
            self._draw_text(draw, (name_x, y + 6), d["name"], L.F_NAME, (255, 255, 255), bold=True)
            if d["author_desc"]:
                self._draw_text(draw, (name_x, y + 64 - 24), d["author_desc"], L.F_SIGN,
                                (255, 255, 255, 175))
            y += 64 + 16
        if stat_rows:
            label_font = self._font(L.F_STAT_LABEL)
            value_font = self._font(L.F_STAT_VALUE, bold=True)
            for row in stat_rows:
                x = pad
                for label, value in row:
                    w = self._stat_pill_width(label, value)
                    self._glass(canvas, (x, y, x + w, y + L.STAT_H), L.STAT_H // 2,
                                (255, 255, 255), 26, (255, 255, 255), 70, blur=8)
                    draw = ImageDraw.Draw(canvas)
                    label_w = self._text_width(label, label_font)
                    if value:
                        self._draw_text(draw, (x + L.STAT_PAD_X, y + (L.STAT_H - self._line_height(label_font)) // 2),
                                        label, L.F_STAT_LABEL, (255, 255, 255, 185))
                        self._draw_text(draw, (x + L.STAT_PAD_X + label_w + L.STAT_LABEL_VALUE_GAP,
                                               y + (L.STAT_H - self._line_height(value_font)) // 2),
                                        value, L.F_STAT_VALUE, (255, 255, 255), bold=True)
                    x += w + L.STAT_GAP
                y += L.STAT_H + L.STAT_ROW_GAP
            y += 16 - L.STAT_ROW_GAP
        if d["online_text"]:
            y = self._draw_online(draw, d, y, accent) - 2
        if d["warnings"]:
            y = self._draw_warning_block(canvas, draw, theme, d["warnings"], y, inner_w, on_image=True)
            draw = ImageDraw.Draw(canvas)
        self._footer_block(canvas, draw, theme, accent, accent_rgb, result, y, inner_w,
                           on_image=True)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(out_path, "PNG", optimize=True)
        return out_path

    # ==================== 布局：社交动态流 ====================

    def _render_feed(self, result, images, out_path) -> Path:
        """社交动态：作者行最前，媒体为内嵌圆角块。"""
        theme = THEMES[self.theme_name]
        accent = PLATFORM_COLORS.get(result.platform.name, PLATFORM_COLORS["default"])
        accent_rgb = hex_to_rgb(accent)
        pad = L.PAD
        inner_w = self.width - pad * 2
        gap = L.GRID_GAP
        d = self._prep(result, images)

        title_font = self._font(34, bold=True)
        title_lines = self._fit_lines(d["title"], title_font, inner_w, 3) if d["title"] else []
        desc_font = self._font(L.F_DESC)
        desc_lines = self._fit_lines(d["text"], desc_font, inner_w, 5) if d["text"] else []
        media_h = round(inner_w * 9 / 16) if d["hero"] else 0
        if d["hero"] and self.cover_full_size:
            media_h = self._hero_aspect_height(d["hero"], inner_w, media_h)
        stats_h, stat_rows = self._stat_rows_height(d, inner_w)
        warnings_h = self._warning_block_height(d["warnings"], inner_w)
        grid_h = self._grid_metrics(len(d["grid"]), inner_w, gap)[0]
        quote_h = self._measure_quote(result.repost, inner_w) if result.repost else 0

        # ---- 高度 ----
        y = 38
        if d["author"]:
            y += 68 + 20
        y += len(title_lines) * 48 + (12 if title_lines else 0)
        if desc_lines:
            y += len(desc_lines) * L.F_DESC_LINE_H + 16
        if media_h:
            y += media_h + 20
        if stats_h:
            y += stats_h + 18
        if d["online_text"]:
            y += 38
        if warnings_h:
            y += warnings_h + 16
        if grid_h:
            y += grid_h + 20
        if quote_h:
            y += quote_h + 20
        y += L.FOOTER_H
        card_h = y

        canvas, draw = self._base_canvas(theme, accent_rgb, card_h)

        # 作者行最前（无顶部 accent 条/头部徽章）
        y = 38
        if d["author"]:
            self._avatar_block(canvas, draw, pad, y, 68, images, d, accent_rgb)
            draw = ImageDraw.Draw(canvas)
            name_x = pad + 68 + 20
            name_font = self._font(26, bold=True)
            name_w = self._text_width(d["name"], name_font)
            self._draw_text(draw, (name_x, y + 8), d["name"], 26, theme.text_primary, bold=True)
            # 平台小药丸跟在昵称后
            pill_font = self._font(17, bold=True)
            pill_w = 12 + 8 + 6 + self._text_width(d["platform_text"], pill_font) + 12
            pill_h = 30
            pill_y = y + 8 + (self._line_height(name_font) - pill_h) // 2
            self._glass(canvas, (name_x + name_w + 12, pill_y,
                                 name_x + name_w + 12 + pill_w, pill_y + pill_h),
                        pill_h // 2, theme.pill_bg, theme.frost_alpha,
                        theme.pill_bg, theme.frost_border_alpha, blur=6)
            draw = ImageDraw.Draw(canvas)
            dot_cy = pill_y + pill_h // 2
            draw.ellipse((name_x + name_w + 24, dot_cy - 4, name_x + name_w + 32, dot_cy + 4),
                         fill=(*accent_rgb, 255))
            self._draw_text(draw, (name_x + name_w + 24 + 14,
                                   pill_y + (pill_h - self._line_height(pill_font)) // 2),
                            d["platform_text"], 17, theme.text_secondary, bold=True)
            if d["author_desc"]:
                self._draw_text(draw, (name_x, y + 68 - 26), d["author_desc"], L.F_SIGN,
                                theme.text_tertiary)
            if d["ts"]:
                ts_font = self._font(L.F_TIME)
                ts_w = self._text_width(d["ts"], ts_font)
                self._draw_text(draw, (self.width - pad - ts_w, y + 12), d["ts"], L.F_TIME,
                                theme.text_tertiary)
            y += 68 + 20

        for line in title_lines:
            self._draw_text(draw, (pad, y), line, 34, theme.text_primary, bold=True)
            y += 48
        if title_lines:
            y += 12
        for line in desc_lines:
            self._draw_text(draw, (pad, y), line, L.F_DESC, theme.text_secondary)
            y += L.F_DESC_LINE_H
        if desc_lines:
            y += 16

        # 媒体内嵌圆角块（类型 chip 浮在媒体角上）
        if d["hero"]:
            try:
                img = self._cover_fit(self._open_image(d["hero"]), inner_w, media_h)
                img = self._rounded_image(img, 20)
                canvas.alpha_composite(img, (pad, y))
            except Exception:
                ph = self._gradient(
                    (inner_w, media_h), theme.placeholder_top, theme.placeholder_bottom
                ).convert("RGBA")
                ph.alpha_composite(Image.new("RGBA", (inner_w, media_h), (*accent_rgb, 40)))
                canvas.alpha_composite(self._rounded_image(ph, 20), (pad, y))
            chip_font = self._font(18, bold=True)
            chip_w = self._text_width(d["content_type"], chip_font) + 28
            self._draw_hero_badge(canvas, pad + 14, y + 14, 34, chip_w,
                                  text=d["content_type"], accent_rgb=accent_rgb, dot=False,
                                  font_size=18)
            if d["is_video_hero"]:
                r_ = L.PLAY_R
                cx, cy = self.width // 2, y + media_h // 2
                self._glass(canvas, (cx - r_, cy - r_, cx + r_, cy + r_), r_,
                            (255, 255, 255), 34, (255, 255, 255), 110, blur=8)
                ImageDraw.Draw(canvas).polygon(
                    [(cx - 12, cy - 18), (cx - 12, cy + 18), (cx + 20, cy)],
                    fill=(255, 255, 255, 245),
                )
            y += media_h + 20
            draw = ImageDraw.Draw(canvas)

        if stat_rows:
            y = self._draw_stat_rows(canvas, theme, stat_rows, pad, y) + 18
            draw = ImageDraw.Draw(canvas)
        if d["online_text"]:
            y = self._draw_online(draw, d, y, accent)
        if d["warnings"]:
            y = self._draw_warning_block(canvas, draw, theme, d["warnings"], y, inner_w) + 16
            draw = ImageDraw.Draw(canvas)
        y = self._draw_grid_block(canvas, draw, theme, d["grid"], y, inner_w, gap)
        y = self._draw_quote_block(canvas, ImageDraw.Draw(canvas), theme, accent_rgb, result, y, inner_w)
        self._footer_block(canvas, ImageDraw.Draw(canvas), theme, accent, accent_rgb, result, y, inner_w)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(out_path, "PNG", optimize=True)
        return out_path
