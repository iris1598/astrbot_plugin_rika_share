"""快手解析器"""

import re
from typing import ClassVar

from httpx import AsyncClient

from ..constants import PlatformEnum
from ..exceptions import ParseException
from ..models import Platform
from ..models.platforms.kuaishou import init_state_decoder
from .base import BaseParser, handle
from .registry import AdapterSpec, register_adapter


class KuaiShouParser(BaseParser):
    platform: ClassVar[Platform] = Platform(name=PlatformEnum.KUAISHOU, display_name="快手")

    #: 分享短链：需先跟随跳转才能拿到作品 ID
    SHORT_LINK_KEYWORDS = ("v.kuaishou.com", "chenzhongtech.com")
    #: handle 正则未命名分组，这里补一条：/fw/photo/{id}、/fw/long-video/{id}、/short-video/{id}
    IDENTITY_PATTERNS = (
        (
            "photo",
            re.compile(r"/(?:fw/(?:photo|long-video)|short-video)/(?P<id>[A-Za-z0-9_-]+)"),
        ),
    )

    def __init__(self, downloader):
        super().__init__(downloader)
        self.ios_headers["Referer"] = "https://v.kuaishou.com/"

    def short_link_headers(self) -> dict[str, str]:
        """短链跳转需带移动端 UA / Referer，与解析时保持一致。"""
        return self.ios_headers

    @handle("v.kuaishou", r"v\.kuaishou\.com/[A-Za-z\d._?%&+\-=/#]+")
    @handle("kuaishou", r"(?:www\.)?kuaishou\.com/[A-Za-z\d._?%&+\-=/#]+")
    @handle("chenzhongtech", r"(?:v\.m\.)?chenzhongtech\.com/fw/[A-Za-z\d._?%&+\-=/#]+")
    async def _parse_v_kuaishou(self, searched: re.Match[str]):
        url = f"https://{searched.group(0)}"
        real_url = await self.get_redirect_url(url, headers=self.ios_headers)
        if len(real_url) <= 0:
            raise ParseException("failed to get location url from url")

        real_url = real_url.replace("/fw/long-video/", "/fw/photo/")
        async with AsyncClient(headers=self.ios_headers, timeout=self.timeout) as client:
            response = await client.get(real_url)
            response.raise_for_status()
            response_text = response.text

        pattern = r"window\.INIT_STATE\s*=\s*(.*?)</script>"
        matched = re.search(pattern, response_text)
        if not matched:
            raise ParseException("failed to parse video JSON info from HTML")

        raw = matched.group(1).strip()
        data_map = init_state_decoder.decode(raw)
        photo = next((d.photo for d in data_map.values() if d.photo is not None), None)
        if photo is None:
            raise ParseException("window.init_state don't contains videos or pics")

        author = self.create_author(photo.name, photo.head_url)
        result = self.result(title=photo.caption, author=author, contents=[], timestamp=photo.timestamp // 1000)

        if video_url := photo.video_url:
            self._add_limit_warning(result, photo.duration_in_seconds)
            result.video = self.create_video(video_url, photo.cover_url, photo.duration_in_seconds)
        if img_urls := photo.img_urls:
            result.contents.extend(self.create_images(img_urls))
        return result


ADAPTER = register_adapter(
    AdapterSpec(
        name=PlatformEnum.KUAISHOU.value,
        url_pattern=re.compile(r"(v\.kuaishou\.com|kuaishou\.com|chenzhongtech\.com)"),
        parser_cls=KuaiShouParser,
        description="视频 / 图文",
        priority=30,
    )
)
