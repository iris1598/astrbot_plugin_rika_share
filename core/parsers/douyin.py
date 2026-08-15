"""抖音解析器"""
import base64
import re
from typing import ClassVar
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

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

    @staticmethod
    def _build_page_candidates(url: str) -> list[str]:
        """生成抖音分享页的备用地址，规避分享参数触发的空 SSR 页面。"""
        candidates = [url]
        parsed = urlsplit(url)
        if parsed.hostname not in {"m.douyin.com", "www.iesdouyin.com"}:
            return candidates

        query = parse_qs(parsed.query)
        normalized_query = urlencode(
            {
                "from_aid": query.get("from_aid", ["1128"])[0],
                "from_ssr": "1",
            }
        )
        normalized = urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, normalized_query, "")
        )
        if normalized not in candidates:
            candidates.append(normalized)

        alternate_host = (
            "m.douyin.com"
            if parsed.hostname == "www.iesdouyin.com"
            else "www.iesdouyin.com"
        )
        alternate = urlunsplit(
            (parsed.scheme, alternate_host, parsed.path, normalized_query, "")
        )
        if alternate not in candidates:
            candidates.append(alternate)
        return candidates

    async def _request_page(
        self,
        url: str,
        *,
        client: AsyncClient | None = None,
        use_curl_cffi: bool = False,
    ) -> str:
        if use_curl_cffi:
            try:
                import curl_cffi
            except ImportError as e:
                raise ParseException("curl_cffi is not installed") from e

            async with curl_cffi.AsyncSession(
                impersonate="chrome131", allow_redirects=False, verify=False
            ) as client:
                response = await client.get(
                    url, headers=self.ios_headers, timeout=30
                )
                if response.status_code != 200:
                    raise ParseException(f"status: {response.status_code}")
                if not response.text:
                    raise ParseException("empty douyin page")
                return response.text

        if client is not None:
            response = await client.get(url)
            if response.status_code != 200:
                raise ParseException(f"status: {response.status_code}")
            if not response.text:
                raise ParseException("empty douyin page")
            return response.text

        async with AsyncClient(
            headers=self.ios_headers,
            timeout=COMMON_TIMEOUT,
            follow_redirects=False,
            verify=False,
        ) as request_client:
            response = await request_client.get(url)
            if response.status_code != 200:
                raise ParseException(f"status: {response.status_code}")
            if not response.text:
                raise ParseException("empty douyin page")
            return response.text

    async def parse_video(self, url: str):
        from ..douyin_models.video import VideoInfoRes, decoder as video_decoder

        pattern = re.compile(pattern=r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", flags=re.DOTALL)
        video_data = None
        last_error = ParseException("can't find _ROUTER_DATA or iteminfo in html")
        video_id_match = re.search(r"/(?:video|note)/(\d+)", url)
        if not video_id_match:
            raise ParseException("can't find video id in url")
        video_id = video_id_match.group(1)

        async with AsyncClient(
            headers=self.ios_headers,
            timeout=COMMON_TIMEOUT,
            follow_redirects=False,
            verify=False,
        ) as page_client:
            for page_url in self._build_page_candidates(url):
                # 保持同一个 httpx 会话，让抖音下发的 ttwid 等 cookie
                # 能够用于后续页面和接口请求；curl_cffi 作为第二种请求栈重试。
                for use_curl_cffi in (False, True):
                    try:
                        text = await self._request_page(
                            page_url,
                            client=page_client,
                            use_curl_cffi=use_curl_cffi,
                        )
                    except ParseException as e:
                        last_error = e
                        continue

                    matched = pattern.search(text)
                    if matched and matched.group(1):
                        try:
                            video_data = video_decoder.decode(
                                matched.group(1).strip()
                            ).video_data
                        except Exception as e:
                            last_error = ParseException(str(e))

                    if video_data is None:
                        try:
                            video_data = await self._parse_video_by_iteminfo(
                                video_id, page_url, text, VideoInfoRes, page_client
                            )
                        except ParseException as e:
                            last_error = e

                    if video_data is not None:
                        break
                if video_data is not None:
                    break

        if video_data is None:
            raise last_error

        author = self.create_author(video_data.author.nickname, video_data.avatar_url)
        result = self.result(title=video_data.desc, author=author, timestamp=video_data.create_time)

        if image_urls := video_data.image_urls:
            result.contents.extend(self.create_images(image_urls))
        elif video_url := video_data.video_url:
            self._add_limit_warning(result, video_data.duration)
            result.video = self.create_video(video_url, video_data.cover_url, video_data.duration)
        return result

    async def _parse_video_by_iteminfo(
        self,
        video_id: str,
        page_url: str,
        text: str,
        video_info_type,
        client: AsyncClient | None = None,
    ):
        """通过新版分享页的 iteminfo 接口获取作品数据。

        抖音近期会返回不带 videoInfoRes 的 SSR 页面，前端随后使用
        douyin_reflow_token 调用该接口。这里复现前端的 AES-128-CBC token
        生成方式，避免依赖浏览器执行 JavaScript。
        """
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.padding import PKCS7
        from msgspec.json import Decoder

        web_id_match = re.search(r'"webId"\s*:\s*"([^"\\]+)"', text)
        if not web_id_match:
            web_id_match = re.search(
                r"\bwebId\s*=\s*['\"]?([^'\"\s>]+)", text, re.IGNORECASE
            )
        token_match = re.search(
            r"id=['\"]?douyin_reflow_token['\"]?[^>]*\bxsstoken=['\"]?([^'\"\s>]+)",
            text,
        ) or re.search(r"\bxsstoken=['\"]?([^'\"\s>]+)", text)
        if not token_match:
            raise ParseException(
                "can't find reflow token in html "
                "(xsstoken=False)"
            )

        web_id = web_id_match.group(1) if web_id_match else ""
        if not re.fullmatch(r"\d{16,}", web_id):
            web_id = await self._request_web_id(page_url, client=client)
        key = web_id[:16].encode("utf-8")
        if len(key) != 16:
            raise ParseException("invalid douyin web id")

        padder = PKCS7(algorithms.AES.block_size).padder()
        padded_token = padder.update(token_match.group(1).encode("utf-8")) + padder.finalize()
        encryptor = Cipher(algorithms.AES(key), modes.CBC(key)).encryptor()
        reflow_id = base64.b64encode(encryptor.update(padded_token) + encryptor.finalize()).decode()

        query = parse_qs(urlsplit(page_url).query)
        user_cip_match = re.search(
            r"id=['\"]?douyin_reflow_webId['\"]?[^>]*\busercip=['\"]?([^'\"\s>]+)",
            text,
            re.IGNORECASE,
        )
        params = {
            "reflow_source": "reflow_page",
            "web_id": web_id,
            "device_id": web_id,
            "aid": query.get("from_aid", ["1128"])[0],
            "from_did": query.get("did", [""])[0],
            "user_cip": query.get(
                "user_cip", [user_cip_match.group(1) if user_cip_match else ""]
            )[0],
            "from_ssr": "1",
            "item_ids": video_id,
            "reflow_id": reflow_id,
            "scene_from": "share_reflow",
            "use_new_select_scope": "0",
        }

        request_headers = {
            **self.ios_headers,
            "Referer": page_url,
            "Accept": "application/json, text/plain, */*",
        }
        last_error: Exception = ParseException("empty iteminfo response")
        for host in ("www.iesdouyin.com", "www.douyin.com"):
            api_url = f"https://{host}/web/api/v2/aweme/iteminfo/"
            for use_curl_cffi in (False, True):
                try:
                    if use_curl_cffi:
                        try:
                            import curl_cffi
                        except ImportError:
                            continue
                        async with curl_cffi.AsyncSession(
                            impersonate="chrome131", verify=False
                        ) as client:
                            response = await client.get(
                                api_url,
                                params=params,
                                headers=request_headers,
                                timeout=30,
                            )
                    elif client is not None:
                        response = await client.get(
                            api_url, params=params, headers=request_headers
                        )
                    else:
                        async with AsyncClient(
                            headers=request_headers,
                            timeout=COMMON_TIMEOUT,
                            verify=False,
                        ) as client:
                            response = await client.get(api_url, params=params)

                    if response.status_code != 200:
                        last_error = ParseException(
                            f"iteminfo status: {response.status_code}"
                        )
                        continue
                    if not response.content:
                        last_error = ParseException("empty iteminfo response")
                        continue

                    video_info = Decoder(video_info_type).decode(response.content)
                    if video_info.item_list:
                        return video_info.video_data
                    last_error = ParseException("empty iteminfo item_list")
                except Exception as e:
                    last_error = e

        raise ParseException(f"can't find data in iteminfo: {last_error}") from last_error

    async def _request_web_id(
        self, page_url: str, *, client: AsyncClient | None = None
    ) -> str:
        """获取 SSR 页面偶发缺失时由抖音前端补取的 webId。"""
        request_headers = {
            **self.ios_headers,
            "Referer": page_url,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
        }
        payload = {
            "app_id": 2018,
            "referer": page_url,
            "url": page_url,
            "user_agent": self.ios_headers.get("User-Agent", ""),
            "user_unique_id": "",
        }
        last_error: Exception = ParseException("empty webid response")
        for use_curl_cffi in (False, True):
            try:
                if use_curl_cffi:
                    try:
                        import curl_cffi
                    except ImportError:
                        continue
                    async with curl_cffi.AsyncSession(
                        impersonate="chrome131", verify=False
                    ) as client:
                        response = await client.post(
                            "https://mcs.zijieapi.com/webid",
                            json=payload,
                            headers=request_headers,
                            timeout=30,
                        )
                elif client is not None:
                    response = await client.post(
                        "https://mcs.zijieapi.com/webid",
                        json=payload,
                        headers=request_headers,
                    )
                else:
                    async with AsyncClient(
                        headers=request_headers,
                        timeout=COMMON_TIMEOUT,
                        verify=False,
                    ) as client:
                        response = await client.post(
                            "https://mcs.zijieapi.com/webid", json=payload
                        )

                if response.status_code != 200:
                    last_error = ParseException(
                        f"webid status: {response.status_code}"
                    )
                    continue
                data = response.json() if response.content else {}
                web_id = str(data.get("web_id", ""))
                if re.fullmatch(r"\d{16,}", web_id):
                    return web_id
                last_error = ParseException("invalid webid response")
            except Exception as e:
                last_error = e
        raise ParseException(f"can't get douyin web id: {last_error}") from last_error

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
