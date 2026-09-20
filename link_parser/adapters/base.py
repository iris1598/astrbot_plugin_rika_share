"""平台解析适配器基类。

所有平台适配器都继承 :class:`BaseParser`，并用 :func:`handle` 声明「URL 关键词 →
处理函数」的映射；``search_url()`` 会按关键词长度优先匹配，命中后由 ``parse()``
调用对应处理函数。

适配器的平台声明、URL 触发正则与构建方式统一在
:mod:`link_parser.adapters.registry` 中注册，入口文件只依赖注册表。
"""

import asyncio
from pathlib import Path
from re import Match, Pattern, compile
from typing import ClassVar, final
from typing_extensions import Unpack

from ..constants import IOS_HEADER, COMMON_HEADER, ANDROID_HEADER, COMMON_TIMEOUT
from ..exceptions import ParseException, IgnoreException, SilentException
from ..models import (
    AudioContent,
    Author,
    ImageContent,
    ParseResult,
    ParseResultKwargs,
    PathTask,
    Platform,
    VideoContent,
)
from ..services.downloader import StreamDownloader

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

    def __init__(self, downloader: StreamDownloader):
        self.headers = COMMON_HEADER.copy()
        self.ios_headers = IOS_HEADER.copy()
        self.android_headers = ANDROID_HEADER.copy()
        self.downloader = downloader
        self.timeout = COMMON_TIMEOUT

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

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

    def create_video(self, url_or_task: str | asyncio.Task[Path] | PathTask, cover_url: str | None = None, duration: float | None = None, is_gif: bool = False):
        if duration is not None:
            from ..config import get_config
            from ..utils.formatting import fmt_duration
            pconfig = get_config()
            if duration > pconfig.VIDEO_DURATION_MAXIMUM:
                from astrbot.api import logger
                logger.warning(
                    f"视频时长 {fmt_duration(duration)} "
                    f"超过限制 {fmt_duration(pconfig.VIDEO_DURATION_MAXIMUM)}, 跳过下载"
                )
                # 模仿 B站：创建一个 download_video 闭包，被 await 时抛出 IgnoreException
                # 这样解析结果能正常返回（标题/作者/封面），但实际不下载视频
                async def _skip_video_download():
                    raise IgnoreException(
                        f"视频时长({fmt_duration(duration)})超过限制({fmt_duration(pconfig.VIDEO_DURATION_MAXIMUM)})，跳过下载"
                    )
                path_task = _skip_video_download()
                video_content = VideoContent(PathTask(path_task), duration=duration, is_gif=is_gif)
                if cover_url:
                    video_content.cover = PathTask(
                        self.downloader.download_img(cover_url, ext_headers=self.headers)
                    )
                return video_content

        if isinstance(url_or_task, str):
            path_task = PathTask(self.downloader.download_video(url_or_task, ext_headers=self.headers))
        elif isinstance(url_or_task, PathTask):
            path_task = url_or_task
        else:
            path_task = PathTask(url_or_task)

        video_content = VideoContent(path_task, duration=duration, is_gif=is_gif)

        if cover_url:
            cover_task = self.downloader.download_img(cover_url, ext_headers=self.headers)
        else:
            async def extract_cover():
                from ..utils.media import extract_video_first_frame
                video_path = await path_task.get()
                return await extract_video_first_frame(video_path)
            cover_task = extract_cover()

        video_content.cover = PathTask(cover_task)

        if is_gif:
            async def convert_to_gif():
                from ..utils.media import convert_video_to_gif
                video_path = await path_task.get()
                return await convert_video_to_gif(video_path)
            video_content.gif_path = PathTask(convert_to_gif())

        return video_content

    def _add_limit_warning(self, result: ParseResult, duration: float | None):
        """检查视频时长，超限时添加 limit_warnings 到 result.extra（参考 B站实现）"""
        if duration is not None:
            from ..config import get_config
            from ..utils.formatting import fmt_duration
            pconfig = get_config()
            if duration > pconfig.VIDEO_DURATION_MAXIMUM:
                from astrbot.api import logger
                msg = (
                    f"⚠️ 视频时长({fmt_duration(duration)})"
                    f"超过限制({fmt_duration(pconfig.VIDEO_DURATION_MAXIMUM)})，不会下载视频"
                )
                logger.warning(msg)
                result.extra.setdefault("limit_warnings", []).append(msg)

    def create_live_photo(
        self,
        image_url: str,
        video_url: str,
        cover_url: str | None = None,
        duration: float | None = None,
        is_live_photo: bool = True,
    ):
        """「主图(JPEG) + 短视频(MP4)」重建为单文件动态照片。

        主图与视频各自独立下载，再合成为一个 JPEG 文件（XMP 索引 + 尾部视频）。
        合成失败时回退为静态主图，保证内容不会整个丢失。

        Args:
            is_live_photo: 源内容是否被平台标记为实况照片（抖音 clip_type==5）。
                普通动图(clip_type==4)走同一条重建路径，但文案上不算实况照片。

        Note:
            这类附带动图本身就是 2~4 秒的短片，不做时长上限判断。
        """
        still_task = asyncio.ensure_future(
            self.downloader.download_img(image_url, ext_headers=self.headers)
        )
        still_path_task = PathTask(still_task)
        video_path_task = PathTask(
            self.downloader.download_video(video_url, ext_headers=self.headers)
        )

        video_content = VideoContent(
            video_path_task, duration=duration, is_live_photo=is_live_photo
        )
        # 封面：优先用平台给的封面图，没有就直接用主图
        if cover_url:
            video_content.cover = PathTask(
                self.downloader.download_img(cover_url, ext_headers=self.headers)
            )
        else:
            video_content.cover = still_path_task

        async def build_live_photo():
            from astrbot.api import logger
            from ..services.live_photo import create_motion_photo

            try:
                still_path = await still_path_task.get()
            except Exception as e:
                # 主图都没拿到，只能让上层去发原始视频
                logger.warning(f"实况照片主图获取失败，回退为原始视频: {e}")
                return None

            try:
                video_path = await video_path_task.get()
                dest = video_path.with_name(f"{video_path.stem}_live.jpg")
                return await create_motion_photo(still_path, video_path, dest)
            except Exception as e:
                logger.warning(f"实况照片重建失败，回退为静态主图: {e}")
                return still_path

        video_content.live_photo_path = PathTask(build_live_photo())
        return video_content

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
