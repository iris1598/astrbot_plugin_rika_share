"""媒体内容模型：图片 / 视频 / 音频。

所有内容都通过 :class:`PathTask` 惰性持有下载任务，只有在真正需要落盘路径时
才会被 await，从而让「解析」与「下载」并行进行。
"""

from __future__ import annotations

from dataclasses import dataclass

from .task import PathTask


@dataclass(repr=False, slots=True)
class MediaContent:
    """媒体内容基类：仅持有一个惰性路径任务。"""

    path_task: PathTask

    def __repr__(self) -> str:
        prefix = self.__class__.__name__
        return f"{prefix}({self.path_task})"


@dataclass(repr=False, slots=True)
class AudioContent(MediaContent):
    """音频内容"""

    duration: float | None = None


@dataclass(repr=False, slots=True)
class VideoContent(MediaContent):
    """视频内容。

    其中 ``is_gif`` / ``gif_path`` 仅 Twitter 解析在用（其媒体本身就带 gif 类型）；
    抖音的「主图 + 短视频」统一走 ``live_photo_path``（单文件动态照片）。
    """

    cover: PathTask | None = None
    duration: float | None = None
    is_gif: bool = False
    gif_path: PathTask | None = None
    # 源内容在平台上被标记为实况照片（抖音 clip_type==5），仅用于文案区分
    is_live_photo: bool = False
    # 「主图 + 短视频」重建出的单文件动态照片（失败时为主图静态图）
    live_photo_path: PathTask | None = None

    @property
    def is_image_like(self) -> bool:
        """已重建为图片类产物（动态照片 / Twitter 动图）：
        对外以图片形式发送，而不是当视频再发一遍"""
        return self.is_gif or self.live_photo_path is not None

    @property
    def still_path(self) -> PathTask | None:
        """对外发送的图片文件（Twitter 动图 .gif / 动态照片 .jpg）"""
        return self.gif_path if self.is_gif else self.live_photo_path

    def __repr__(self) -> str:
        repr = f"VideoContent({self.path_task}"
        if self.cover is not None:
            repr += f", cover={self.cover}"
        if self.duration:
            repr += f", duration={self.duration}"
        if self.is_live_photo:
            repr += ", live_photo=True"
        return repr + ")"


@dataclass(repr=False, slots=True)
class ImageContent(MediaContent):
    """图片内容"""

    alt: str | None = None
