"""卡片绘制工具：字体册与可复用绘图组件。

模块分成两层：

- :class:`FontBook` —— 字体探测、回退字体链、文本测量与绘制缓存，跨渲染复用；
- :class:`DrawingKit` —— 单次渲染的绘图上下文，持有画布尺寸、配色、平台色与
  全部图片 / 光影 / 组件工具。:class:`link_parser.services.card_render.styles.base.CardStyle`
  继承它，因此样式模块可以直接用 ``self.draw_text(...)``、``self.base_canvas(...)``。
"""

from __future__ import annotations

import math
import sys
import unicodedata
from pathlib import Path
from typing import Any

from astrbot.api import logger

from ...models import ParseResult
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
    PLATFORM_COLORS,
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


class FontBook:
    """字体探测、回退与文本排版缓存（由渲染器持有，跨渲染复用）。"""

    def __init__(self, font_path: str | None = None):
        self.font_path = font_path
        self._regular_font: str | None = None
        self._bold_font: str | None = None
        self._font_cache: dict[tuple[int, bool], Any] = {}
        # id(font) -> (size, bold)，供 text_width 反查字号
        self._font_meta: dict[int, tuple[int, bool]] = {}
        # 符号回退字体：[(路径, cmap)]，None 表示尚未加载
        self._fallback_specs: list[tuple[str, frozenset[int]]] | None = None
        # 主字体 cmap，None 表示尚未加载
        self._primary_cmap: frozenset[int] | None = None
        # 回退字体对象缓存 (路径, 字号) -> font
        self._fallback_font_cache: dict[tuple[str, int], Any] = {}
        self._measure = ImageDraw.Draw(Image.new("RGBA", (1, 1))) if Image else None

    # ---------- 字体 ----------

    def load_fonts(self) -> None:
        self._regular_font, self._bold_font = discover_fonts(self.font_path)
        self._primary_cmap = None  # 主字体变化后重新加载 cmap
        if not self._regular_font:
            logger.warning(
                "未找到可用的中文字体，解析卡片文字可能显示为方块，"
                "可在插件配置 RENDER_FONT_PATH 中指定字体文件"
            )

    def font(self, size: int, bold: bool = False) -> Any:
        key = (size, bold)
        if key in self._font_cache:
            return self._font_cache[key]
        if self._regular_font is None:
            self.load_fonts()
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

    def primary_cmap(self) -> frozenset[int]:
        """主字体（常规字重）的码点覆盖集合。"""
        if self._primary_cmap is None:
            if self._regular_font is None:
                self.load_fonts()
            self._primary_cmap = (
                font_cmap(self._regular_font) if self._regular_font else frozenset()
            )
        return self._primary_cmap

    def load_fallbacks(self) -> list[tuple[str, frozenset[int]]]:
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

    def fallback_font(self, path: str, size: int) -> Any:
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

    def split_runs(self, text: str, size: int, bold: bool) -> list[tuple[str, Any, bool]]:
        """按字体覆盖情况将文本切分为渲染段。

        返回 [(段文本, 字体对象, 是否主字体)]。主字体缺失字形的字符
        会切换到第一个覆盖它的回退字体；组合附标（如 ̫）始终跟随
        前一段，避免拆开后错位。无 fontTools 或无可用回退时退化为单段。
        """
        primary = self.font(size, bold)
        fallbacks = self.load_fallbacks()
        if not fallbacks or not text:
            return [(text, primary, True)]
        primary_cmap = self.primary_cmap()

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
                cur_font = self.fallback_font(path, size) if path else primary
        if cur_text:
            runs.append((cur_text, cur_font, cur_path is None))
        return runs

    def bold_stroke(self, bold: bool) -> int:
        """使用常规字体模拟粗体时的描边宽度。"""
        return 2 if bold and not self._bold_font and self._regular_font else 0

    # ---------- 文本工具 ----------

    def text_width(self, text: str, font: Any) -> int:
        meta = self._font_meta.get(id(font))
        if meta is not None and self.load_fallbacks():
            total = 0.0
            for run_text, run_font, _ in self.split_runs(text, meta[0], meta[1]):
                total += self._measure.textlength(run_text, font=run_font)
            return math.ceil(total)
        return math.ceil(self._measure.textlength(text, font=font))

    def wrap(self, text: str, font: Any, max_width: int) -> list[str]:
        """按字符宽度换行，兼容中日韩文本。"""
        lines: list[str] = []
        for raw in text.split("\n"):
            if not raw:
                lines.append("")
                continue
            current = ""
            for ch in raw:
                if self.text_width(current + ch, font) <= max_width:
                    current += ch
                else:
                    lines.append(current)
                    current = ch
            lines.append(current)
        return lines

    def fit_lines(
        self, text: str, font: Any, max_width: int, max_lines: int
    ) -> list[str]:
        lines = self.wrap(text, font, max_width)
        if len(lines) <= max_lines:
            return lines
        result = lines[: max_lines - 1]
        last = lines[max_lines - 1]
        ellipsis = "…"
        while last and self.text_width(last + ellipsis, font) > max_width:
            last = last[:-1]
        result.append(last + ellipsis)
        return result

    def line_height(self, font: Any) -> int:
        ascent, descent = font.getmetrics()
        return ascent + descent

    def draw_text(
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
        font = self.font(size, bold)
        if stroke_width is None:
            stroke_width = self.bold_stroke(bold)
        if stroke_fill is None:
            stroke_fill = fill
        runs = self.split_runs(text, size, bold)
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



class DrawingKit:
    """单次渲染的绘图上下文与全部可复用组件。

    样式实例继承本类；``fonts`` 由渲染器传入以复用字体缓存，其余字段都是
    本次渲染专属状态（并发渲染时各实例互不共享）。
    """

    def __init__(
        self,
        fonts: FontBook,
        *,
        width: int,
        theme: Theme,
        theme_name: str,
        cover_full_size: bool,
        result: ParseResult,
        images: dict[str, Any],
        out_path: Path,
    ):
        self.fonts = fonts
        self.width = width
        self.theme = theme
        self.theme_name = theme_name
        self.cover_full_size = cover_full_size
        self.result = result
        self.images = images
        self.out_path = out_path
        self.pad = L.PAD
        self.inner_w = self.width - self.pad * 2
        self.gap = L.GRID_GAP
        self.accent = self.accent_for(result.platform.name)
        self.accent_rgb = hex_to_rgb(self.accent)
        self._data: dict[str, Any] | None = None

    # ---------- 字体 / 文本（转发到共享的 FontBook） ----------

    def font(self, size: int, bold: bool = False) -> Any:
        return self.fonts.font(size, bold)

    def text_width(self, text: str, font: Any) -> int:
        return self.fonts.text_width(text, font)

    def wrap(self, text: str, font: Any, max_width: int) -> list[str]:
        return self.fonts.wrap(text, font, max_width)

    def fit_lines(self, text: str, font: Any, max_width: int, max_lines: int) -> list[str]:
        return self.fonts.fit_lines(text, font, max_width, max_lines)

    def line_height(self, font: Any) -> int:
        return self.fonts.line_height(font)

    def draw_text(
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
        self.fonts.draw_text(
            draw, xy, text, size, fill, bold, stroke_width, stroke_fill
        )

    # ---------- 上下文与保存 ----------

    @staticmethod
    def accent_for(platform_name: str) -> str:
        """平台品牌色；未登记的平台回退默认色。"""
        return PLATFORM_COLORS.get(platform_name, PLATFORM_COLORS["default"])

    @property
    def data(self) -> dict[str, Any]:
        """惰性准备的标题 / 正文 / 作者 / 统计等标准化字段。"""
        if self._data is None:
            self._data = self.prepare()
        return self._data

    def save(self, canvas: Any, out_path: Path | None = None) -> Path:
        """保存 PNG 并返回目标路径。"""
        target = Path(out_path or self.out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(target, "PNG", optimize=True)
        return target

    # ---------- 图片工具 ----------

    @staticmethod
    def open_image(path: Path) -> Image.Image:
        with Image.open(path) as im:
            im.load()
            im = ImageOps.exif_transpose(im)
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA")
            return im.copy()

    @staticmethod
    def cover_fit(image: Image.Image, box_w: int, box_h: int) -> Image.Image:
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
    def rounded_image(image: Image.Image, radius: int) -> Image.Image:
        img = image.convert("RGBA")
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, img.size[0] - 1, img.size[1] - 1), radius=radius, fill=255
        )
        img.putalpha(mask)
        return img

    @staticmethod
    def circle_avatar(image: Image.Image, size: int) -> Image.Image:
        img = image.convert("RGBA").resize((size, size), LANCZOS)
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
        img.putalpha(mask)
        return img

    @staticmethod
    def gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
        w, h = size
        grad = Image.new("RGB", (1, max(h, 1)))
        for y in range(max(h, 1)):
            ratio = y / max(h - 1, 1)
            color = tuple(round(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3))
            grad.putpixel((0, y), color)
        return grad.resize((w, h))

    # ---------- 毛玻璃与光影 ----------

    @staticmethod
    def glass(
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
    def radial_glow(
        w: int, h: int, rgb: tuple[int, int, int], alpha: int
    ) -> Image.Image:
        """生成一团柔和的径向光晕（品牌色渗透渐变用）。"""
        base = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(base).ellipse(
            (-w // 3, -h // 2, w // 2, h // 2), fill=(*rgb, alpha)
        )
        return base.filter(ImageFilter.GaussianBlur(max(w, h) // 5))

    @staticmethod
    def scrim(
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


    # ---------- 布局辅助 ----------

    @staticmethod
    def rounded_image_top(image: Image.Image, radius: int) -> Image.Image:
        """仅保留顶部圆角的图片（用于全宽横幅）。"""
        img = image.convert("RGBA")
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, img.size[0] - 1, img.size[1] - 1), radius=radius,
            corners=(True, True, False, False), fill=255,
        )
        img.putalpha(mask)
        return img

    def grid_metrics(
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

    def stat_pill_width(self, label: str, value: str) -> int:
        """统计药丸宽度：水平内边距 + 标签 + 间距 + 数值。"""
        w = L.STAT_PAD_X * 2
        w += self.text_width(label, self.font(L.F_STAT_LABEL))
        if value:
            w += L.STAT_LABEL_VALUE_GAP
            w += self.text_width(value, self.font(L.F_STAT_VALUE, bold=True))
        return w

    def build_stat_rows(
        self, stats: list[tuple[str, str]], inner_w: int
    ) -> list[list[tuple[str, str]]]:
        """将统计项按宽度拆分为多行徽章。"""
        rows: list[list[tuple[str, str]]] = []
        if not stats:
            return rows
        pills: list[tuple[str, str]] = []
        row_w = 0
        for label, value in stats:
            w = self.stat_pill_width(label, value)
            if pills and row_w + w + L.STAT_GAP > inner_w:
                rows.append(pills)
                pills = []
                row_w = 0
            pills.append((label, value))
            row_w += w + L.STAT_GAP
        if pills:
            rows.append(pills)
        return rows

    def platform_pill_width(self, text: str) -> int:
        """平台徽标（accent 圆点 + 平台名）宽度。"""
        font = self.font(L.F_PLATFORM, bold=True)
        return 18 + 12 + 8 + self.text_width(text, font) + 18


    # ---------- 徽章组件 ----------

    def draw_hero_badge(
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
        self.glass(
            canvas, (x, y, x + w, y + h), h // 2,
            tint_rgb=L.HERO_GLASS_TINT, tint_alpha=L.HERO_GLASS_TINT_ALPHA,
            border_rgb=(255, 255, 255), border_alpha=L.HERO_GLASS_BORDER_ALPHA,
        )
        draw = ImageDraw.Draw(canvas)
        font = self.font(font_size, bold)
        tx = x + 18
        if dot:
            dot_r = 6
            dot_cy = y + h // 2
            draw.ellipse(
                (tx, dot_cy - dot_r, tx + dot_r * 2, dot_cy + dot_r),
                fill=(*accent_rgb, 255),
            )
            tx += dot_r * 2 + 8
        self.draw_text(
            draw, (tx, y + (h - self.line_height(font)) // 2),
            text, font_size, "#FFFFFF", bold=bold,
        )

    def draw_flat_badge(
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
        self.glass(
            canvas, (x, y, x + w, y + h), h // 2,
            tint_rgb=theme.pill_bg, tint_alpha=theme.frost_alpha,
            border_rgb=theme.pill_bg, border_alpha=theme.frost_border_alpha,
            blur=6,
        )
        draw = ImageDraw.Draw(canvas)
        font = self.font(font_size, bold)
        tx = x + 18
        if dot:
            dot_r = 6
            dot_cy = y + h // 2
            draw.ellipse(
                (tx, dot_cy - dot_r, tx + dot_r * 2, dot_cy + dot_r),
                fill=(*accent_rgb, 255),
            )
            tx += dot_r * 2 + 8
        self.draw_text(
            draw, (tx, y + (h - self.line_height(font)) // 2),
            text, font_size, text_rgb, bold=bold,
        )

    # ---------- 转发引用 ----------

    def measure_quote(self, repost: ParseResult, inner_w: int) -> int:
        q_font = self.font(L.F_QUOTE)
        author = strip_emoji(repost.author.name) if repost.author else "原帖"
        text = strip_emoji(repost.title or repost.text or "")
        body = f"@{author}"
        if text:
            body += f"：{text}"
        max_w = inner_w - 18 * 2 - L.QUOTE_BAR_W - 16
        lines = self.fit_lines(body, q_font, max_w, 4)
        return max(80, len(lines) * L.F_QUOTE_LINE_H + 32)

    def draw_quote_text(
        self,
        draw: Any,
        repost: ParseResult,
        x: int,
        y: int,
        max_width: int,
        theme: Theme,
    ) -> None:
        q_font = self.font(L.F_QUOTE)
        author = strip_emoji(repost.author.name) if repost.author else "原帖"
        text = strip_emoji(repost.title or repost.text or "")
        body = f"@{author}"
        if text:
            body += f"：{text}"
        lines = self.fit_lines(body, q_font, max_width, 4)
        for line in lines:
            self.draw_text(draw, (x, y), line, L.F_QUOTE, theme.text_secondary)
            y += L.F_QUOTE_LINE_H

    # ==================== 备选布局共享组件 ====================

    def prepare(
        self,
        result: ParseResult | None = None,
        images: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """备选布局的公共数据准备。"""
        result = result if result is not None else self.result
        images = images if images is not None else self.images
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

    def base_canvas(self, theme: Theme, accent_rgb: tuple[int, int, int], card_h: int):
        """阴影 + 渐变底 + 光晕 + 圆角 + 描边，返回 (canvas, draw)。"""
        total_h = card_h + 14
        canvas = Image.new("RGBA", (self.width, total_h), (0, 0, 0, 0))
        shadow = Image.new("RGBA", (self.width, total_h), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            (L.SHADOW_INSET, L.SHADOW_INSET, self.width - L.SHADOW_INSET, total_h - 2),
            radius=L.RADIUS + 2, fill=(0, 0, 0, theme.shadow_alpha),
        )
        canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(L.SHADOW_BLUR)))
        grad = self.gradient((self.width, card_h), theme.gradient_top, theme.gradient_bottom)
        grad_rgba = grad.convert("RGBA")
        glow = self.radial_glow(self.width, round(self.width * 0.9), accent_rgb, theme.glow_alpha)
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

    def header_badges(self, canvas, theme: Theme, accent_rgb, d: dict) -> int:
        """纯文本头部：accent 条 + 平台药丸 + 类型 + 时间，返回结束 y。"""
        pad = L.PAD
        bar = Image.new("RGBA", (L.HEAD_BAR_W, L.HEAD_BAR_H), (0, 0, 0, 0))
        for xx in range(L.HEAD_BAR_W):
            a = int(230 * (1 - xx / max(L.HEAD_BAR_W - 1, 1)) ** 1.3)
            ImageDraw.Draw(bar).line([(xx, 0), (xx, L.HEAD_BAR_H)], fill=(*accent_rgb, a))
        canvas.alpha_composite(self.rounded_image(bar, L.HEAD_BAR_H // 2), (pad, L.HEAD_BAR_TOP))
        y = L.HEAD_BAR_TOP + L.HEAD_BAR_H + 18
        pw = self.platform_pill_width(d["platform_text"])
        self.draw_flat_badge(
            canvas, theme, pad, y, L.HEAD_PILL_H, pw,
            text=d["platform_text"], accent_rgb=accent_rgb, dot=True,
            font_size=L.F_PLATFORM, bold=True, text_rgb=theme.text_primary,
        )
        chip_font = self.font(L.F_CHIP, bold=True)
        self.draw_text(
            ImageDraw.Draw(canvas),
            (pad + pw + 16, y + (L.HEAD_PILL_H - self.line_height(chip_font)) // 2),
            d["content_type"], L.F_CHIP, theme.text_tertiary, bold=True,
        )
        if d["ts"]:
            ts_font = self.font(L.F_TIME)
            ts_w = self.text_width(d["ts"], ts_font)
            self.draw_text(
                ImageDraw.Draw(canvas),
                (self.width - pad - ts_w, y + (L.HEAD_PILL_H - self.line_height(ts_font)) // 2),
                d["ts"], L.F_TIME, theme.text_tertiary,
            )
        return y + L.HEAD_PILL_H + 18

    def avatar_block(self, canvas, draw, x: int, y: int, size: int,
                      images: dict, d: dict, accent_rgb) -> None:
        """绘制头像（含 accent 描边环或渐变首字母占位）。"""
        avatar_path = images.get("avatar")
        avatar = None
        if avatar_path:
            try:
                avatar = self.circle_avatar(self.open_image(avatar_path), size)
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
            placeholder = self.gradient(
                (size, size), accent_rgb, mix(accent_rgb, (0, 0, 0), 0.35)
            ).convert("RGBA")
            pmask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(pmask).ellipse((0, 0, size - 1, size - 1), fill=255)
            placeholder.putalpha(pmask)
            canvas.alpha_composite(placeholder, (x, y))
            first = d["name"][:1].upper()
            f_font = self.font(L.F_INITIAL, bold=True)
            fw = self.text_width(first, f_font)
            self.draw_text(
                ImageDraw.Draw(canvas),
                (x + (size - fw) // 2, y + (size - self.line_height(f_font)) // 2),
                first, L.F_INITIAL, "#FFFFFF", bold=True,
            )

    def stat_rows_height(self, d: dict, inner_w: int):
        rows = self.build_stat_rows(d["stats"], inner_w)
        if not rows:
            return 0, []
        return len(rows) * (L.STAT_H + L.STAT_ROW_GAP) - L.STAT_ROW_GAP, rows

    def draw_stat_rows(self, canvas, theme: Theme, rows, x0: int, y: int) -> int:
        """主题感知的统计药丸行，返回结束 y。"""
        label_font = self.font(L.F_STAT_LABEL)
        value_font = self.font(L.F_STAT_VALUE, bold=True)
        for row in rows:
            x = x0
            for label, value in row:
                w = self.stat_pill_width(label, value)
                self.glass(
                    canvas, (x, y, x + w, y + L.STAT_H), L.STAT_H // 2,
                    tint_rgb=theme.stat_pill_bg, tint_alpha=theme.frost_alpha,
                    border_rgb=theme.stat_pill_bg, border_alpha=theme.frost_border_alpha,
                    blur=6,
                )
                draw = ImageDraw.Draw(canvas)
                label_w = self.text_width(label, label_font)
                tx = x + L.STAT_PAD_X
                if value:
                    self.draw_text(draw, (tx, y + (L.STAT_H - self.line_height(label_font)) // 2),
                                    label, L.F_STAT_LABEL, theme.text_tertiary)
                    self.draw_text(draw, (tx + label_w + L.STAT_LABEL_VALUE_GAP,
                                           y + (L.STAT_H - self.line_height(value_font)) // 2),
                                    value, L.F_STAT_VALUE, theme.text_primary, bold=True)
                else:
                    self.draw_text(draw, (tx, y + (L.STAT_H - self.line_height(label_font)) // 2),
                                    label, L.F_STAT_LABEL, theme.text_secondary)
                x += w + L.STAT_GAP
            y += L.STAT_H + L.STAT_ROW_GAP
        return y - L.STAT_ROW_GAP

    def draw_online(self, draw, d: dict, y: int, accent: str) -> int:
        """在线人数（accent 圆点 + 文字），返回结束 y。"""
        online_font = self.font(L.F_ONLINE)
        dot_cy = y + self.line_height(online_font) // 2
        draw.ellipse((L.PAD, dot_cy - 4, L.PAD + 8, dot_cy + 4), fill=accent)
        self.draw_text(draw, (L.PAD + 18, y), d["online_text"], L.F_ONLINE, accent)
        return y + 38

    def warning_block_height(self, warnings: list[str], inner_w: int) -> int:
        """计算警告提示块的总高度。"""
        if not warnings:
            return 0
        font = self.font(20)
        line_h = self.line_height(font) + 4
        avail_w = inner_w - 46
        total_h = 0
        for raw_msg in warnings:
            msg = strip_emoji(raw_msg)
            lines = self.wrap(msg, font, avail_w)
            box_h = max(len(lines), 1) * line_h + 24
            total_h += box_h + 12
        return total_h - 12 if total_h > 0 else 0

    def draw_warning_block(
        self, canvas: Image.Image, draw: ImageDraw.ImageDraw, theme: Theme,
        warnings: list[str], y: int, inner_w: int, on_image: bool = False
    ) -> int:
        """渲染精致的时长超出限制警告提示块，返回结束 y。"""
        if not warnings:
            return y
        pad = L.PAD
        font = self.font(20)
        line_h = self.line_height(font) + 4
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
        elif self.theme.is_dark:
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
            lines = self.wrap(msg, font, avail_w)
            box_h = max(len(lines), 1) * line_h + 24

            # 毛玻璃圆角卡片底
            self.glass(
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
                self.draw_text(draw, (pad + 28, ty), line, 20, text_color)
                ty += line_h

            y += box_h + 12

        return y - 24

    def hero_aspect_height(self, hero_path: Path | None, box_w: int, default_h: int) -> int:
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

    def footer_block(self, canvas, draw, theme: Theme, accent: str, accent_rgb,
                      result: ParseResult, y: int, inner_w: int,
                      on_image: bool = False) -> None:
        """页脚：分隔线 + 左链接 + 右「圆点 莉卡解析」水印。"""
        pad = L.PAD
        divider_layer = Image.new("RGBA", (inner_w, 1), (0, 0, 0, 0))
        ImageDraw.Draw(divider_layer).line(
            (0, 0, inner_w - 1, 0),
            fill=((255, 255, 255, 60) if on_image
                  else with_alpha(theme.divider, theme.divider_alpha)),
            width=1,
        )
        canvas.alpha_composite(divider_layer, (pad, y + 12))
        foot_y = y + 28
        wm_font = self.font(L.F_FOOT, bold=True)
        wm_text_w = self.text_width("莉卡解析", wm_font)
        wm_group_w = L.WM_DOT + L.WM_DOT_GAP + wm_text_w
        wm_x = self.width - pad - wm_group_w
        wm_lh = self.line_height(wm_font)
        dot_cy = foot_y + wm_lh // 2
        draw.ellipse(
            (wm_x, dot_cy - L.WM_DOT // 2, wm_x + L.WM_DOT, dot_cy + L.WM_DOT // 2),
            fill=(*accent_rgb, 255),
        )
        self.draw_text(draw, (wm_x + L.WM_DOT + L.WM_DOT_GAP, foot_y),
                        "莉卡解析", L.F_FOOT, accent, bold=True)
        url_text = short_url(result.url)
        if url_text:
            url_font = self.font(L.F_FOOT)
            avail_w = wm_x - pad - 20
            while url_text and self.text_width(url_text, url_font) > avail_w:
                url_text = url_text[:-1]
            if url_text:
                color = (255, 255, 255, 160) if on_image else theme.text_tertiary
                self.draw_text(draw, (pad, foot_y), url_text, L.F_FOOT, color)

    def draw_grid_block(self, canvas, draw, theme: Theme, grid: list,
                         y: int, inner_w: int, gap: int) -> int:
        """图集网格，返回结束 y（自带异常兜底）。"""
        pad = L.PAD
        grid_h, cols, rows, cell_h = self.grid_metrics(len(grid), inner_w, gap)
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
                    img = self.cover_fit(self.open_image(path), cell_h, cell_h)
                    img = self.rounded_image(img, L.GRID_RADIUS)
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
                        self.scrim(cell_h, cell_h, start=0.0, max_alpha=150, power=1.2),
                        (x, yy),
                    )
                    plus_font = self.font(L.F_PLUS, bold=True)
                    pw = self.text_width(f"+{over}", plus_font)
                    self.draw_text(
                        ImageDraw.Draw(canvas),
                        (x + (cell_h - pw) // 2, yy + (cell_h - self.line_height(plus_font)) // 2),
                        f"+{over}", L.F_PLUS, "#FFFFFF", bold=True,
                    )
            return y + grid_h + 20
        except Exception:
            logger.warning("图集渲染失败，已跳过", exc_info=True)
            return y

    def draw_quote_block(self, canvas, draw, theme: Theme, accent_rgb,
                          result: ParseResult, y: int, inner_w: int) -> int:
        """转发引用（毛玻璃容器 + accent 竖条），返回结束 y。"""
        if not result.repost:
            return y
        pad = L.PAD
        quote_h = self.measure_quote(result.repost, inner_w)
        self.glass(
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
        self.draw_quote_text(
            ImageDraw.Draw(canvas), result.repost,
            pad + 18 + L.QUOTE_BAR_W + 16, y + 16,
            inner_w - 18 * 2 - L.QUOTE_BAR_W - 16, theme,
        )
        return y + quote_h + 20
