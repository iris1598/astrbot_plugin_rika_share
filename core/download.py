"""下载系统 - 提供媒体文件下载功能"""

import asyncio
from pathlib import Path
from functools import partial
from contextlib import contextmanager
from urllib.parse import urljoin

import httpx
import aiofiles
from astrbot.api import logger

from .utils import merge_av, safe_unlink, generate_file_name, is_module_available
from .constants import COMMON_HEADER, DOWNLOAD_TIMEOUT
from .exception import IgnoreException, DownloadException


class StreamDownloader:
    def __init__(self, cache_dir: Path):
        self.headers: dict[str, str] = COMMON_HEADER.copy()
        self.cache_dir: Path = cache_dir
        self.client: httpx.AsyncClient = httpx.AsyncClient(
            timeout=DOWNLOAD_TIMEOUT, verify=False
        )

    async def aclose(self):
        await self.client.aclose()

    @staticmethod
    def _validate_content_length(response: httpx.Response) -> int | None:
        """校验明确声明的响应大小。

        抖音 CDN 经常使用 ``Transfer-Encoding: chunked``，此时不会返回
        ``Content-Length``。缺少该响应头并不代表响应为空，实际大小需要
        在流式下载过程中统计。
        """
        content_length = response.headers.get("Content-Length")
        if not content_length:
            return None

        content_length = int(content_length)
        if content_length == 0:
            logger.warning(f"媒体 url: {response.url}, 大小为 0, 取消下载")
            raise IgnoreException
        return content_length

    @staticmethod
    async def _validate_downloaded_bytes(file_path: Path, url: str, received_bytes: int):
        """防止把空响应当成成功下载，并清理已创建的空文件。"""
        if received_bytes > 0:
            return
        await safe_unlink(file_path)
        logger.warning(f"媒体 url: {url}, 大小为 0, 取消下载")
        raise IgnoreException

    async def _download_file_with_httpx(
        self,
        url: str,
        *,
        file_path: Path,
        headers: dict[str, str],
        chunk_size: int = 64 * 1024,
    ) -> Path:
        async with self.client.stream("GET", url, headers=headers, follow_redirects=True) as response:
            response.raise_for_status()
            self._validate_content_length(response)
            received_bytes = 0
            try:
                async with aiofiles.open(file_path, "wb") as file:
                    async for chunk in response.aiter_bytes(chunk_size):
                        if chunk:
                            await file.write(chunk)
                            received_bytes += len(chunk)
            except Exception:
                await safe_unlink(file_path)
                raise
            await self._validate_downloaded_bytes(file_path, str(response.url), received_bytes)
        return file_path

    async def _download_file_with_curl_cffi(
        self,
        url: str,
        *,
        file_path: Path,
        headers: dict[str, str],
    ) -> Path:
        try:
            import curl_cffi
        except ImportError:
            raise DownloadException("curl_cffi 未安装")

        async with curl_cffi.AsyncSession(allow_redirects=True) as session:
            response: curl_cffi.Response = await session.get(
                url, headers=headers, timeout=DOWNLOAD_TIMEOUT, stream=True,
            )
            response.raise_for_status()
            self._validate_content_length(response)
            received_bytes = 0
            try:
                async with aiofiles.open(file_path, "wb") as file:
                    async for chunk in response.aiter_content(chunk_size=8192):
                        if chunk:
                            await file.write(chunk)
                            received_bytes += len(chunk)
            except Exception:
                await safe_unlink(file_path)
                raise
            await self._validate_downloaded_bytes(file_path, str(response.url), received_bytes)
        return file_path

    async def _download_file(
        self,
        url: str,
        *,
        file_name: str | None = None,
        ext_headers: dict[str, str] | None = None,
        chunk_size: int = 64 * 1024,
    ) -> Path:
        if not file_name:
            file_name = generate_file_name(url)
        file_path = self.cache_dir / file_name
        if file_path.exists():
            return file_path

        headers = {**self.headers, **(ext_headers or {})}

        try:
            return await self._download_file_with_httpx(
                url, file_path=file_path, headers=headers, chunk_size=chunk_size
            )
        except httpx.HTTPError:
            from .config import get_config
            if get_config().DEBUG_LOG_ENABLED:
                logger.warning(f"下载失败(httpx) | url: {url}", exc_info=True)
            try:
                return await self._download_file_with_curl_cffi(url, file_path=file_path, headers=headers)
            except Exception:
                if get_config().DEBUG_LOG_ENABLED:
                    logger.warning(f"下载失败(curl_cffi) | url: {url}", exc_info=True)
                raise DownloadException("媒体下载失败")

    async def download_video(
        self,
        url: str,
        *,
        video_name: str | None = None,
        ext_headers: dict[str, str] | None = None,
    ) -> Path:
        if video_name is None:
            video_name = generate_file_name(url, ".mp4")
        return await self._download_file(
            url, file_name=video_name, ext_headers=ext_headers, chunk_size=1024 * 1024,
        )

    async def download_m3u8(
        self,
        m3u8_url: str,
        *,
        video_name: str | None = None,
        ext_headers: dict[str, str] | None = None,
    ) -> Path:
        """下载 m3u8 视频 - 解析分片列表并合并下载"""
        if video_name is None:
            video_name = generate_file_name(m3u8_url, ".mp4")

        video_path = self.cache_dir / video_name
        if video_path.exists():
            return video_path

        headers = {**self.headers, **(ext_headers or {})}

        try:
            # 1. 获取并解析 m3u8 分片列表
            response = await self.client.get(m3u8_url, headers=headers)
            response.raise_for_status()
            slices_text = response.text

            slices: list[str] = []
            for line in slices_text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                slices.append(urljoin(m3u8_url, line))

            if not slices:
                raise DownloadException("m3u8 分片列表为空")

            # 2. 逐个下载分片并追加到文件
            async with aiofiles.open(video_path, "wb") as f:
                for seg_url in slices:
                    async with self.client.stream("GET", seg_url, headers=headers) as response:
                        response.raise_for_status()
                        async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                            await f.write(chunk)

        except httpx.HTTPError:
            await safe_unlink(video_path)
            from .config import get_config
            if get_config().DEBUG_LOG_ENABLED:
                logger.exception(f"m3u8 视频下载失败 | url: {m3u8_url}")
            raise DownloadException("m3u8 视频下载失败")

        return video_path

    async def download_audio(
        self,
        url: str,
        *,
        audio_name: str | None = None,
        ext_headers: dict[str, str] | None = None,
    ) -> Path:
        if audio_name is None:
            audio_name = generate_file_name(url, ".mp3")
        return await self._download_file(url, file_name=audio_name, ext_headers=ext_headers)

    async def download_img(
        self,
        url: str,
        *,
        img_name: str | None = None,
        ext_headers: dict[str, str] | None = None,
    ) -> Path:
        if img_name is None:
            img_name = generate_file_name(url, ".jpg")
        return await self._download_file(url, file_name=img_name, ext_headers=ext_headers)

    async def download_av_and_merge(
        self,
        v_url: str,
        a_url: str,
        *,
        output_path: Path,
        ext_headers: dict[str, str] | None = None,
    ) -> Path:
        v_path, a_path = await asyncio.gather(
            self._download_file(v_url, ext_headers=ext_headers),
            self._download_file(a_url, ext_headers=ext_headers),
        )
        await merge_av(v_path=v_path, a_path=a_path, output_path=output_path)
        return output_path
