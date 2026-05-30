"""NGA 解析器"""
import re
import json
import time
import random
import asyncio
from typing import ClassVar
from bs4 import Tag, BeautifulSoup
from httpx import HTTPError, AsyncClient
from astrbot.api import logger
from ..base_parser import BaseParser, PlatformEnum, ParseException, handle
from ..data import Platform


class NGAParser(BaseParser):
    platform: ClassVar[Platform] = Platform(name=PlatformEnum.NGA, display_name="NGA")

    def __init__(self, downloader):
        super().__init__(downloader)
        extra_headers = {
            "Referer": "https://nga.178.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        self.headers.update(extra_headers)

    @staticmethod
    def build_url_by_tid(tid: str | int) -> str:
        return f"https://nga.178.com/read.php?tid={tid}"

    @staticmethod
    def build_img_url(path: str) -> str:
        return "https://img.nga.178.com/attachments" + path

    @handle("nga", r"tid=(?P<tid>\d+)")
    async def _parse(self, searched: re.Match[str]):
        tid = int(searched.group("tid"))
        url = self.build_url_by_tid(tid)
        async with AsyncClient(headers=self.headers, timeout=self.timeout, follow_redirects=True) as client:
            try:
                resp = await client.get(url)
                if resp.status_code == 403 and "guestJs" in resp.text:
                    logger.debug("第一次请求 403 错误, 包含 guestJs cookie, 重试请求")
                    if matched := re.search(r"document\.cookie\s*=\s*['\"]guestJs=([^;'\"]+)", resp.text):
                        guest_js = matched.group(1)
                        client.cookies.set("guestJs", guest_js, domain=".178.com")
                        await asyncio.sleep(0.3)
                        rand_param = random.randint(0, 999)
                        separator = "&" if "?" in url else "?"
                        retry_url = f"{url}{separator}rand={rand_param}"
                        resp = await client.get(retry_url)
            except HTTPError as e:
                raise ParseException(f"请求失败: {e}")

        if resp.status_code != 200:
            raise ParseException(f"无法获取页面, HTTP {resp.status_code}")

        html = resp.text
        if "需要" in html and ("登录" in html or "请登录" in html):
            raise ParseException("页面可能需要登录后访问")

        soup = BeautifulSoup(html, "html.parser")
        result = self.result(url=url)

        title_tag = soup.find(id="postsubject0")
        if title_tag and isinstance(title_tag, Tag):
            result.title = title_tag.get_text(strip=True)

        author_tag = soup.find(id="postauthor0")
        if author_tag and isinstance(author_tag, Tag):
            href = author_tag.get("href", "")
            if matched := re.search(r"[?&]uid=(\d+)", str(href)):
                uid = str(matched.group(1))
                script_pattern = r"commonui\.userInfo\.setAll\s*\(\s*(\{.*?\})\s*\)"
                if matched := re.search(script_pattern, html, re.DOTALL):
                    user_info = matched.group(1)
                    try:
                        user_info = json.loads(user_info)
                        if uid in user_info:
                            author = user_info[uid].get("username")
                            result.author = self.create_author(author)
                    except (json.JSONDecodeError, KeyError):
                        pass

        time_tag = soup.find(id="postdate0")
        if time_tag and isinstance(time_tag, Tag):
            timestr = time_tag.get_text(strip=True)
            result.timestamp = int(time.mktime(time.strptime(timestr, "%Y-%m-%d %H:%M")))

        content_tag = soup.find(id="postcontent0")
        if content_tag and isinstance(content_tag, Tag):
            text = content_tag.get_text("\n", strip=True)
            for line in text.split("\n"):
                if "[" in line:
                    if paths := re.findall(r"\[img\]\.(.*?)\[\/img\]", line):
                        for path in paths:
                            img_url = self.build_img_url(path)
                            result.graphics.append(self.create_image(img_url))
                    else:
                        if clean_line := re.sub(r"\[[^\]]*?\]", "", line).strip():
                            result.graphics.append(clean_line)
                else:
                    result.graphics.append(line)
        return result
