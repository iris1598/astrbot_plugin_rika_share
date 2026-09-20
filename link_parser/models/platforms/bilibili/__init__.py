"""B站接口返回结构模型。

- ``author``        账号信息（``Upper``）
- ``video_info``    视频信息、分P 与 AI 总结
- ``dynamic``       动态（含转发原动态）
- ``opus``          图文动态
- ``live_room``     直播间信息
- ``favorite_list`` 收藏夹
"""

from .author import Upper
from .dynamic import DynamicInfo, DynamicWrapper
from .favorite_list import FavData, FavInfo, FavItem
from .live_room import RoomData
from .opus import OpusItem
from .video_info import AIConclusion, Page, PageInfo, Stats, VideoInfo

__all__ = [
    "AIConclusion",
    "DynamicInfo",
    "DynamicWrapper",
    "FavData",
    "FavInfo",
    "FavItem",
    "OpusItem",
    "Page",
    "PageInfo",
    "RoomData",
    "Stats",
    "Upper",
    "VideoInfo",
]
