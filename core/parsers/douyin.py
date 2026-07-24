"""抖音解析器"""
import re
from typing import ClassVar
from httpx import AsyncClient
from astrbot.api import logger
from ..base_parser import BaseParser, PlatformEnum, ParseException, handle, COMMON_TIMEOUT
from ..data import Platform


class DouyinParser(BaseParser):
    platform: ClassVar[Platform] = Platform(name=PlatformEnum.DOUYIN, display_name="抖音")

    @handle("v.douyin", r"v\.douyin\.com/[a-zA-Z0-9_\-]+")
    @handle("jx.douyin", r"jx\.douyin\.com/[a-zA-Z0-9_\-]+")
    async def _parse_short_link(self, searched: re.Match[str]):
        url = f"https://{searched.group(0)}"
        return await self.parse_with_redirect(url)

    @handle("douyin", r"douyin\.com/(?P<ty>video|note)/(?P<vid>\d+)")
    @handle("iesdouyin", r"iesdouyin\.com/share/(?P<ty>slides|video|note)/(?P<vid>\d+)")
    @handle("m.douyin", r"m\.douyin\.com/share/(?P<ty>slides|video|note)/(?P<vid>\d+)")
    @handle("jingxuan.douyin", r"jingxuan\.douyin.com/m/(?P<ty>slides|video|note)/(?P<vid>\d+)")
    async def _parse_douyin(self, searched: re.Match[str]):
        ty, vid = searched.group("ty"), searched.group("vid")
        if ty == "slides":
            return await self.parse_slides(vid)
        for url in (self._build_m_douyin_url(ty, vid), self._build_iesdouyin_url(ty, vid)):
            try:
                return await self.parse_video(url)
            except ParseException as e:
                logger.warning(f"failed to parse {url}, error: {e}")
                continue
        raise ParseException("分享已删除或资源直链提取失败, 请稍后再试")

    @staticmethod
    def _build_iesdouyin_url(ty: str, vid: str) -> str:
        return f"https://www.iesdouyin.com/share/{ty}/{vid}"

    @staticmethod
    def _build_m_douyin_url(ty: str, vid: str) -> str:
        return f"https://m.douyin.com/share/{ty}/{vid}"

    async def parse_video(self, url: str):
        from ..douyin_models.video import decoder as video_decoder

        async with AsyncClient(headers=self.ios_headers, timeout=COMMON_TIMEOUT, follow_redirects=False, verify=False) as client:
            response = await client.get(url)
            if response.status_code != 200:
                raise ParseException(f"status: {response.status_code}")
            text = response.text

        pattern = re.compile(pattern=r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", flags=re.DOTALL)
        matched = pattern.search(text)
        if not matched or not matched.group(1):
            raise ParseException("can't find _ROUTER_DATA in html")

        video_data = video_decoder.decode(matched.group(1).strip()).video_data
        author = self.create_author(video_data.author.nickname, video_data.avatar_url)
        result = self.result(title=video_data.desc, author=author, timestamp=video_data.create_time)

        if image_urls := video_data.image_urls:
            result.contents.extend(self.create_images(image_urls))
        elif video_url := video_data.video_url:
            self._add_limit_warning(result, video_data.duration)
            result.video = self.create_video(video_url, video_data.cover_url, video_data.duration)
        return result

    async def parse_slides(self, video_id: str):
        from ..douyin_models.slides import decoder as slides_decoder

        url = "https://www.iesdouyin.com/web/api/v2/aweme/slidesinfo/"
        params = {"aweme_ids": f"[{video_id}]", "request_source": "200"}
        async with AsyncClient(headers=self.android_headers, verify=False) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()

        slides_data = slides_decoder.decode(response.content).aweme_details[0]
        author = self.create_author(slides_data.name, slides_data.avatar_url)
        result = self.result(title=slides_data.desc, author=author, timestamp=slides_data.create_time)

        if dynamic_urls := slides_data.dynamic_urls:
            for dynamic_url in dynamic_urls:
                result.contents.append(self.create_gif(dynamic_url))
        elif image_urls := slides_data.image_urls:
            result.contents.extend(self.create_images(image_urls))
        return result
