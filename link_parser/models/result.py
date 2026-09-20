"""解析结果模型：平台信息、作者与 :class:`ParseResult`。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict

from .content import ImageContent, MediaContent, VideoContent
from .task import PathTask


@dataclass(slots=True)
class Platform:
    """平台标识。``name`` 与 ``PlatformEnum`` 取值一致，``display_name`` 用于展示。"""

    name: str
    display_name: str


@dataclass(repr=False, slots=True)
class Author:
    """作者信息（昵称 / 头像 / 签名）。"""

    name: str
    avatar: PathTask | None = None
    description: str | None = None

    def __repr__(self) -> str:
        repr = f"Author(name={self.name}"
        if self.avatar:
            repr += f", avatar={self.avatar}"
        if self.description:
            repr += f", description={self.description}"
        return repr + ")"


@dataclass(repr=False, slots=True)
class ParseResult:
    """完整的解析结果"""

    platform: Platform
    author: Author | None = None
    title: str | None = None
    text: str | None = None
    timestamp: int | None = None
    url: str | None = None
    contents: list[MediaContent] = field(default_factory=list)
    graphics: list[str | ImageContent] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    repost: ParseResult | None = None
    render_image: Path | None = None

    @property
    def video(self) -> VideoContent | None:
        if len(self.contents) != 1:
            return None
        cont = self.contents[0]
        return cont if isinstance(cont, VideoContent) and not cont.is_image_like else None

    @video.setter
    def video(self, video: VideoContent | None):
        if video is not None and len(self.contents) == 0:
            self.contents.append(video)

    @property
    def img_contents(self) -> list[ImageContent]:
        return [cont for cont in self.contents if isinstance(cont, ImageContent)]

    @property
    def all_grid_images(self) -> list[PathTask]:
        """图集渲染用的全部图片路径任务（含视频封面）。"""
        covers: list[PathTask] = []
        for cont in self.contents:
            if isinstance(cont, VideoContent):
                if cont.cover is not None:
                    covers.append(cont.cover)
            elif isinstance(cont, ImageContent):
                covers.append(cont.path_task)
        return covers

    @property
    def content_type(self) -> str:
        """内容类型文案：优先取 ``extra['content_type']``，否则按内容推断。"""
        content_type = self.extra.get("content_type")
        if content_type is None:
            if self.video:
                return "视频"
            elif self.graphics:
                return "图文"
            else:
                return "动态"
        return content_type

    def __repr__(self) -> str:
        return (
            f"platform: {self.platform.display_name}, "
            f"timestamp: {self.timestamp}, "
            f"title: {self.title}, "
            f"text: {self.text}, "
            f"url: {self.url}, "
            f"author: {self.author}, "
            f"video: {self.video}, "
            f"contents: {self.contents}, "
            f"graphics: {self.graphics}, "
            f"extra: {self.extra}, "
            f"repost: <<<<<<<{self.repost}>>>>>>, "
            f"render_image: {self.render_image.name if self.render_image else 'None'}"
        )


class ParseResultKwargs(TypedDict, total=False):
    """``BaseParser.result()`` 接受的关键字参数。"""

    title: str | None
    text: str | None
    contents: list[MediaContent]
    graphics: list[str | ImageContent]
    timestamp: int | None
    url: str | None
    author: Author | None
    extra: dict[str, Any]
    repost: ParseResult | None
