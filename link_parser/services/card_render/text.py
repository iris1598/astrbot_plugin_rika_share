"""卡片文本处理：清洗、统计行解析、链接与时间格式化。"""

from __future__ import annotations

import re
from datetime import datetime


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


def one_line(text: str | None) -> str:
    """折叠换行与多余空白，供单行文本绘制使用。"""
    return " ".join(strip_emoji(text).split())


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
