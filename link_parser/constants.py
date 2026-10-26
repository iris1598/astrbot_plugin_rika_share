"""常量和枚举定义"""

import re
from enum import Enum
from typing import Final

from httpx import Timeout

COMMON_HEADER: Final[dict[str, str]] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/55.0.2883.87 UBrowser/6.2.4098.3 Safari/537.36"
    )
}

IOS_HEADER: Final[dict[str, str]] = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1 Edg/132.0.0.0"
    )
}

ANDROID_HEADER: Final[dict[str, str]] = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 15; SM-G998B) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/132.0.0.0 Mobile Safari/537.36 Edg/132.0.0.0"
    )
}

COMMON_TIMEOUT: Final[Timeout] = Timeout(connect=15.0, read=20.0, write=10.0, pool=10.0)

DOWNLOAD_TIMEOUT: Final[Timeout] = Timeout(connect=15.0, read=240.0, write=10.0, pool=10.0)

#: 通用 URL 匹配：用于 Cloudflare 网页截图兜底与 JSON 卡片内的链接提取
GENERIC_URL_PATTERN: Final[re.Pattern[str]] = re.compile(r"https?://[^\s'\"<>]+")

#: 「引用一条含链接的消息 + 回复『下载封面』」的触发词。
#:
#: 用 ``@filter.regex`` 而不是 ``@filter.command``：指令过滤器要求
#: ``event.is_at_or_wake_command``（@ 机器人 / 唤醒前缀 / 引用机器人自己的消息），
#: 而这里要支持「引用**别人**发的链接消息再回一句下载封面」——那种引用不算唤醒。
#: 前置的可选 ``@昵称(id)`` 是 OneBot 适配器把「非第一个 @」写进 message_str 的形态。
COVER_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:@\S+\s*)?[/／]?\s*下载封面(?:图|图片)?\s*$"
)


class PlatformEnum(str, Enum):
    """内置平台的标识（历史常量，新增平台**不需要**在这里登记）。

    取值用于：内置适配器的注册表键名、渲染配色 ``PLATFORM_COLORS`` 的键名。
    新平台直接在适配器里用字面量平台名即可——注册表只校验它是小写标识符
    （见 ``adapters.registry.register_adapter``），配色缺失会自动回退默认色。
    """

    ACFUN = "acfun"
    BILIBILI = "bilibili"
    DOUYIN = "douyin"
    KUAISHOU = "kuaishou"
    NGA = "nga"
    TWITTER = "twitter"
    WEIBO = "weibo"
    XIAOHONGSHU = "xiaohongshu"

    def __str__(self) -> str:
        return self.value
