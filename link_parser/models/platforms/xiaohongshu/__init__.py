"""小红书接口返回结构模型。

- ``explore_page``   笔记分享页 ``window.__INITIAL_STATE__``（explore 链接）
- ``discovery_page`` 笔记分享页 ``window.__INITIAL_STATE__``（discovery 链接）
- ``note``           两种页面共用的笔记视频流结构

两个页面模块都定义了 ``InitialState`` 与 ``decoder``，导出时按页面加前缀区分。
"""

from .discovery_page import InitialState as DiscoveryInitialState
from .discovery_page import NoteData, NormalNotePreloadData
from .discovery_page import decoder as discovery_decoder
from .explore_page import InitialState as ExploreInitialState
from .explore_page import NoteDetail
from .explore_page import decoder as explore_decoder
from .note import Media, Stream, StreamItem, Video

__all__ = [
    "DiscoveryInitialState",
    "ExploreInitialState",
    "Media",
    "NoteData",
    "NoteDetail",
    "NormalNotePreloadData",
    "Stream",
    "StreamItem",
    "Video",
    "discovery_decoder",
    "explore_decoder",
]
