"""抖音接口返回结构模型。

- ``aweme``：`aweme/v1/web/aweme/detail` 接口返回的作品详情（图片 / 视频 / 实况照片）
"""

from .aweme import Author, Aweme, Image, Response, ShareInfo, Video
from .aweme import decoder as aweme_decoder

__all__ = [
    "Author",
    "Aweme",
    "Image",
    "Response",
    "ShareInfo",
    "Video",
    "aweme_decoder",
]
