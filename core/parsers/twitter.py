"""Twitter/X 解析器"""
import re
from typing import ClassVar
from httpx import AsyncClient
from msgspec import Struct, field
from msgspec.json import Decoder
from ..base_parser import BaseParser, PlatformEnum, handle
from ..data import Platform, ParseResult


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
        return self.url + "?format=jpg&name=orig"


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

    @handle("x.com", r"x\.com/[0-9-a-zA-Z_]{1,20}/status/([0-9]+)")
    async def _parse(self, searched: re.Match[str]) -> ParseResult:
        url = f"https://{searched.group(0)}"
        return await self.parse_by_vxapi(url)

    async def parse_by_vxapi(self, url: str):
        api_url = url.replace("x.com", "api.vxtwitter.com")
        async with AsyncClient(headers=self.headers, timeout=self.timeout) as client:
            response = await client.get(api_url)
            response.raise_for_status()
        data = vx_decoder.decode(response.content)
        return self._collect_result(data)

    def _collect_result(self, data: VxTwitterResponse) -> ParseResult:
        author = self.create_author(data.user_name, data.user_profile_image_url)
        title = data.article.title if isinstance(data.article, Article) else data.article
        result = self.result(author=author, title=title, text=data.text, timestamp=data.date_epoch)
        for media in data.media_extended:
            if media.type in ["video", "gif"]:
                self._add_limit_warning(result, media.duration)
                video = self.create_video(media.url, media.thumbnail_url, duration=media.duration, is_gif=media.type == "gif")
                result.contents.append(video)
            elif media.type == "image":
                result.contents.append(self.create_image(media.original_url))
        if data.qrt:
            result.repost = self._collect_result(data.qrt)
        return result
