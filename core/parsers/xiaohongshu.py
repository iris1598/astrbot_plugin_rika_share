"""小红书解析器"""
import re
from typing import ClassVar
from httpx import Cookies, AsyncClient
from astrbot.api import logger
from ..base_parser import BaseParser, PlatformEnum, ParseException, handle
from ..data import Platform


class XiaoHongShuParser(BaseParser):
    platform: ClassVar[Platform] = Platform(name=PlatformEnum.XIAOHONGSHU, display_name="小红书")

    def __init__(self, downloader, xhs_ck: str | None = None):
        super().__init__(downloader)
        explore_headers = {
            "accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
                "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
            )
        }
        self.headers.update(explore_headers)

        discovery_headers = {
            "origin": "https://www.xiaohongshu.com",
            "x-requested-with": "XMLHttpRequest",
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
        }
        self.ios_headers.update(discovery_headers)

        if xhs_ck:
            self.headers["cookie"] = xhs_ck
            self.ios_headers["cookie"] = xhs_ck

    @handle("xhslink.com", r"xhslink\.com/[A-Za-z0-9._?%&+=/#@-]+")
    async def _parse_short_link(self, searched: re.Match[str]):
        url = f"https://{searched.group(0)}"
        return await self.parse_with_redirect(url, self.ios_headers)

    @handle("xhslink.cn", r"xhslink\.cn/[A-Za-z0-9._?%&+=/#@-]+")
    async def _parse_short_link_cn(self, searched: re.Match[str]):
        url = f"https://{searched.group(0)}"
        return await self.parse_with_redirect(url, self.ios_headers)

    @handle("xiaohongshu.com", r"(explore|discovery/item)/(?P<query>(?P<xhs_id>[0-9a-zA-Z]+)\?[A-Za-z0-9._%&+=/#@-]+)")
    async def _parse_common(self, searched: re.Match[str]):
        xhs_domain = "https://www.xiaohongshu.com"
        query, xhs_id = searched.group("query", "xhs_id")

        try:
            return await self.parse_explore(f"{xhs_domain}/explore/{query}", xhs_id)
        except Exception as e:
            logger.warning(f"parse_explore failed, error: {e}, fallback to parse_discovery")
            return await self.parse_discovery(f"{xhs_domain}/discovery/item/{query}")

    async def parse_explore(self, url: str, xhs_id: str):
        from ..xhs_models.explore import decoder as explore_decoder

        async with AsyncClient(headers=self.headers, timeout=self.timeout) as client:
            response = await client.get(url)
            if response.status_code > 400:
                response.raise_for_status()

        html = response.text
        raw = self._extract_initial_state_raw(html)
        init_state = explore_decoder.decode(raw)
        note_detail_wrapper = init_state.note.noteDetailMap.get(xhs_id)
        if not note_detail_wrapper:
            raise ParseException(f"can't find note detail for xhs_id: {xhs_id}")

        note_detail = note_detail_wrapper.note
        author = self.create_author(note_detail.nickname, note_detail.avatar_url)
        result = self.result(
            author=author, title=note_detail.title, text=note_detail.desc,
            extra={"is_video": note_detail.is_video},
        )
        if note_detail.is_video:
            video_url, cover_url, duration = note_detail.video_cover_duration
            self._add_limit_warning(result, duration)
            result.video = self.create_video(video_url, cover_url, duration)
        elif image_urls := note_detail.image_urls:
            result.contents.extend(self.create_images(image_urls))
        return result

    async def parse_discovery(self, url: str):
        from ..xhs_models.discovery import decoder as discovery_decoder

        async with AsyncClient(
            headers=self.ios_headers,
            timeout=self.timeout,
            follow_redirects=True,
            cookies=Cookies(),
            trust_env=False,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text

        raw = self._extract_initial_state_raw(html)
        init_state = discovery_decoder.decode(raw)
        note_data = init_state.noteData.data.noteData
        preload_data = init_state.noteData.normalNotePreloadData

        author = self.create_author(note_data.user.nickName, note_data.user.avatar)
        result = self.result(
            author=author, title=note_data.title, text=note_data.desc,
            timestamp=note_data.time // 1000,
            extra={"is_video": note_data.is_video},
        )
        if note_data.is_video:
            video_url, duration = note_data.url_and_duration
            if preload_data:
                cover_url = preload_data.image_urls[0]
            else:
                cover_url = note_data.image_urls[0]
            self._add_limit_warning(result, duration)
            result.video = self.create_video(video_url, cover_url, duration)
        elif img_urls := note_data.image_urls:
            result.contents.extend(self.create_images(img_urls))
        return result

    def _extract_initial_state_raw(self, html: str) -> str:
        pattern = r"window\.__INITIAL_STATE__=(.*?)</script>"
        matched = re.search(pattern, html)
        if not matched:
            raise ParseException("小红书分享链接失效或内容已删除")
        return matched.group(1).replace("undefined", "null")
