"""抖音解析器"""
import base64
import re
from typing import ClassVar
from urllib.parse import parse_qs, urlsplit

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

        # 短链 302 的目标 URL 中包含 did、from_aid 等分享上下文。抖音新版
        # 页面会用这些参数生成 iteminfo 请求所需的 token，不能在这里丢掉。
        source_url = searched.string.strip()
        source_host = urlsplit(source_url).hostname if source_url.startswith(("http://", "https://")) else None
        urls = []
        if source_host in {"m.douyin.com", "www.iesdouyin.com"}:
            urls.append(source_url)
        urls.extend((self._build_m_douyin_url(ty, vid), self._build_iesdouyin_url(ty, vid)))

        seen_urls: set[str] = set()
        for url in urls:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                return await self.parse_video(url)
            except ParseException as e:
                logger.warning(f"failed to parse {url}, error: {e}")
                continue
        raise ParseException("分享已删除或资源直链提取失败, 请稍后再试")

    @staticmethod
    def _build_iesdouyin_url(ty: str, vid: str) -> str:
        return f"https://www.iesdouyin.com/share/{ty}/{vid}?from_aid=1128&from_ssr=1"

    @staticmethod
    def _build_m_douyin_url(ty: str, vid: str) -> str:
        return f"https://m.douyin.com/share/{ty}/{vid}?from_aid=1128&from_ssr=1"

    async def parse_video(self, url: str):
        from ..douyin_models.video import VideoInfoRes, decoder as video_decoder

        async with AsyncClient(headers=self.ios_headers, timeout=COMMON_TIMEOUT, follow_redirects=False, verify=False) as client:
            response = await client.get(url)
            if response.status_code != 200:
                raise ParseException(f"status: {response.status_code}")
            text = response.text

        pattern = re.compile(pattern=r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", flags=re.DOTALL)
        matched = pattern.search(text)
        video_data = None
        router_error: Exception | None = None
        if matched and matched.group(1):
            try:
                video_data = video_decoder.decode(matched.group(1).strip()).video_data
            except Exception as e:
                # 新版页面仍有 _ROUTER_DATA，但 videoInfoRes 可能为空；
                # 此时改用页面下发的 xsstoken 请求 iteminfo。
                router_error = e

        if video_data is None:
            video_id_match = re.search(r"/(?:video|note)/(\d+)", url)
            if not video_id_match:
                raise ParseException("can't find video id in url")
            try:
                video_data = await self._parse_video_by_iteminfo(
                    video_id_match.group(1), url, text, VideoInfoRes
                )
            except ParseException:
                if router_error is not None:
                    raise
                raise ParseException("can't find _ROUTER_DATA or iteminfo in html")

        author = self.create_author(video_data.author.nickname, video_data.avatar_url)
        result = self.result(title=video_data.desc, author=author, timestamp=video_data.create_time)

        if image_urls := video_data.image_urls:
            result.contents.extend(self.create_images(image_urls))
        elif video_url := video_data.video_url:
            self._add_limit_warning(result, video_data.duration)
            result.video = self.create_video(video_url, video_data.cover_url, video_data.duration)
        return result

    async def _parse_video_by_iteminfo(self, video_id: str, page_url: str, text: str, video_info_type):
        """通过新版分享页的 iteminfo 接口获取作品数据。

        抖音近期会返回不带 videoInfoRes 的 SSR 页面，前端随后使用
        douyin_reflow_token 调用该接口。这里复现前端的 AES-128-CBC token
        生成方式，避免依赖浏览器执行 JavaScript。
        """
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.padding import PKCS7
        from msgspec.json import Decoder

        web_id_match = re.search(r'"webId"\s*:\s*"([^"\\]+)"', text)
        token_match = re.search(
            r"id=['\"]?douyin_reflow_token['\"]?[^>]*\bxsstoken=['\"]?([^'\"\s>]+)",
            text,
        )
        if not web_id_match or not token_match:
            raise ParseException("can't find reflow token in html")

        web_id = web_id_match.group(1)
        key = web_id[:16].encode("utf-8")
        if len(key) != 16:
            raise ParseException("invalid douyin web id")

        padder = PKCS7(algorithms.AES.block_size).padder()
        padded_token = padder.update(token_match.group(1).encode("utf-8")) + padder.finalize()
        encryptor = Cipher(algorithms.AES(key), modes.CBC(key)).encryptor()
        reflow_id = base64.b64encode(encryptor.update(padded_token) + encryptor.finalize()).decode()

        query = parse_qs(urlsplit(page_url).query)
        params = {
            "reflow_source": "reflow_page",
            "web_id": web_id,
            "device_id": web_id,
            "aid": query.get("from_aid", ["1128"])[0],
            "from_did": query.get("did", [""])[0],
            "user_cip": query.get("user_cip", [""])[0],
            "from_ssr": "1",
            "item_ids": video_id,
            "reflow_id": reflow_id,
            "scene_from": "share_reflow",
            "use_new_select_scope": "0",
        }

        api_url = "https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/"
        async with AsyncClient(
            headers={**self.ios_headers, "Referer": page_url, "Accept": "application/json, text/plain, */*"},
            timeout=COMMON_TIMEOUT,
            verify=False,
        ) as client:
            response = await client.get(api_url, params=params)
            if response.status_code != 200:
                raise ParseException(f"iteminfo status: {response.status_code}")

        try:
            video_info = Decoder(video_info_type).decode(response.content)
            return video_info.video_data
        except Exception as e:
            raise ParseException(f"can't find data in iteminfo: {e}") from e

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
