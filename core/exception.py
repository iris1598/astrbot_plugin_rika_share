"""异常类定义"""
import asyncio


class ParseException(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class DownloadException(ParseException):
    """下载异常"""

    def __init__(self, message: str | None = None):
        super().__init__(message or "媒体下载失败")


class IgnoreException(ParseException):
    """可忽略异常"""

    def __init__(self, message: str | None = None):
        super().__init__(message or "可忽略异常")


class TipException(ParseException):
    """提示异常"""


class SilentException(ParseException):
    """静默异常 - 不发送通知，仅静默忽略"""


def is_timeout_exception(e: Exception) -> bool:
    """判断消息发送/网络 API 异常是否为超时异常（如 NapCat/NTQQ retcode=1200 invoke timeout）。

    在 OneBot / NTQQ 协议端框架中，主动发送图片等大文件时 API 响应可能会超时（如 retcode 1200 / invoke timeout），
    但底层的发送任务实际上已被提交给 NTQQ 客户端并会在后台异步完成发送。
    此时如果捕获到异常并回退重发，会导致底层发送成功 + 回退发送发出了两张相同的图片。
    """
    if isinstance(e, (asyncio.TimeoutError, TimeoutError)):
        return True
    err_str = str(e).lower()
    if "timeout" in err_str or "timed out" in err_str:
        return True
    retcode = getattr(e, "retcode", None) or getattr(e, "code", None)
    if retcode == 1200:
        return True
    return False

