"""卡片渲染服务。

模块划分：

- :mod:`~link_parser.services.card_render.renderer`  渲染编排（缓存 / 取图 / 样式分发）
- :mod:`~link_parser.services.card_render.toolkit`   字体册与绘图工具（FontBook / DrawingKit）
- :mod:`~link_parser.services.card_render.styles`    卡片样式包（自动发现 + 自注册）
- :mod:`~link_parser.services.card_render.theme`     布局尺寸常量、配色主题、颜色工具
- :mod:`~link_parser.services.card_render.fonts`     中文字体探测与符号回退链
- :mod:`~link_parser.services.card_render.text`      文本清洗、统计行解析、链接与时间格式化
"""

from .renderer import ShareCardRenderer
from .styles import (
    DEFAULT_STYLE,
    STYLE_NAMES,
    CardStyle,
    StyleSpec,
    get_style,
    iter_styles,
    register_style,
    style_names,
)
from .text import format_timestamp, one_line, parse_stats_line, short_url, strip_emoji
from .theme import PLATFORM_COLORS

__all__ = [
    "DEFAULT_STYLE",
    "PLATFORM_COLORS",
    "STYLE_NAMES",
    "CardStyle",
    "ShareCardRenderer",
    "StyleSpec",
    "format_timestamp",
    "get_style",
    "iter_styles",
    "one_line",
    "parse_stats_line",
    "register_style",
    "short_url",
    "strip_emoji",
    "style_names",
]
