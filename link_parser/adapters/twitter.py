"""Twitter/X 解析器"""

import re
from typing import ClassVar
from urllib.parse import urlsplit

from httpx import AsyncClient
from astrbot.api import logger
from msgspec import Struct, field
from msgspec.json import Decoder

from ..constants import PlatformEnum
from ..models import ParseResult, Platform
from .base import BaseParser, handle
from .registry import AdapterSpec, register_adapter

# 需要走反代的 X 域名 -> Worker 路径前缀
# pbs/video 为官方媒体 CDN，api 为解析接口 api.vxtwitter.com
_PROXY_PATH_PREFIX = {
    "pbs.twimg.com": "pbs",
    "video.twimg.com": "video",
    "api.vxtwitter.com": "api",
}


def proxy_url(url: str | None) -> str | None:
    """将 X 官方媒体 CDN / 解析接口地址改写为自定义反代地址"""
    if not url:
        return url
    from ..config import get_config

    config = get_config()
    if not config.TWITTER_MEDIA_PROXY_ENABLED:
        return url
    base = config.TWITTER_MEDIA_PROXY_BASE
    if not base:
        return url
    parts = urlsplit(url)
    prefix = _PROXY_PATH_PREFIX.get(parts.netloc.lower())
    if prefix is None:
        return url
    query = f"?{parts.query}" if parts.query else ""
    return f"{base}/{prefix}{parts.path}{query}"


class MediaElement(Struct):
    type: str
    url: str
    altText: str | None = None
    thumbnail_url: str | None = None
    duration_millis: int | None = None

    @property
    def duration(self) -> float | None:
        return self.duration_millis / 1000 if self.duration_millis else None

    @property
    def original_url(self) -> str:
        return self.url + "?name=orig"


class Article(Struct):
    image: str | None = None
    preview_text: str | None = None
    title: str | None = None


class VxTwitterResponse(Struct):
    article: str | Article | None
    date_epoch: int
    fetched_on: int
    likes: int
    text: str
    user_name: str
    user_screen_name: str
    user_profile_image_url: str
    qrt: "VxTwitterResponse | None" = None
    qrtURL: str | None = None
    media_extended: list[MediaElement] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"{self.user_name} @{self.user_screen_name}"


vx_decoder = Decoder(VxTwitterResponse)


class TwitterParser(BaseParser):
    platform: ClassVar[Platform] = Platform(name=PlatformEnum.TWITTER, display_name="小蓝鸟")

    #: handle 正则未命名分组，这里补一条：同一推文的不同分享形式统一按 status_id 归并
    IDENTITY_PATTERNS = (
        ("status", re.compile(r"/status(?:es)?/(?P<id>\d+)")),
    )

    @handle("x.com", r"x\.com/[0-9-a-zA-Z_]{1,20}/status/([0-9]+)")
    async def _parse(self, searched: re.Match[str]) -> ParseResult:
        url = f"https://{searched.group(0)}"
        return await self.parse_by_vxapi(url)

    async def parse_by_vxapi(self, url: str):
        api_url = url.replace("x.com", "api.vxtwitter.com")
        proxy_api_url = proxy_url(api_url)
        async with AsyncClient(headers=self.headers, timeout=self.timeout) as client:
            if proxy_api_url and proxy_api_url != api_url:
                try:
                    return await self._fetch_vxapi(client, proxy_api_url)
                except Exception as e:
                    logger.warning(f"X 反代解析失败，回退直连 {api_url}: {e}")
            return await self._fetch_vxapi(client, api_url)

    async def _fetch_vxapi(self, client: AsyncClient, api_url: str) -> ParseResult:
        response = await client.get(api_url)
        response.raise_for_status()
        data = vx_decoder.decode(response.content)
        return self._collect_result(data)

    def _collect_result(self, data: VxTwitterResponse) -> ParseResult:
        author = self.create_author(data.user_name, proxy_url(data.user_profile_image_url))
        title = data.article.title if isinstance(data.article, Article) else data.article
        result = self.result(author=author, title=title, text=data.text, timestamp=data.date_epoch)
        for media in data.media_extended:
            if media.type in ["video", "gif"]:
                self._add_limit_warning(result, media.duration)
                video = self.create_video(
                    proxy_url(media.url),
                    proxy_url(media.thumbnail_url),
                    duration=media.duration,
                    is_gif=media.type == "gif",
                )
                result.contents.append(video)
            elif media.type == "image":
                result.contents.append(self.create_image(proxy_url(media.original_url)))
        if data.qrt:
            result.repost = self._collect_result(data.qrt)
        return result


ADAPTER = register_adapter(
    AdapterSpec(
        name=PlatformEnum.TWITTER.value,
        url_pattern=re.compile(r"x\.com"),
        parser_cls=TwitterParser,
        description="推文 / 媒体（支持自定义反代）",
    )
)
