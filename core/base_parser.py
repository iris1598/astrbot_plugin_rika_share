"""BaseParser 基类 - 所有平台解析器的基类"""

import asyncio
import re
from abc import ABC
from pathlib import Path
from re import Match, Pattern, compile
from typing import Any, ClassVar, cast, final
from typing_extensions import Unpack

from .data import Platform, ParseResult, Author, VideoContent, ImageContent, AudioContent, ParseResultKwargs
from .task import PathTask
from .download import StreamDownloader
from .constants import IOS_HEADER, COMMON_HEADER, ANDROID_HEADER, COMMON_TIMEOUT, PlatformEnum
from .exception import ParseException, IgnoreException, DownloadException, SilentException

HandlerFunc = Any
KeyPatterns = list[tuple[str, Pattern[str]]]

_KEY_PATTERNS = "_key_patterns"


def handle(keyword: str, pattern: str):
    """注册处理器装饰器"""
    def decorator(func):
        if not hasattr(func, _KEY_PATTERNS):
            setattr(func, _KEY_PATTERNS, [])
        key_patterns: KeyPatterns = getattr(func, _KEY_PATTERNS)
        key_patterns.append((keyword, compile(pattern)))
        return func
    return decorator


class BaseParser:
    platform: ClassVar[Platform]
    _registry: ClassVar[list[type["BaseParser"]]] = []

    def __init__(self, downloader: StreamDownloader):
        self.headers = COMMON_HEADER.copy()
        self.ios_headers = IOS_HEADER.copy()
        self.android_headers = ANDROID_HEADER.copy()
        self.downloader = downloader
        self.timeout = COMMON_TIMEOUT

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if ABC not in cls.__bases__:
            BaseParser._registry.append(cls)

        cls._handlers = {}
        cls._key_patterns = []

        for attr_name in dir(cls):
            attr = getattr(cls, attr_name)
            if callable(attr) and hasattr(attr, _KEY_PATTERNS):
                key_patterns: KeyPatterns = getattr(attr, _KEY_PATTERNS)
                for keyword, pattern in key_patterns:
                    cls._handlers[keyword] = attr
                    cls._key_patterns.append((keyword, pattern))

        cls._key_patterns.sort(key=lambda x: -len(x[0]))

    @classmethod
    def get_all_subclass(cls) -> list[type["BaseParser"]]:
        return cls._registry

    @final
    async def parse(self, keyword: str, searched: Match[str]) -> ParseResult:
        return await self._handlers[keyword](self, searched)

    @final
    async def parse_with_redirect(self, url: str, headers: dict[str, str] | None = None) -> ParseResult:
        redirect_url = await self.get_redirect_url(url, headers=headers or self.headers)
        if redirect_url == url:
            raise ParseException(f"无法重定向 URL: {url}")
        keyword, searched = self.search_url(redirect_url)
        return await self.parse(keyword, searched)

    @classmethod
    def search_url(cls, url: str) -> tuple[str, Match[str]]:
        for keyword, pattern in cls._key_patterns:
            if keyword not in url:
                continue
            if searched := pattern.search(url):
                return keyword, searched
        raise SilentException(f"无法匹配 {url}")

    @classmethod
    def result(cls, **kwargs: Unpack[ParseResultKwargs]) -> ParseResult:
        return ParseResult(platform=cls.platform, **kwargs)

    @staticmethod
    async def get_redirect_url(url: str, headers: dict[str, str] | None = None) -> str:
        from httpx import AsyncClient
        headers = headers or COMMON_HEADER.copy()
        async with AsyncClient(headers=headers, verify=False, follow_redirects=False, timeout=COMMON_TIMEOUT) as client:
            response = await client.get(url)
            if response.status_code >= 400:
                response.raise_for_status()
            return response.headers.get("Location", url)

    @staticmethod
    async def get_final_url(url: str, headers: dict[str, str] | None = None) -> str:
        from httpx import AsyncClient
        headers = headers or COMMON_HEADER.copy()
        async with AsyncClient(headers=headers, verify=False, follow_redirects=True, timeout=COMMON_TIMEOUT) as client:
            response = await client.get(url)
            if response.status_code >= 400:
                response.raise_for_status()
            return str(response.url)

    def create_author(self, name: str, avatar_url: str | None = None, description: str | None = None):
        author = Author(name=name, description=description)
        if avatar_url:
            author.avatar = PathTask(self.downloader.download_img(avatar_url, ext_headers=self.headers))
        return author

    def create_video(self, url_or_task: str | asyncio.Task[Path], cover_url: str | None = None, duration: float | None = None, is_gif: bool = False):
        if isinstance(url_or_task, str):
            path_task = self.downloader.download_video(url_or_task, ext_headers=self.headers)
        else:
            path_task = url_or_task

        video_content = VideoContent(PathTask(path_task), duration=duration, is_gif=is_gif)

        if cover_url:
            cover_task = self.downloader.download_img(cover_url, ext_headers=self.headers)
        else:
            async def extract_cover():
                from .utils import extract_video_first_frame
                video_path = await path_task
                return await extract_video_first_frame(video_path)
            cover_task = extract_cover()

        video_content.cover = PathTask(cover_task)

        if is_gif:
            async def convert_to_gif():
                from .utils import convert_video_to_gif
                video_path = await path_task
                return await convert_video_to_gif(video_path)
            video_content.gif_path = PathTask(convert_to_gif())

        return video_content

    def create_gif(self, url_or_task: str | asyncio.Task[Path], cover_url: str | None = None):
        return self.create_video(url_or_task, cover_url=cover_url, is_gif=True)

    def create_images(self, image_urls: list[str]):
        contents: list[ImageContent] = []
        for url in image_urls:
            task = self.downloader.download_img(url, ext_headers=self.headers)
            contents.append(ImageContent(PathTask(task)))
        return contents

    def create_image(self, url_or_task: str | asyncio.Task[Path], alt: str | None = None):
        if isinstance(url_or_task, str):
            path_task = self.downloader.download_img(url_or_task, ext_headers=self.headers)
        else:
            path_task = url_or_task
        return ImageContent(PathTask(path_task), alt=alt)

    def create_audio(self, url_or_task: str | asyncio.Task[Path], duration: float = 0.0):
        if isinstance(url_or_task, str):
            path_task = self.downloader.download_audio(url_or_task, ext_headers=self.headers)
        else:
            path_task = url_or_task
        return AudioContent(PathTask(path_task), duration)
