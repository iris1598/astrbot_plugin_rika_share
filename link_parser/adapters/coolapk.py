"""酷安解析器

优先走酷安 App 的 ``/v6/feed/detail`` 接口（签名算法来自开源社区，字段稳定、
覆盖全部动态类型）；接口不可用时回退到桌面版网页 SSR 解析——网页端只对部分
动态类型渲染完整内容，其余只会返回「动态分享」二维码落地页。
"""

import base64
import hashlib
import re
import time
import uuid
from datetime import datetime
from typing import ClassVar

from bs4 import BeautifulSoup
from httpx import AsyncClient

from ..exceptions import ParseException
from ..models import ParseResult, Platform
from ..models.platforms.coolapk import feed_decoder
from .base import BaseParser, handle
from .registry import AdapterSpec, register_adapter

# 桌面端 SSR 页面结构（2026-11 实测）：
#   #feed-detail .userinfo-item  作者（头像 / 昵称 / 相对时间+机型）
#   #feed-detail .feed-message   正文（<br> 换行，表情为 img.feed-emoji）
#   #feed-detail .message-image-group img.message-image  图集（协议相对 URL）
#   #feed-detail .feed-status    统计（feed-like / feed-reply / feed-favorite）

_RELATIVE_TIME_RE = re.compile(
    r"(?:(\d+)\s*(秒|分钟|小时|天|月|年)前)|(刚刚)|(昨天)|(前天)"
)
_UNIT_SECONDS = {"秒": 1, "分钟": 60, "小时": 3600, "天": 86400, "月": 86400 * 30, "年": 86400 * 365}

# 桌面版网页对移动 UA 会渲染不同的页面结构，这里固定用实测可用的桌面 Chrome UA
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# ---------------- App 接口签名（来自开源社区逆向，见 RSSHub lib/routes/coolapk） ----------------

_TOKEN_SALT = "token://com.coolapk.market/c67ef5943784d09750dcfbb31020f0ab"
_APP_UA = (
    "Dalvik/2.1.0 (Linux; U; Android 10; Redmi K30 5G MIUI/V12.0.3.0.QGICMXM) "
    "(#Build; Redmi; Redmi K30 5G; QKQ1.191222.002 test-keys; 10) "
    "+CoolMarket/11.0-2101202"
)


def _get_app_token() -> str:
    """生成 X-App-Token：md5(base64(盐?md5(时间)$随机设备ID&包名)) + 设备ID + 0x时间戳。"""
    device_id = str(uuid.uuid4())
    now = str(int(time.time()))
    hex_now = "0x" + format(int(now), "x")
    md5_now = hashlib.md5(now.encode()).hexdigest()
    s = f"{_TOKEN_SALT}?{md5_now}${device_id}&com.coolapk.market"
    md5_s = hashlib.md5(base64.b64encode(s.encode())).hexdigest()
    return md5_s + device_id + hex_now


def _api_headers() -> dict[str, str]:
    return {
        "X-Requested-With": "XMLHttpRequest",
        "X-App-Id": "com.coolapk.market",
        "X-App-Token": _get_app_token(),
        "X-Sdk-Int": "29",
        "X-Sdk-Locale": "zh-CN",
        "X-App-Version": "11.0",
        "X-Api-Version": "11",
        "X-App-Code": "2101202",
        "User-Agent": _APP_UA,
    }


def _parse_relative_time(text: str) -> int | None:
    """把「1天前 moto g100」这类相对时间粗略换算成秒级时间戳，认不出返回 None。"""
    matched = _RELATIVE_TIME_RE.search(text.strip())
    if not matched:
        if dated := re.match(r"(\d{4})-(\d{2})-(\d{2})", text.strip()):
            try:
                dt = datetime(
                    int(dated.group(1)), int(dated.group(2)), int(dated.group(3))
                )
                return int(dt.timestamp())
            except ValueError:
                pass
        return None
    n, unit, just_now, yesterday, before_yesterday = matched.groups()
    if just_now:
        return int(time.time())
    delta = _UNIT_SECONDS.get(unit, 0) if (n and unit) else 0
    delta = int(n) * delta if delta else 0
    if yesterday:
        delta = 86400
    elif before_yesterday:
        delta = 86400 * 2
    return int(time.time() - delta)


def _absolute_url(src: str) -> str:
    """补全协议相对 URL（//image.coolapk.com/...）。"""
    if src.startswith("//"):
        return f"https:{src}"
    return src


def _html_message_to_text(html: str) -> str | None:
    """API 正文是 HTML 片段：话题 <a> 转纯文字、<br>/<br/> 转换行、其余标签剥离。"""
    soup = BeautifulSoup(html, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for emoji in soup.find_all("img", class_="feed-emoji"):
        emoji.replace_with(f"[{emoji.get('alt', '')}]")
    text = soup.get_text().strip()
    return text or None


class CoolapkParser(BaseParser):
    platform: ClassVar[Platform] = Platform(name="coolapk", display_name="酷安")

    def __init__(self, downloader):
        super().__init__(downloader)
        # 图片 CDN 校验 Referer（网页回退路径也用它）
        self.headers["User-Agent"] = DESKTOP_UA
        self.headers["referer"] = "https://www.coolapk.com/"

    @handle("coolapk.com", r"coolapk\.com/feed/(?P<feed_id>\d+)")
    async def _parse(self, searched: re.Match[str]) -> ParseResult:
        feed_id = searched.group("feed_id")
        url = f"https://www.coolapk.com/feed/{feed_id}"

        try:
            return await self._parse_by_api(feed_id, url)
        except Exception as e:
            from astrbot.api import logger

            logger.warning(f"酷安接口解析失败，回退网页解析: {type(e).__name__}: {e}")
        return await self._parse_by_webpage(url)

    # ---------------- App 接口（首选） ----------------

    async def _parse_by_api(self, feed_id: str, url: str) -> ParseResult:
        api_url = f"https://api2.coolapk.com/v6/feed/detail?id={feed_id}"
        async with AsyncClient(headers=_api_headers(), timeout=self.timeout, verify=False) as client:
            response = await client.get(api_url)
            if response.status_code in (403, 429):
                raise ParseException("酷安接口请求受限")
            response.raise_for_status()
        payload = feed_decoder.decode(response.content)
        if payload.data is None or payload.data.entityType != "feed":
            raise ParseException("酷安接口未返回动态内容")
        return self._collect_api_result(payload.data, url)

    def _collect_api_result(self, feed, url: str) -> ParseResult:
        # 图片 CDN 与头像：image 域名走 https，avatar 域名保持 API 返回的地址
        image_urls = [
            u.replace("http://image.coolapk.com", "https://image.coolapk.com")
            for u in feed.picArr
            if u
        ]
        author = self.create_author(feed.username, feed.userAvatar)

        stats_map = {
            "👍": feed.likenum,
            "💬": feed.replynum,
            "⭐": feed.favnum,
            "↩️": feed.forwardnum,
        }
        stats_line = " ".join(f"{k} {v}" for k, v in stats_map.items() if v > 0)

        contents = self.create_images(image_urls)
        return self.result(
            text=_html_message_to_text(feed.message or ""),
            timestamp=feed.dateline,
            url=url,
            contents=contents,
            author=author,
            extra={
                "content_type": "图文" if contents else "动态",
                "stats_line": stats_line,
            },
        )

    # ---------------- 桌面版网页（回退） ----------------

    async def _parse_by_webpage(self, url: str) -> ParseResult:
        async with AsyncClient(headers=self.headers, timeout=self.timeout, verify=False) as client:
            response = await client.get(url)
            if response.status_code == 404:
                raise ParseException("酷安动态不存在或已被删除")
            response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        detail = soup.select_one("#feed-detail") or soup
        return self._collect_webpage_result(detail, url)

    def _collect_webpage_result(self, detail, url: str):
        # 作者：头像 + 昵称 + 相对时间（第二个 <p>）
        author = None
        timestamp: int | None = None
        userinfo = detail.select_one(".userinfo-item")
        if userinfo:
            avatar = userinfo.select_one(".avatar-item img")
            name_tag = userinfo.select_one(".username-item p")
            meta_tag = name_tag.find_next_sibling("p") if name_tag else None
            if name_tag:
                timestamp = _parse_relative_time(meta_tag.get_text()) if meta_tag else None
                avatar_url = _absolute_url(avatar["src"]) if avatar and avatar.get("src") else None
                author = self.create_author(name_tag.get_text(strip=True), avatar_url)

        # 正文：<br> 转换行，表情图转 [alt]，话题链接保留文字
        text: str | None = None
        if message := detail.select_one(".feed-message"):
            for p in message.find_all("p"):
                for br in p.find_all("br"):
                    br.replace_with("\n")
                for emoji in p.find_all("img", class_="feed-emoji"):
                    emoji.replace_with(f"[{emoji.get('alt', '')}]")
            text = message.get_text().strip() or None

        # 图集
        image_urls = []
        for img in detail.select(".message-image-group img.message-image"):
            if src := img.get("src"):
                image_urls.append(_absolute_url(src))

        if not text and not image_urls:
            raise ParseException("酷安动态仅能在 App 内查看，网页端未提供内容")

        # 统计：点赞 / 评论 / 收藏
        stats_map = {}
        for key, cls in (("👍", "feed-like"), ("💬", "feed-reply"), ("⭐", "feed-favorite")):
            if tag := detail.select_one(f".feed-status .{cls} a"):
                try:
                    stats_map[key] = int(tag.get_text(strip=True))
                except ValueError:
                    pass
        stats_line = " ".join(f"{k} {v}" for k, v in stats_map.items())

        contents = self.create_images(image_urls)
        return self.result(
            text=text,
            timestamp=timestamp,
            url=url,
            contents=contents,
            author=author,
            extra={
                "content_type": "图文" if contents else "动态",
                "stats_line": stats_line,
            },
        )


ADAPTER = register_adapter(
    AdapterSpec(
        name="coolapk",
        url_pattern=re.compile(r"coolapk\.com"),
        parser_cls=CoolapkParser,
        description="动态 / 图文",
        priority=100,
    )
)
