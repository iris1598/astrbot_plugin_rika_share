"""微博解析器"""
import re
from time import time
from uuid import uuid4
from typing import ClassVar
from bs4 import Tag, BeautifulSoup
from httpx import Cookies, AsyncClient
from ..base_parser import BaseParser, PlatformEnum, ParseException, handle
from ..data import Platform, ImageContent


class WeiBoParser(BaseParser):
    platform: ClassVar[Platform] = Platform(name=PlatformEnum.WEIBO, display_name="微博")

    def __init__(self, downloader):
        super().__init__(downloader)
        extra_headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
            "referer": "https://weibo.com/",
        }
        self.headers.update(extra_headers)

    @handle("weibo.com/tv", r"weibo\.com/tv/show/\d{4}:\d+\?mid=(?P<mid>\d+)")
    async def _parse_weibo_tv(self, searched: re.Match[str]):
        mid = str(searched.group("mid"))
        weibo_id = self._mid2id(mid)
        return await self.parse_weibo_id(weibo_id)

    @handle("video.weibo", r"video\.weibo\.com/show\?fid=(?P<fid>\d+:\d+)")
    async def _parse_video_weibo(self, searched: re.Match[str]):
        fid = str(searched.group("fid"))
        return await self.parse_fid(fid)

    @handle("m.weibo.cn", r"weibo\.cn/(?:status|detail|\d+)/(?P<wid>[0-9a-zA-Z]+)")
    @handle("weibo.com", r"weibo\.com/\d+/(?P<wid>[0-9a-zA-Z]+)")
    async def _parse_m_weibo_cn(self, searched: re.Match[str]):
        wid = str(searched.group("wid"))
        return await self.parse_weibo_id(wid)

    @handle("mapp.api.weibo", r"mapp\.api\.weibo\.cn/fx/[0-9A-Za-z]+\.html")
    async def _parse_mapp_api_weibo(self, searched: re.Match[str]):
        url = f"https://{searched.group(0)}"
        return await self.parse_with_redirect(url)

    @handle("weibo.com/ttarticle", r"id=(?P<id>\d+)")
    @handle("weibo.com/article", r"/id/(?P<id>\d+)")
    async def _parse_article(self, searched: re.Match[str]):
        _id = searched.group("id")
        return await self.parse_article(_id)

    async def parse_article(self, _id: str):
        from ..weibo_models.article import decoder as article_decoder

        url = "https://card.weibo.com/article/m/aj/detail"
        params = {"_rid": str(uuid4()), "id": _id, "_t": int(time() * 1000)}
        async with AsyncClient(headers=self.headers, timeout=self.timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()

        detail = article_decoder.decode(response.content)
        if detail.msg != "success":
            raise ParseException("请求失败")
        data = detail.data
        soup = BeautifulSoup(data.content, "html.parser")
        graphics: list[str | ImageContent] = []
        for element in soup.find_all(["p", "img"]):
            if not isinstance(element, Tag):
                continue
            if element.name == "p":
                text = element.get_text(strip=True).replace("\u200b", "")
                if text:
                    graphics.append(text)
            elif element.name == "img":
                src = element.get("src")
                if isinstance(src, str):
                    graphics.append(self.create_image(src))
        author = self.create_author(data.userinfo.screen_name, data.userinfo.profile_image_url)
        return self.result(url=data.url, title=data.title, author=author, timestamp=data.create_at_unix, graphics=graphics)

    async def parse_fid(self, fid: str):
        from ..weibo_models.show import decoder as show_decoder

        req_url = f"https://h5.video.weibo.com/api/component?page=/show/{fid}"
        headers = {"Referer": f"https://h5.video.weibo.com/show/{fid}", "Content-Type": "application/x-www-form-urlencoded", **self.headers}
        post_content = 'data={"Component_Play_Playinfo":{"oid":"' + fid + '"}}'
        async with AsyncClient(headers=headers, timeout=self.timeout) as client:
            response = await client.post(req_url, content=post_content)
            response.raise_for_status()

        data = show_decoder.decode(response.content).data
        play_info = data.Component_Play_Playinfo
        author = self.create_author(play_info.name, play_info.avatar, play_info.description)
        video_content = self.create_video(play_info.video_url, play_info.cover_url, duration=play_info.duration)
        return self.result(author=author, title=play_info.title, text=play_info.text, contents=[video_content], timestamp=play_info.real_date)

    async def parse_weibo_id(self, weibo_id: str):
        from ..weibo_models.common import decoder as weibo_decoder

        headers = {
            "accept": "application/json, text/plain, */*",
            "referer": f"https://m.weibo.cn/detail/{weibo_id}",
            "origin": "https://m.weibo.cn",
            "x-requested-with": "XMLHttpRequest",
            "mweibo-pwa": "1",
            **self.headers,
        }
        ts = int(time() * 1000)
        url = f"https://m.weibo.cn/statuses/show?id={weibo_id}&_={ts}"
        async with AsyncClient(headers=headers, timeout=self.timeout, follow_redirects=False, cookies=Cookies(), trust_env=False) as client:
            response = await client.get(url)
            if response.status_code != 200:
                if response.status_code in (403, 418):
                    raise ParseException(f"被风控拦截({response.status_code}), 可尝试更换 UA/Referer 或稍后重试")
                raise ParseException(f"获取数据失败 {response.status_code}")
            ctype = response.headers.get("content-type", "")
            if "application/json" not in ctype:
                raise ParseException(f"获取数据失败 content-type is not application/json (got: {ctype})")

        weibo_data = weibo_decoder.decode(response.content).data
        return self._collect_result(weibo_data)

    def _collect_result(self, data):
        author = self.create_author(data.display_name, data.user.profile_image_url)
        result = self.result(title=data.title, text=data.text_content, author=author, timestamp=data.timestamp, url=data.url)
        if video_url := data.video_url:
            result.video = self.create_video(video_url, data.cover_url, data.duration)
        if image_urls := data.image_urls:
            result.contents.extend(self.create_images(image_urls))
        if data.retweeted_status:
            result.repost = self._collect_result(data.retweeted_status)
        return result

    def _base62_encode(self, number: int) -> str:
        alphabet = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        if number == 0:
            return "0"
        result = ""
        while number > 0:
            result = alphabet[number % 62] + result
            number //= 62
        return result

    def _mid2id(self, mid: str) -> str:
        from math import ceil
        mid = str(mid)[::-1]
        size = ceil(len(mid) / 7)
        result = []
        for i in range(size):
            s = mid[i * 7:(i + 1) * 7][::-1]
            s = self._base62_encode(int(s))
            if i < size - 1 and len(s) < 4:
                s = "0" * (4 - len(s)) + s
            result.append(s)
        result.reverse()
        return "".join(result)
