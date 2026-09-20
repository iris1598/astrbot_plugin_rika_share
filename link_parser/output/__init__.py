"""输出层：解析结果 → AstrBot 消息链。

- :mod:`~link_parser.output.builder`   按平台规则构建节点内容并发送（合并转发 / 纯文本）
- :mod:`~link_parser.output.json_card` JSON 分享卡片的识别与链接提取
- :mod:`~link_parser.output.replies`   统一的回复构造（错误提示等）
"""

from .builder import (
    build_platform_output,
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
from .replies import error_result

__all__ = [
    "EventUrlWrapper",
    "build_platform_output",
    "error_result",
    "extract_links_from_event",
    "extract_links_from_text",
    "has_json_component",
    "send_nodes_batched",
    "send_plain_output",
    "try_send_media",
]
