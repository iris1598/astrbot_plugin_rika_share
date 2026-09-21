"""AcFun 解析器"""

import re
from typing import ClassVar

from httpx import AsyncClient
from astrbot.api import logger

from ..constants import COMMON_TIMEOUT, PlatformEnum
from ..exceptions import IgnoreException, ParseException
from ..models import Platform
from ..models.platforms.acfun import video_info_decoder
from .base import BaseParser, handle
from .registry import AdapterSpec, register_adapter


class AcfunParser(BaseParser):
    platform: ClassVar[Platform] = Platform(name=PlatformEnum.ACFUN, display_name="猴山")

    def __init__(self, downloader):
        super().__init__(downloader)
        self.headers["referer"] = "https://www.acfun.cn/"

    @handle("acfun.cn", r"(?:ac=|/ac)(?P<acid>\d+)")
    async def _parse(self, searched: re.Match[str]):
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
        video_info = video_info_decoder.decode(raw_json)

        from ..config import get_config
        pconfig = get_config()

        author = self.create_author(video_info.name, video_info.avatar_url)
        if (duration := video_info.duration) >= pconfig.VIDEO_DURATION_MAXIMUM:
            from ..utils.formatting import fmt_duration

            # 这条消息会作为「ℹ️ …」发给用户，也会出现在链接调试页的报告里，要说清楚原因
            message = (
                f"视频时长({fmt_duration(duration)})超过限制"
                f"({fmt_duration(pconfig.VIDEO_DURATION_MAXIMUM)})，跳过解析"
            )
            logger.warning(message)
            raise IgnoreException(message)

        video_task = self.downloader.download_m3u8(
            video_info.m3u8_url, video_name=f"acfun_{acid}.mp4",
        )
        video_content = self.create_video(video_task, cover_url=video_info.coverUrl)
        return self.result(title=video_info.title, text=video_info.text, author=author,
                          timestamp=video_info.timestamp, contents=[video_content])


ADAPTER = register_adapter(
    AdapterSpec(
        name=PlatformEnum.ACFUN.value,
        url_pattern=re.compile(r"acfun\.cn"),
        parser_cls=AcfunParser,
        description="视频",
        priority=80,
    )
)
