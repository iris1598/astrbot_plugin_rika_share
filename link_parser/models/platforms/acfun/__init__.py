"""AcFun 接口返回结构模型。

- ``video_info``：`videoInfo_new` 接口返回的视频信息与 m3u8 播放列表
"""

from .video_info import CurrentVideoInfo, KsPlay, Representation, User, VideoInfo
from .video_info import decoder as video_info_decoder

__all__ = [
    "CurrentVideoInfo",
    "KsPlay",
    "Representation",
    "User",
    "VideoInfo",
    "video_info_decoder",
]
