"""微博接口返回结构模型。

- ``status``      m.weibo.cn 微博正文接口（含转发原微博）
- ``video_show``  h5.video.weibo.com 视频播放接口
- ``article``     头条文章接口

三个模块都定义了 ``decoder``，导出时按语义加前缀区分。
"""

from .article import Detail as ArticleDetail
from .article import decoder as article_decoder
from .status import WeiboData, WeiboResponse
from .status import decoder as status_decoder
from .video_show import DataWrapper, PlayInfo
from .video_show import decoder as video_show_decoder

__all__ = [
    "ArticleDetail",
    "DataWrapper",
    "PlayInfo",
    "WeiboData",
    "WeiboResponse",
    "article_decoder",
    "status_decoder",
    "video_show_decoder",
]
