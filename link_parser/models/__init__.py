"""数据类型层：解析结果、媒体内容与路径任务。

各平台接口返回结构的模型放在 ``models/platforms/<平台>/`` 子包中，与解析逻辑解耦。
"""

from .content import AudioContent, ImageContent, MediaContent, VideoContent
from .result import Author, ParseResult, ParseResultKwargs, Platform
from .task import PathTask

__all__ = [
    "AudioContent",
    "Author",
    "ImageContent",
    "MediaContent",
    "ParseResult",
    "ParseResultKwargs",
    "PathTask",
    "Platform",
    "VideoContent",
]
