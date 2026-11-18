"""酷安接口返回结构模型。

- ``feed_info``：`/v6/feed/detail` 接口返回的动态信息
"""

from .feed_info import FeedInfo, FeedResponse
from .feed_info import decoder as feed_decoder

__all__ = [
    "FeedInfo",
    "FeedResponse",
    "feed_decoder",
]
