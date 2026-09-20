"""回复结果构造。"""

from astrbot.api.event import AstrMessageEvent, MessageEventResult

from ..config import get_config


def error_result(event: AstrMessageEvent, message: str) -> MessageEventResult | None:
    """根据配置生成错误回复；关闭发送开关时不向对话发送。"""
    if not get_config().SEND_ERROR_MESSAGES:
        return None
    return event.plain_result(message)
