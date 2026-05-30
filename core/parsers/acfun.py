"""AcFun 解析器"""
import re
from typing import ClassVar
from httpx import AsyncClient
from astrbot.api import logger
from ..base_parser import BaseParser, PlatformEnum, ParseException, IgnoreException, handle, COMMON_TIMEOUT
from ..data import Platform


class AcfunParser(BaseParser):
    platform: ClassVar[Platform] = Platform(name=PlatformEnum.ACFUN, display_name="猴山")

    def __init__(self, downloader):
        super().__init__(downloader)
        self.headers["referer"] = "https://www.acfun.cn/"

    @handle("acfun.cn", r"(?:ac=|/ac)(?P<acid>\d+)")
    async def _parse(self, searched: re.Match[str]):
        from ..acfun_models.video import decoder as video_decoder

        acid = int(searched.group("acid"))
        url = f"https://www.acfun.cn/v/ac{acid}"
        query_url = f"{url}?quickViewId=videoInfo_new&ajaxpipe=1"

        async with AsyncClient(headers=self.headers, timeout=COMMON_TIMEOUT) as client:
            response = await client.get(query_url)
            response.raise_for_status()
            raw = response.text

        matched = re.search(r"window\.videoInfo =(.*?)</script>", raw)
        if not matched:
            raise ParseException("解析 acfun 视频信息失败")

        raw_json = str(matched.group(1))
        raw_json = re.sub(r'\\{1,4}"', '"', raw_json)
        raw_json = raw_json.replace('"{', "{").replace('}"', "}")
        video_info = video_decoder.decode(raw_json)

        from ..config import get_config
        pconfig = get_config()

        author = self.create_author(video_info.name, video_info.avatar_url)
        if (duration := video_info.duration) >= pconfig.VIDEO_DURATION_MAXIMUM:
            logger.warning(f"视频时长 {duration} 超过最大限制 {pconfig.VIDEO_DURATION_MAXIMUM}")
            raise IgnoreException

        video_task = self.downloader.download_video(
            video_info.m3u8_url, video_name=f"acfun_{acid}.mp4",
        )
        video_content = self.create_video(video_task, cover_url=video_info.coverUrl)
        return self.result(title=video_info.title, text=video_info.text, author=author,
                          timestamp=video_info.timestamp, contents=[video_content])
