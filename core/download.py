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
    def _validate_content_length(response: httpx.Response) -> int:
        content_length = response.headers.get("Content-Length")
        content_length = int(content_length) if content_length else 0
        if content_length == 0:
            logger.warning(f"媒体 url: {response.url}, 大小为 0, 取消下载")
            raise IgnoreException
        return content_length

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
            async with aiofiles.open(file_path, "wb") as file:
                async for chunk in response.aiter_bytes(chunk_size):
                    await file.write(chunk)
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
            async with aiofiles.open(file_path, "wb") as file:
                async for chunk in response.aiter_content(chunk_size=8192):
                    await file.write(chunk)
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
            logger.opt(exception=True).warning(f"下载失败(httpx) | url: {url}")
            try:
                return await self._download_file_with_curl_cffi(url, file_path=file_path, headers=headers)
            except Exception:
                logger.opt(exception=True).warning(f"下载失败(curl_cffi) | url: {url}")
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
            logger.opt(exception=True).error(f"m3u8 视频下载失败 | url: {m3u8_url}")
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


class YtdlpDownloader:
    """yt-dlp 下载器封装"""

    def __init__(self, cache_dir: Path, proxy: str | None = None):
        self.cache_dir = cache_dir
        self.proxy = proxy

    async def extract_video_info(self, url: str, cookiefile: Path | None = None):
        """提取视频信息"""
        import yt_dlp

        ydl_opts = {
            "quiet": True,
            "skip_download": "1",
            "force_generic_extractor": True,
        }
        if self.proxy:
            ydl_opts["proxy"] = self.proxy
        if cookiefile:
            ydl_opts["cookiefile"] = str(cookiefile)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = await asyncio.to_thread(ydl.extract_info, url, download=False)
            if not info_dict:
                from .exception import ParseException
                raise ParseException("获取视频信息失败")

        from dataclasses import dataclass

        @dataclass
        class VideoInfo:
            title: str
            channel: str
            uploader: str
            duration: int
            timestamp: int
            thumbnail: str
            description: str
            channel_id: str

        return VideoInfo(
            title=info_dict.get("title", ""),
            channel=info_dict.get("channel", info_dict.get("uploader", "")),
            uploader=info_dict.get("uploader_id", ""),
            duration=int(info_dict.get("duration", 0)),
            timestamp=int(info_dict.get("timestamp", 0)),
            thumbnail=info_dict.get("thumbnail", ""),
            description=info_dict.get("description", ""),
            channel_id=info_dict.get("channel_id", info_dict.get("uploader_id", "")),
        )

    async def download_video(self, url: str, cookiefile: Path | None = None) -> Path:
        """下载视频"""
        import yt_dlp

        from .config import get_config
        pconfig = get_config()

        video_info = await self.extract_video_info(url, cookiefile)
        max_duration = getattr(pconfig, 'VIDEO_DURATION_MAXIMUM', 480)
        if video_info.duration > max_duration:
            logger.warning(f"视频时长 {video_info.duration} 秒, 超过 {max_duration} 秒, 取消下载")
            raise IgnoreException

        video_path = self.cache_dir / generate_file_name(url, ".mp4")
        if video_path.exists():
            return video_path

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        ydl_opts = {
            "outtmpl": str(video_path),
            "merge_output_format": "mp4",
            "format": "bv*+ba/b",
            "quiet": True,
        }
        if self.proxy:
            ydl_opts["proxy"] = self.proxy
        if cookiefile:
            ydl_opts["cookiefile"] = str(cookiefile)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            await asyncio.to_thread(ydl.download, [url])

        return video_path

    async def download_audio(self, url: str, cookiefile: Path | None = None) -> Path:
        """下载音频"""
        import yt_dlp

        file_name = generate_file_name(url)
        audio_path = self.cache_dir / f"{file_name}.flac"
        if audio_path.exists():
            return audio_path

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        ydl_opts = {
            "outtmpl": f"{self.cache_dir / file_name}.%(ext)s",
            "format": "bestaudio/best",
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "flac", "preferredquality": "0"}],
            "quiet": True,
        }
        if self.proxy:
            ydl_opts["proxy"] = self.proxy
        if cookiefile:
            ydl_opts["cookiefile"] = str(cookiefile)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            await asyncio.to_thread(ydl.download, [url])

        return audio_path
