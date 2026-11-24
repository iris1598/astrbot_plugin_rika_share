"""输出层：解析结果 ↔ AstrBot 消息链。

- :mod:`~link_parser.output.builder`      按平台规则构建节点内容并发送（合并转发 / 纯文本）
- :mod:`~link_parser.output.json_card`    JSON 分享卡片的识别与链接提取
- :mod:`~link_parser.output.miniapp_card` QQ 官方机器人小程序卡片（纯文本形态）的识别与字段提取
- :mod:`~link_parser.output.quoted`       引用（回复）消息的文本与链接提取
- :mod:`~link_parser.output.replies`      统一的回复构造（错误提示等）
- :mod:`~link_parser.output.webpage`      非 OneBot 平台的「合并转发转网页」（链接经文件服务下发）
"""

from .builder import (
    build_header_text,
    build_platform_output,
    plan_output_segments,
    send_nodes_batched,
    send_plain_output,
    try_send_media,
)
from .json_card import (
    EventUrlWrapper,
    extract_links_from_event,
    extract_links_from_text,
    has_json_component,
)
from .miniapp_card import (
    extract_card_link,
    extract_card_title,
    is_miniapp_card,
    parse_miniapp_card,
)
from .quoted import (
    find_reply_component,
    quoted_links,
    quoted_text,
)
from .replies import error_result
from .webpage import (
    build_official_card_assets,
    create_webpage,
    format_share_message,
    webpage_token_expired,
)

__all__ = [
    "EventUrlWrapper",
    "build_header_text",
    "build_official_card_assets",
    "build_platform_output",
    "create_webpage",
    "error_result",
    "extract_card_link",
    "extract_card_title",
    "extract_links_from_event",
    "extract_links_from_text",
    "find_reply_component",
    "format_share_message",
    "has_json_component",
    "is_miniapp_card",
    "parse_miniapp_card",
    "plan_output_segments",
    "quoted_links",
    "quoted_text",
    "send_nodes_batched",
    "send_plain_output",
    "try_send_media",
    "webpage_token_expired",
]
