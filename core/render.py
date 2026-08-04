"""精美解析卡片渲染模块

使用 Pillow 将解析结果渲染为一张精美的分享卡片图片，
支持深色 / 浅色两套主题，包含：

- 顶部横幅：视频封面或图集首图全宽展示，标题白色浮层 + 平台徽标悬浮
- 圆形作者头像、昵称与签名
- 正文简介、数据统计徽章（时长 / 点赞 / 投币 / 收藏 / 播放等）
- 图集网格（超过 6 张显示 +N）、转发内容引用卡片
- 底部链接与「莉卡解析」水印

所有绘图操作均为 CPU 密集的同步任务，由调用方通过 asyncio.to_thread
放到后台线程执行，避免阻塞 AstrBot 事件循环。
"""

from __future__ import annotations

import hashlib
import asyncio
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from astrbot.api import logger

from .data import ParseResult, ImageContent
from .task import PathTask

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    from PIL import ImageOps
except ImportError:  # pragma: no cover
    Image = ImageDraw = ImageFilter = ImageFont = None
    ImageOps = None

try:
    _LANCZOS = Image.Resampling.LANCZOS
except AttributeError:  # Pillow < 9.1
    _LANCZOS = Image.LANCZOS  # type: ignore[attr-defined]


# ============================ 文本与统计处理 ============================

# 常见 emoji 区域（含 ZWJ 序列、变体选择符、肤色修饰符）
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001F0FF"    # 麻将 / 扑克
    "\U0001F100-\U0001F64F"    # 数字符号 - 表情符号
    "\U0001F680-\U0001F6FF"    # 交通
    "\U0001F700-\U0001F77F"    # 炼金术符号
    "\U0001F780-\U0001F7FF"    # 几何图形扩展
    "\U0001F800-\U0001F8FF"    # 补充箭头
    "\U0001F900-\U0001F9FF"    # 补充符号与图案
    "\U0001FA00-\U0001FA6F"    # 国际象棋符号
    "\U0001FA70-\U0001FAFF"    # 符号扩展
    "\U00002600-\U000026FF"    # 杂项符号
    "\U00002700-\U000027BF"    # 装饰符号
    "\U0000FE00-\U0000FE0F"    # 变体选择符
    "\U0001F1E6-\U0001F1FF"    # 区域指示符（国旗）
    "\U0001F3FB-\U0001F3FF"    # 肤色修饰符
    "\U0000200D"               # 零宽连接符
    "\U000E0020-\U000E007F"    # 标签字符
    "]+"
)

# 统计行 emoji -> 中文标签
_STAT_LABELS = {
    "👍": "点赞",
    "❤": "喜欢",
    "❤️": "喜欢",
    "🧡": "喜欢",
    "💗": "喜欢",
    "🪙": "投币",
    "⭐": "收藏",
    "↩": "转发",
    "↩️": "转发",
    "🔁": "转发",
    "📢": "转发",
    "💬": "评论",
    "✉": "回复",
    "✉️": "回复",
    "👀": "播放",
    "▶": "播放",
    "💭": "弹幕",
    "🔗": "链接",
    "📈": "浏览",
    "🔥": "热度",
    "🏄": "在线",
}


def strip_emoji(text: str | None) -> str:
    """移除字符串中的 emoji，避免字体缺失导致渲染成方块。"""
    if not text:
        return ""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _EMOJI_RE.sub("", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def parse_stats_line(stats_line: str | None) -> list[tuple[str, str]]:
    """将类似『👍 1.2万 🪙 8千』的统计行解析为 (标签, 数值) 列表。"""
    if not stats_line:
        return []
    tokens = stats_line.split()
    stats: list[tuple[str, str]] = []
    i = 0
    icons = sorted(_STAT_LABELS.items(), key=lambda kv: len(kv[0]), reverse=True)
    while i < len(tokens):
        token = tokens[i]
        matched = None
        for icon, label in icons:
            if token.startswith(icon):
                matched = label
                rest = strip_emoji(token[len(icon):])
                break
        if matched is not None:
            value = rest
            if not value and i + 1 < len(tokens):
                i += 1
                value = tokens[i]
            if value:
                stats.append((matched, value))
        else:
            clean = strip_emoji(token)
            if clean:
                stats.append((clean, ""))
        i += 1
    return stats


def short_url(url: str | None, max_len: int = 58) -> str:
    """去掉协议头并截断为适合卡片展示的链接文本。"""
    if not url:
        return ""
    text = re.sub(r"^https?://", "", url).rstrip("/")
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text


def format_timestamp(ts: int | None) -> str | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return None


# ============================ 主题与平台配色 ============================

PLATFORM_COLORS = {
    "bilibili": "#FB7299",
    "douyin": "#2EF2EE",
    "kuaishou": "#FF7E00",
    "weibo": "#FF8200",
    "xiaohongshu": "#FF2442",
    "twitter": "#55ACEE",
    "acfun": "#FD4C5D",
    "nga": "#66C0F4",
    "youtube": "#FF4E45",
    "tiktok": "#2EF2EE",
    "website": "#8B7CF6",
    "default": "#8B7CF6",
}


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _with_alpha(rgb: tuple[int, int, int], alpha: int) -> tuple[int, int, int, int]:
    return (rgb[0], rgb[1], rgb[2], alpha)


class _Theme:
    """一套卡片配色方案"""

    def __init__(
        self,
        *,
        gradient_top: str,
        gradient_bottom: str,
        border: str,
        text_primary: str,
        text_secondary: str,
        text_tertiary: str,
        pill_bg: str,
        quote_bg: str,
        divider: str,
        shadow_alpha: int,
        stat_pill_bg: str,
    ):
        self.gradient_top = _hex_to_rgb(gradient_top)
        self.gradient_bottom = _hex_to_rgb(gradient_bottom)
        self.border = _hex_to_rgb(border)
        self.text_primary = _hex_to_rgb(text_primary)
        self.text_secondary = _hex_to_rgb(text_secondary)
        self.text_tertiary = _hex_to_rgb(text_tertiary)
        self.pill_bg = _hex_to_rgb(pill_bg)
        self.quote_bg = _hex_to_rgb(quote_bg)
        self.divider = _hex_to_rgb(divider)
        self.shadow_alpha = shadow_alpha
        self.stat_pill_bg = _hex_to_rgb(stat_pill_bg)


_THEMES = {
    "dark": _Theme(
        gradient_top="#2A3142",
        gradient_bottom="#171B27",
        border="#FFFFFF",
        text_primary="#F3F5FA",
        text_secondary="#A9B2C4",
        text_tertiary="#7B8497",
        pill_bg="#FFFFFF",
        quote_bg="#FFFFFF",
        divider="#FFFFFF",
        shadow_alpha=120,
        stat_pill_bg="#FFFFFF",
    ),
    "light": _Theme(
        gradient_top="#FFFFFF",
        gradient_bottom="#EEF2F8",
        border="#1B2233",
        text_primary="#1B2233",
        text_secondary="#5B6478",
        text_tertiary="#8B93A6",
        pill_bg="#1B2233",
        quote_bg="#1B2233",
        divider="#1B2233",
        shadow_alpha=70,
        stat_pill_bg="#1B2233",
    ),
}


# ============================ 字体探测 ============================

_FONT_CANDIDATES: dict[str, tuple[tuple[str, str], ...]] = {
    "win32": (
        ("msyh.ttc", "msyhbd.ttc"),        # 微软雅黑
        ("simhei.ttf", "msyhbd.ttc"),      # 黑体
        ("Deng.ttf", "Dengb.ttf"),         # 等线
        ("simsun.ttc", "simsun.ttc"),      # 宋体
        ("NotoSansSC-VF.ttf", "NotoSansSC-VF.ttf"),
    ),
    "darwin": (
        ("PingFang.ttc", "PingFang.ttc"),  # 苹方
        ("Hiragino Sans GB.ttc", "Hiragino Sans GB.ttc"),
        ("STHeiti Medium.ttc", "STHeiti Medium.ttc"),
    ),
    "linux": (
        ("NotoSansCJK-Regular.ttc", "NotoSansCJK-Bold.ttc"),
        ("SourceHanSansSC-Regular.otf", "SourceHanSansSC-Bold.otf"),
        ("wqy-zenhei.ttc", "wqy-zenhei.ttc"),
        ("wqy-microhei.ttc", "wqy-microhei.ttc"),
        ("DroidSansFallbackFull.ttf", "DroidSansFallbackFull.ttf"),
        ("arpluminghk-regular.ttf", "arpluminghk-regular.ttf"),
    ),
}

_FONT_DIRS = [
    "C:/Windows/Fonts",
    "/System/Library/Fonts",
    "/System/Library/Fonts/Supplemental",
    "/usr/share/fonts/opentype/noto",
    "/usr/share/fonts/opentype/noto-cjk",
    "/usr/share/fonts/truetype/noto-cjk",
    "/usr/share/fonts/noto-cjk",
    "/usr/share/fonts/truetype/wqy",
    "/usr/share/fonts/truetype/droid",
    "/usr/share/fonts/truetype/arphic",
    "/usr/share/fonts/opentype/source-han-sans",
    "/usr/local/share/fonts",
]


def _discover_fonts(custom_path: str | None = None) -> tuple[str | None, str | None]:
    """查找可用的中文字体，返回 (常规字体, 粗体字体) 路径。"""
    if custom_path:
        p = Path(custom_path).expanduser()
        if p.is_dir():
            for ext in ("*.ttf", "*.ttc", "*.otf"):
                found = sorted(p.glob(ext))
                if found:
                    return str(found[0]), str(found[-1] if len(found) > 1 else found[0])
        elif p.is_file():
            return str(p), str(p)
        logger.warning(f"渲染字体路径无效，将自动探测系统字体: {custom_path}")

    platform = sys.platform
    candidates = _FONT_CANDIDATES.get(platform, _FONT_CANDIDATES["linux"])
    dirs = [Path(d) for d in _FONT_DIRS]

    for regular_name, bold_name in candidates:
        for d in dirs:
            reg = d / regular_name
            bol = d / bold_name
            if reg.exists():
                if bol.exists():
                    return str(reg), str(bol)
                return str(reg), None

    # 兜底：任意目录下存在的中文字体
    for d in dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.suffix.lower() in {".ttf", ".ttc", ".otf"}:
                return str(p), None
    return None, None


# ============================ 渲染器 ============================


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
    ):
        self.cache_dir = cache_dir
        self.enabled = enabled and Image is not None
        self.width = max(520, min(1080, int(width)))
        self.theme_name = theme if theme in _THEMES else "dark"
        self.font_path = font_path
        self._regular_font: str | None = None
        self._bold_font: str | None = None
        self._font_cache: dict[tuple[int, bool], Any] = {}
        self._measure = ImageDraw.Draw(Image.new("RGBA", (1, 1))) if Image else None

    # ---------- 字体 ----------

    def _load_fonts(self) -> None:
        self._regular_font, self._bold_font = _discover_fonts(self.font_path)
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
        return font

    def _bold_stroke(self, bold: bool) -> int:
        """使用常规字体模拟粗体时的描边宽度。"""
        return 2 if bold and not self._bold_font and self._regular_font else 0

    # ---------- 文本工具 ----------

    def _text_width(self, text: str, font: Any) -> int:
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
    ) -> None:
        font = self._font(size, bold)
        stroke = self._bold_stroke(bold)
        draw.text(
            xy,
            text,
            font=font,
            fill=fill,
            stroke_width=stroke,
            stroke_fill=fill,
        )

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
        img = img.resize((nw, nh), _LANCZOS)
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
        img = image.convert("RGBA").resize((size, size), _LANCZOS)
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

    # ---------- 主流程 ----------

    async def render(
        self,
        result: ParseResult,
        cache_key: str | None = None,
        existing: Path | None = None,
    ) -> Path | None:
        """异步渲染卡片，失败时返回 None（由调用方回退到文本输出）。"""
        if not self.enabled:
            return None
        try:
            if existing is not None and existing.exists():
                return existing
            out_path = self._output_path(cache_key, result)
            if out_path.exists():
                return out_path
            images = await self._collect_images(result)
            return await asyncio.to_thread(self._render_sync, result, images, out_path)
        except Exception:
            logger.exception("解析卡片渲染失败，已回退到文本输出")
            return None

    def _output_path(self, cache_key: str | None, result: ParseResult) -> Path:
        payload = (
            cache_key
            or f"{result.platform.name}|{result.title}|{result.timestamp}|{result.url}"
        )
        digest = hashlib.md5(
            f"{self.theme_name}|{self.width}|{payload}".encode("utf-8")
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
            cols, rows, cell_h = 1, 1, min(inner_w, 420)
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

    def _build_stat_rows(
        self, stats: list[tuple[str, str]], inner_w: int
    ) -> list[list[tuple[str, str]]]:
        """将统计项按宽度拆分为多行徽章。"""
        rows: list[list[tuple[str, str]]] = []
        if not stats:
            return rows
        font = self._font(22, bold=True)
        pills: list[tuple[str, str]] = []
        row_w = 0
        for label, value in stats:
            pill_text = f"{label} {value}".strip()
            w = self._text_width(pill_text, font) + 32
            if pills and row_w + w + 10 > inner_w:
                rows.append(pills)
                pills = []
                row_w = 0
            pills.append((label, value))
            row_w += w + 10
        if pills:
            rows.append(pills)
        return rows

    # ---------- 同步绘制 ----------

    def _render_sync(
        self,
        result: ParseResult,
        images: dict[str, Any],
        out_path: Path,
    ) -> Path:
        theme = _THEMES[self.theme_name]
        accent = PLATFORM_COLORS.get(result.platform.name, PLATFORM_COLORS["default"])
        accent_rgb = _hex_to_rgb(accent)

        pad = 44
        inner_w = self.width - pad * 2
        gap = 14

        # ================= 数据准备 =================
        is_video_hero = images.get("hero") is not None
        hero = images.get("hero")
        grid = list(images.get("grid") or [])
        if hero is None and grid:
            # 没有视频封面时，用图集首图作为顶部横幅
            hero = grid.pop(0)
        hero_h = round(self.width * 9 / 16) if hero else 0

        grid_h, cols, rows, cell_h = self._grid_metrics(len(grid), inner_w, gap)

        # 头部文字
        platform_font = self._font(23, bold=True)
        platform_text = result.platform.display_name
        pill_h = 40
        platform_pill_w = self._text_width(platform_text, platform_font) + 40

        type_font = self._font(21, bold=True)
        content_type = result.content_type or "动态"
        type_pill_w = self._text_width(content_type, type_font) + 36

        ts = format_timestamp(result.timestamp)
        ts_font = self._font(20)

        # 标题
        title_font = self._font(36, bold=True)
        title = strip_emoji(result.title)
        title_lines: list[str] = []
        if title:
            title_lines = self._fit_lines(
                title, title_font, inner_w, 2 if hero else 3
            )
        title_line_h = 50

        # 简介
        desc_font = self._font(26)
        text = strip_emoji(result.text)
        desc_lines: list[str] = []
        if text:
            desc_lines = self._fit_lines(text, desc_font, inner_w, 6)

        # 作者
        author = result.author
        avatar_size = 64
        name = strip_emoji(author.name) or "未知作者" if author else ""
        author_desc = strip_emoji(author.description or "")[:40] if author else ""

        # 统计（时长并入统计徽章）
        stats = parse_stats_line(result.extra.get("stats_line"))
        if dur := result.extra.get("duration"):
            stats.insert(0, ("时长", str(dur)))
        online_text = strip_emoji(result.extra.get("online") or "")
        stat_rows = self._build_stat_rows(stats, inner_w)

        quote_h = self._measure_quote(result.repost, inner_w) if result.repost else 0

        # ================= 高度计算 =================
        y = hero_h if hero else pad + pill_h + 16
        if hero:
            y += 18
        if author:
            y += avatar_size + 18
        else:
            y += 12
        if not hero and title_lines:
            y += len(title_lines) * title_line_h + 12
        if desc_lines:
            y += len(desc_lines) * 38 + 14
        if stat_rows:
            y += len(stat_rows) * 42 + 20
        if online_text:
            y += 40
        if grid:
            y += grid_h + 20
        if quote_h:
            y += quote_h + 20
        y += 54 + pad - 6
        card_h = y
        total_h = card_h + 14

        # ================= 绘制底层 =================
        canvas = Image.new("RGBA", (self.width, total_h), (0, 0, 0, 0))

        # 阴影
        shadow = Image.new("RGBA", (self.width, total_h), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            (10, 10, self.width - 10, total_h - 2), radius=30,
            fill=(0, 0, 0, theme.shadow_alpha),
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(14))
        canvas.alpha_composite(shadow)

        # 卡片主体（渐变 + 圆角）
        grad = self._gradient((self.width, card_h), theme.gradient_top, theme.gradient_bottom)
        mask = Image.new("L", (self.width, card_h), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, self.width - 1, card_h - 1), radius=28, fill=255
        )
        card = grad.convert("RGBA")
        card.putalpha(mask)
        canvas.alpha_composite(card, (0, 0))

        draw = ImageDraw.Draw(canvas)
        border_alpha = 26 if self.theme_name == "dark" else 18
        draw.rounded_rectangle(
            (0, 0, self.width - 1, card_h - 1), radius=28,
            outline=_with_alpha(theme.border, border_alpha), width=1,
        )

        y = 0
        if hero:
            # ============ 顶部横幅 ============
            hero_img = None
            try:
                hero_img = self._cover_fit(self._open_image(hero), self.width, hero_h)
                hero_img = self._rounded_image_top(hero_img, 28)
            except Exception:
                hero_img = None
                logger.warning("横幅图片渲染失败，使用占位背景", exc_info=True)
            if hero_img is not None:
                canvas.alpha_composite(hero_img, (0, 0))
            else:
                ph = self._gradient(
                    (self.width, hero_h), (42, 48, 64), (20, 24, 34)
                ).convert("RGBA")
                tint = Image.new(
                    "RGBA", (self.width, hero_h),
                    (accent_rgb[0], accent_rgb[1], accent_rgb[2], 45),
                )
                ph.alpha_composite(tint)
                ph = self._rounded_image_top(ph, 28)
                canvas.alpha_composite(ph, (0, 0))

            # 底部渐变遮罩（保证标题可读）
            overlay = Image.new("RGBA", (self.width, hero_h), (0, 0, 0, 0))
            od = ImageDraw.Draw(overlay)
            for yy in range(hero_h):
                alpha = int(22 + 168 * (yy / max(hero_h - 1, 1)))
                od.line([(0, yy), (self.width, yy)], fill=(0, 0, 0, alpha))
            canvas.alpha_composite(overlay, (0, 0))

            # 悬浮徽标：平台 + 类型 + 时间
            badge_y = 26
            draw.rounded_rectangle(
                (28, badge_y, 28 + platform_pill_w, badge_y + pill_h),
                radius=pill_h // 2, fill=accent,
            )
            self._draw_text(
                draw,
                (28 + 20, badge_y + (pill_h - self._line_height(platform_font)) // 2),
                platform_text, 23, "#FFFFFF", bold=True,
            )
            chip_h = 34
            chip_y = badge_y + (pill_h - chip_h) // 2
            chip_x = 28 + platform_pill_w + 10
            draw.rounded_rectangle(
                (chip_x, chip_y, chip_x + type_pill_w, chip_y + chip_h),
                radius=chip_h // 2, fill=(0, 0, 0, 115),
            )
            self._draw_text(
                draw,
                (chip_x + 18, chip_y + (chip_h - self._line_height(type_font)) // 2),
                content_type, 21, "#FFFFFF", bold=True,
            )
            if ts:
                ts_w = self._text_width(ts, ts_font)
                ts_x = self.width - 28 - ts_w - 26
                draw.rounded_rectangle(
                    (ts_x, chip_y, ts_x + ts_w + 26, chip_y + chip_h),
                    radius=chip_h // 2, fill=(0, 0, 0, 115),
                )
                self._draw_text(
                    draw,
                    (ts_x + 13, chip_y + (chip_h - self._line_height(ts_font)) // 2),
                    ts, 20, "#FFFFFF",
                )

            # 视频播放按钮
            if is_video_hero:
                play_r = 40
                cx, cy = self.width // 2, hero_h // 2
                play = Image.new("RGBA", (play_r * 2, play_r * 2), (0, 0, 0, 0))
                ImageDraw.Draw(play).ellipse(
                    (0, 0, play_r * 2 - 1, play_r * 2 - 1),
                    fill=(0, 0, 0, 140),
                    outline=(255, 255, 255, 210), width=3,
                )
                pd = ImageDraw.Draw(play)
                pd.polygon(
                    [
                        (play_r - 11, play_r - 16),
                        (play_r - 11, play_r + 16),
                        (play_r + 18, play_r),
                    ],
                    fill=(255, 255, 255, 235),
                )
                canvas.alpha_composite(play, (cx - play_r, cy - play_r))

            # 标题白色浮层（黑色描边增强可读性）
            if title_lines:
                ty = hero_h - len(title_lines) * title_line_h - 28
                for line in title_lines:
                    draw.text(
                        (pad, ty), line, font=title_font,
                        fill=(255, 255, 255, 255), stroke_width=3,
                        stroke_fill=(0, 0, 0, 190),
                    )
                    ty += title_line_h
            y = hero_h + 18
        else:
            # ============ 纯文本卡片头部 ============
            draw.rounded_rectangle(
                (28, 22, self.width - 28, 28), radius=3,
                fill=_with_alpha(accent_rgb, 210),
            )
            y = pad
            draw.rounded_rectangle(
                (pad, y, pad + platform_pill_w, y + pill_h),
                radius=pill_h // 2, fill=accent,
            )
            self._draw_text(
                draw,
                (pad + 20, y + (pill_h - self._line_height(platform_font)) // 2),
                platform_text, 23, "#FFFFFF", bold=True,
            )
            type_pill_x = pad + platform_pill_w + 10
            draw.rounded_rectangle(
                (type_pill_x, y, type_pill_x + type_pill_w, y + pill_h),
                radius=pill_h // 2,
                fill=_with_alpha(theme.pill_bg, 16 if self.theme_name == "dark" else 14),
            )
            self._draw_text(
                draw,
                (type_pill_x + 18, y + (pill_h - self._line_height(type_font)) // 2),
                content_type, 21, theme.text_secondary, bold=True,
            )
            if ts:
                ts_w = self._text_width(ts, ts_font)
                self._draw_text(
                    draw,
                    (self.width - pad - ts_w, y + (pill_h - self._line_height(ts_font)) // 2),
                    ts, 20, theme.text_tertiary,
                )
            y += pill_h + 16

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
                    outline=_with_alpha(accent_rgb, 130), width=3,
                )
                canvas.alpha_composite(ring, (pad, y))
            else:
                # 无头像时绘制首字母占位圆
                placeholder = Image.new("RGBA", (avatar_size, avatar_size), (0, 0, 0, 0))
                ImageDraw.Draw(placeholder).ellipse(
                    (0, 0, avatar_size - 1, avatar_size - 1),
                    fill=_with_alpha(accent_rgb, 150),
                )
                canvas.alpha_composite(placeholder, (pad, y))
                first = name[:1].upper()
                f_font = self._font(26, bold=True)
                fw = self._text_width(first, f_font)
                self._draw_text(
                    draw,
                    (pad + (avatar_size - fw) // 2, y + (avatar_size - self._line_height(f_font)) // 2),
                    first, 26, "#FFFFFF", bold=True,
                )
            name_x = pad + avatar_size + 20
            self._draw_text(
                draw, (name_x, y + 4), name, 26, theme.text_primary, bold=True
            )
            if author_desc:
                self._draw_text(
                    draw, (name_x, y + avatar_size - 22),
                    author_desc, 20, theme.text_tertiary,
                )
            y += avatar_size + 18
        else:
            y += 12

        # ============ 标题（非横幅模式） ============
        if not hero and title_lines:
            for line in title_lines:
                self._draw_text(
                    draw, (pad, y), line, 36, theme.text_primary, bold=True
                )
                y += title_line_h
            y += 12

        # ============ 简介 ============
        if desc_lines:
            for line in desc_lines:
                self._draw_text(draw, (pad, y), line, 26, theme.text_secondary)
                y += 38
            y += 14

        # ============ 统计徽章 ============
        if stat_rows:
            stat_font = self._font(22, bold=True)
            for row in stat_rows:
                x = pad
                for label, value in row:
                    pill_text = f"{label} {value}".strip()
                    w = self._text_width(pill_text, stat_font) + 32
                    draw.rounded_rectangle(
                        (x, y, x + w, y + 38), radius=19,
                        fill=_with_alpha(
                            theme.stat_pill_bg,
                            12 if self.theme_name == "dark" else 16,
                        ),
                    )
                    self._draw_text(
                        draw,
                        (x + 16, y + (38 - self._line_height(stat_font)) // 2),
                        pill_text, 22, theme.text_secondary, bold=True,
                    )
                    x += w + 10
                y += 42
            y += 20

        # ============ 在线人数 ============
        if online_text:
            online_font = self._font(22)
            if self._text_width(online_text, online_font) <= inner_w:
                self._draw_text(draw, (pad, y), online_text, 22, accent)
            y += 40

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
                        img = self._rounded_image(img, 16)
                        canvas.alpha_composite(img, (x, yy))
                    except Exception:
                        draw.rounded_rectangle(
                            (x, yy, x + cell_h, yy + cell_h), radius=16,
                            fill=_with_alpha(theme.pill_bg, 10),
                        )
                    if idx == show - 1 and over > 0:
                        overlay = Image.new("RGBA", (cell_h, cell_h), (0, 0, 0, 0))
                        ImageDraw.Draw(overlay).rounded_rectangle(
                            (0, 0, cell_h - 1, cell_h - 1), radius=16,
                            fill=(0, 0, 0, 115),
                        )
                        canvas.alpha_composite(overlay, (x, yy))
                        plus_font = self._font(38, bold=True)
                        plus_text = f"+{over}"
                        pw = self._text_width(plus_text, plus_font)
                        self._draw_text(
                            draw,
                            (x + (cell_h - pw) // 2, yy + (cell_h - self._line_height(plus_font)) // 2),
                            plus_text, 38, "#FFFFFF", bold=True,
                        )
                y += grid_h + 20
            except Exception:
                logger.warning("图集渲染失败，已跳过", exc_info=True)
                y -= grid_h + 20

        # ============ 转发引用 ============
        if result.repost and quote_h:
            qy = y
            draw.rounded_rectangle(
                (pad, qy, pad + inner_w, qy + quote_h), radius=16,
                fill=_with_alpha(theme.quote_bg, 8 if self.theme_name == "dark" else 10),
            )
            draw.rounded_rectangle(
                (pad + 18, qy + 16, pad + 24, qy + quote_h - 16), radius=4,
                fill=_with_alpha(accent_rgb, 220),
            )
            self._draw_quote_text(
                draw, result.repost, pad + 18 + 40, qy + 14, inner_w - 80, theme
            )
            y += quote_h + 20

        # ============ 页脚 ============
        draw.line(
            (pad, y + 8, pad + inner_w, y + 8),
            fill=_with_alpha(theme.divider, 14 if self.theme_name == "dark" else 12),
            width=1,
        )
        watermark = "★ 莉卡解析"
        wm_font = self._font(22, bold=True)
        wm_w = self._text_width(watermark, wm_font)
        url_text = short_url(result.url)
        if url_text:
            url_font = self._font(22)
            avail_w = inner_w - wm_w - 24
            while url_text and self._text_width(url_text, url_font) > avail_w:
                url_text = url_text[:-1]
            if url_text:
                self._draw_text(
                    draw, (pad, y + 22), url_text, 22, theme.text_tertiary
                )
        self._draw_text(
            draw,
            (self.width - pad - wm_w, y + 22),
            watermark, 22, accent, bold=True,
        )

        # ---------- 保存 ----------
        out_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(out_path, "PNG", optimize=True)
        return out_path

    def _measure_quote(self, repost: ParseResult, inner_w: int) -> int:
        q_font = self._font(25)
        author = strip_emoji(repost.author.name) if repost.author else "原帖"
        text = strip_emoji(repost.title or repost.text or "")
        body = f"@{author}"
        if text:
            body += f"：{text}"
        lines = self._fit_lines(body, q_font, inner_w - 80, 4)
        return max(76, len(lines) * 36 + 38)

    def _draw_quote_text(
        self,
        draw: Any,
        repost: ParseResult,
        x: int,
        y: int,
        max_width: int,
        theme: _Theme,
    ) -> None:
        q_font = self._font(25)
        author = strip_emoji(repost.author.name) if repost.author else "原帖"
        text = strip_emoji(repost.title or repost.text or "")
        body = f"@{author}"
        if text:
            body += f"：{text}"
        lines = self._fit_lines(body, q_font, max_width, 4)
        for line in lines:
            self._draw_text(draw, (x, y), line, 25, theme.text_secondary)
            y += 36
