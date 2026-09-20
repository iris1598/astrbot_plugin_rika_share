"""抖音解析器"""

import re
from typing import ClassVar

from httpx import AsyncClient

from ..config import get_config
from ..constants import COMMON_TIMEOUT, PlatformEnum
from ..exceptions import ParseException
from ..models import ParseResult, Platform
from ..models.platforms.douyin import aweme_decoder
from .base import BaseParser, handle
from .registry import AdapterSpec, register_adapter


class DouyinParser(BaseParser):
    platform: ClassVar[Platform] = Platform(name=PlatformEnum.DOUYIN, display_name="抖音")

    def __init__(self, downloader):
        super().__init__(downloader)
        self.headers.update(
            {
                "Origin": "https://open.douyin.com",
                "Referer": "https://open.douyin.com/",
            }
        )

    @handle("v.douyin", r"v\.douyin\.com/[a-zA-Z0-9_\-]+")
    @handle("jx.douyin", r"jx\.douyin\.com/[a-zA-Z0-9_\-]+")
    async def _parse_short_link(self, searched: re.Match[str]) -> ParseResult:
        url = f"https://{searched.group(0)}"
        return await self.parse_with_redirect(url)

    @handle("douyin", r"douyin\.com/[a-z]+/(?P<aweme_id>\d+)")
    @handle("iesdouyin", r"iesdouyin\.com/share/[a-z]+/(?P<aweme_id>\d+)")
    @handle("m.douyin", r"m\.douyin\.com/share/[a-z]+/(?P<aweme_id>\d+)")
    @handle("jingxuan.douyin", r"jingxuan\.douyin\.com/m/[a-z]+/(?P<aweme_id>\d+)")
    async def _parse_douyin(self, searched: re.Match[str]) -> ParseResult:
        return await self.parse_aweme(searched.group("aweme_id"))

    async def parse_aweme(self, aweme_id: str) -> ParseResult:
        async with AsyncClient(
            headers=self.headers,
            timeout=COMMON_TIMEOUT,
            follow_redirects=True,
            verify=False,
        ) as client:
            response = await client.get(
                "https://www.douyin.com/aweme/v1/web/aweme/detail/",
                params={"aweme_id": aweme_id, "aid": "6383"},
            )
            if response.status_code != 200:
                raise ParseException(f"status: {response.status_code}")
            if not response.content:
                raise ParseException("empty douyin detail response")
            aweme = aweme_decoder.decode(response.content).aweme_detail

        author = self.create_author(
            aweme.author.nickname,
            aweme.author.avatar_url,
        )

        result = self.result(
            title=aweme.share_info.text,
            author=author,
            timestamp=aweme.create_time,
            url=aweme.share_url.split("?")[0] or None,
        )

        if images := aweme.images:
            rebuild_enabled = get_config().DOUYIN_LIVE_PHOTO_ENABLED
            for image in images:
                if image.clip_type == 2 or image.clip_type is None:
                    result.contents.append(self.create_image(image.url_list[-1]))
                elif image_video := image.video:
                    # clip_type==5 实况照片 / clip_type==4 普通动图：
                    # 都是「主图 + 短视频」，统一重建为单文件动态照片
                    if rebuild_enabled:
                        result.contents.append(
                            self.create_live_photo(
                                image.url_list[-1],
                                image_video.url,
                                cover_url=image_video.cover_url,
                                duration=image_video.duration_seconds,
                                is_live_photo=image.is_live_photo,
                            )
                        )
                    else:
                        result.contents.append(self.create_image(image.url_list[-1]))
        elif video := aweme.video:
            self._add_limit_warning(result, video.duration_seconds)
            result.video = self.create_video(
                video.url,
                video.cover_url,
                video.duration_seconds,
            )

        return result


ADAPTER = register_adapter(
    AdapterSpec(
        name=PlatformEnum.DOUYIN.value,
        url_pattern=re.compile(
            r"(v\.douyin\.com|douyin\.com|iesdouyin\.com|m\.douyin\.com"
            r"|jx\.douyin\.com|jingxuan\.douyin\.com)"
        ),
        parser_cls=DouyinParser,
        description="视频 / 图文动态（含实况照片与动图重建）",
    )
)
