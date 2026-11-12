"""小红书解析器"""

import re
from pathlib import Path
from typing import ClassVar

from httpx import AsyncClient, Cookies
from astrbot.api import logger

from ..constants import PlatformEnum
from ..exceptions import ParseException
from ..models import ImageContent, ParseResult, PathTask, Platform
from ..models.platforms.xiaohongshu import (
    DiscoveryImage,
    NoteData,
    NoteDetail,
    discovery_decoder,
    explore_decoder,
    setup_decoder,
)
from .base import BaseParser, handle
from .registry import AdapterSpec, register_adapter

#: 桌面 UA 会被重定向到登录页；移动端匿名访问才能拿到笔记页服务端渲染数据。
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
)

#: 重定向到这些路径说明链接不可用（失效 / 删除 / 风控 / 需要登录）
BLOCKED_PATH_MARKERS = ("/404", "/login", "/website-login", "/captcha")

#: 笔记页请求头：按普通浏览器导航请求，不要带 XHR 的 sec-fetch / x-requested-with
NOTE_PAGE_HEADERS = {
    "User-Agent": MOBILE_UA,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
        "image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.xiaohongshu.com/",
}

INITIAL_STATE_PATTERN = re.compile(r"window\.__INITIAL_STATE__=(.*?)</script>", re.S)
SETUP_STATE_PATTERN = re.compile(r"window\.__SETUP_SERVER_STATE__=(.*?)</script>", re.S)


class XiaoHongShuParser(BaseParser):
    platform: ClassVar[Platform] = Platform(name=PlatformEnum.XIAOHONGSHU, display_name="小红书")

    #: xhslink 短链：需先跟随跳转才能拿到笔记 ID（note_id）
    SHORT_LINK_KEYWORDS = ("xhslink.com", "xhslink.cn")

    def __init__(self, downloader, xhs_ck: str | None = None):
        super().__init__(downloader)
        self.headers.update({
            "User-Agent": MOBILE_UA,
            "Referer": "https://www.xiaohongshu.com/",
        })
        self.page_headers = NOTE_PAGE_HEADERS.copy()

        if xhs_ck:
            self.headers["cookie"] = xhs_ck
            self.page_headers["cookie"] = xhs_ck

    def short_link_headers(self) -> dict[str, str]:
        """短链跳转沿用移动端页面请求头，避免被重定向到登录 / 验证码页。"""
        return self.page_headers

    @handle("xhslink.com", r"xhslink\.com/[A-Za-z0-9._?%&+=/#@-]+")
    async def _parse_short_link(self, searched: re.Match[str]):
        url = f"https://{searched.group(0)}"
        return await self.parse_with_redirect(url, self.page_headers)

    @handle("xhslink.cn", r"xhslink\.cn/[A-Za-z0-9._?%&+=/#@-]+")
    async def _parse_short_link_cn(self, searched: re.Match[str]):
        url = f"https://{searched.group(0)}"
        return await self.parse_with_redirect(url, self.page_headers)

    @handle("xiaohongshu.com", r"(explore|discovery/item)/(?P<query>(?P<xhs_id>[0-9a-zA-Z]+)\?[A-Za-z0-9._%&+=/#@-]+)")
    async def _parse_common(self, searched: re.Match[str]):
        path, query, xhs_id = searched.group(1), searched.group("query"), searched.group("xhs_id")
        # 查询参数里的 xsec_token / xsec_source 是分享凭证，必须原样保留
        url = f"https://www.xiaohongshu.com/{path}/{query}"
        return await self.parse_note(url, xhs_id)

    async def parse_note(self, url: str, xhs_id: str) -> ParseResult:
        html, final_url = await self._fetch_note_page(url)
        self._raise_if_blocked(final_url)

        result = self._parse_setup_state(html, xhs_id)
        if result is None:
            result = self._parse_initial_state(html, xhs_id)
        if result is None:
            raise ParseException(
                "小红书分享链接失效或内容已删除，请在 App 中重新分享后再试"
            )
        return result

    async def _fetch_note_page(self, url: str) -> tuple[str, str]:
        async with AsyncClient(
            headers=self.page_headers,
            timeout=self.timeout,
            follow_redirects=True,
            cookies=Cookies(),
            trust_env=False,
        ) as client:
            response = await client.get(url)
            if response.status_code >= 400:
                raise ParseException(f"小红书页面请求失败: HTTP {response.status_code}")
            return response.text, str(response.url)

    @staticmethod
    def _raise_if_blocked(final_url: str) -> None:
        if any(marker in final_url for marker in BLOCKED_PATH_MARKERS):
            raise ParseException(
                "小红书拒绝了本次访问（链接可能已过期、内容已删除或触发风控），"
                "请在 App 中重新分享后再试"
            )

    def _parse_setup_state(self, html: str, xhs_id: str) -> ParseResult | None:
        raw = self._extract_state(html, SETUP_STATE_PATTERN)
        if raw is None:
            return None
        try:
            state = setup_decoder.decode(raw)
        except Exception:
            logger.debug("小红书 __SETUP_SERVER_STATE__ 解析失败", exc_info=True)
            return None
        page = state.LAUNCHER_SSR_STORE_PAGE_DATA
        if page is None:
            return None
        note = page.noteData
        if note.noteId and xhs_id and note.noteId != xhs_id:
            logger.debug(f"小红书 SSR 笔记 ID 不匹配: {note.noteId} != {xhs_id}")
            return None
        return self._build_result_from_note_data(note)

    def _parse_initial_state(self, html: str, xhs_id: str) -> ParseResult | None:
        raw = self._extract_state(html, INITIAL_STATE_PATTERN)
        if raw is None:
            return None

        try:
            explore_state = explore_decoder.decode(raw)
            wrapper = explore_state.note.noteDetailMap.get(xhs_id)
            if wrapper is not None:
                return self._build_result_from_note_detail(wrapper.note)
        except Exception:
            logger.debug("小红书 explore 页面结构解析失败", exc_info=True)

        try:
            discovery_state = discovery_decoder.decode(raw)
            note = discovery_state.noteData.data.noteData
            if not note.noteId or not xhs_id or note.noteId == xhs_id:
                return self._build_result_from_note_data(note)
        except Exception:
            logger.debug("小红书 discovery 页面结构解析失败", exc_info=True)

        return None

    @staticmethod
    def _extract_state(html: str, pattern: re.Pattern[str]) -> str | None:
        matched = pattern.search(html)
        if not matched:
            return None
        return matched.group(1).replace("undefined", "null")

    def _build_result_from_note_data(self, note: NoteData) -> ParseResult:
        author = self.create_author(note.user.nickName, note.user.avatar)
        result = self.result(
            author=author,
            title=note.title,
            text=note.desc,
            timestamp=note.time // 1000 if note.time else None,
            extra={"is_video": note.is_video},
        )
        if note.is_video:
            assert note.video is not None
            video_url, duration = note.video.url_and_duration
            if video_url:
                cover_url = note.image_urls[0] if note.image_urls else None
                self._add_limit_warning(result, duration)
                result.video = self.create_video(video_url, cover_url, duration)
                return result
        if note.imageList:
            result.contents.extend(self._create_images(note.imageList))
        return result

    def _build_result_from_note_detail(self, note: NoteDetail) -> ParseResult:
        author = self.create_author(note.nickname, note.avatar_url)
        result = self.result(
            author=author,
            title=note.title,
            text=note.desc,
            extra={"is_video": note.is_video},
        )
        if note.is_video:
            video_url, cover_url, duration = note.video_cover_duration
            self._add_limit_warning(result, duration)
            result.video = self.create_video(video_url, cover_url, duration)
        elif image_urls := note.image_urls:
            result.contents.extend(self.create_images(image_urls))
        return result

    def _create_images(self, images: list[DiscoveryImage]) -> list[ImageContent]:
        contents: list[ImageContent] = []
        for image in images:
            urls = image.candidate_urls
            if not urls:
                continue
            contents.append(ImageContent(PathTask(self._download_image(urls))))
        return contents

    async def _download_image(self, urls: list[str]) -> Path:
        last_error: Exception | None = None
        for url in urls:
            try:
                return await self.downloader.download_img(url, ext_headers=self.headers)
            except Exception as exc:
                last_error = exc
                logger.debug(f"小红书图片下载失败，尝试下一候选地址: {url[:120]}")
        if last_error is not None:
            raise last_error
        raise ParseException("小红书图片地址为空")


ADAPTER = register_adapter(
    AdapterSpec(
        name=PlatformEnum.XIAOHONGSHU.value,
        url_pattern=re.compile(r"(xhslink\.com|xhslink\.cn|xiaohongshu\.com)"),
        parser_cls=XiaoHongShuParser,
        description="图文笔记 / 视频笔记",
        priority=50,
        build=lambda ctx: XiaoHongShuParser(ctx.downloader, xhs_ck=ctx.config.XHS_CK),
    )
)
