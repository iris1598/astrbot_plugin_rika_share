"""卡片渲染服务。

模块划分：

- :mod:`~link_parser.services.card_render.renderer`  渲染器主体与四种布局
- :mod:`~link_parser.services.card_render.theme`     布局尺寸常量、配色主题、颜色工具
- :mod:`~link_parser.services.card_render.fonts`     中文字体探测与符号回退链
- :mod:`~link_parser.services.card_render.text`      文本清洗、统计行解析、链接与时间格式化
"""

from .renderer import ShareCardRenderer
from .text import format_timestamp, one_line, parse_stats_line, short_url, strip_emoji
from .theme import LAYOUT_NAMES, PLATFORM_COLORS

__all__ = [
    "LAYOUT_NAMES",
    "PLATFORM_COLORS",
    "ShareCardRenderer",
    "format_timestamp",
    "one_line",
    "parse_stats_line",
    "short_url",
    "strip_emoji",
]
