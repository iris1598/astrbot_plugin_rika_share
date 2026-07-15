"""Bilibili 解析器 - 支持视频、动态、直播、专栏、收藏夹"""

import re
import json
import asyncio
import time
from typing import ClassVar

from astrbot.api import logger
from bilibili_api import HEADERS, Credential, select_client, request_settings
from bilibili_api.opus import Opus
from bilibili_api.video import Video
from bilibili_api.login_v2 import QrCodeLogin, QrCodeLoginEvents
from msgspec import convert

from ..base_parser import BaseParser, PlatformEnum, ParseException, IgnoreException, DownloadException, handle
from ..data import Platform, ImageContent, MediaContent
from ..cookie import ck2dict
from ..utils_parser import fmt_duration
from ..utils import reset_bili_api_client, reset_bili_api_client_safely

try:
    select_client("curl_cffi")
    request_settings.set("impersonate", "chrome131")
except Exception:
    logger.warning("curl_cffi 未注册/未安装，B站解析器将使用默认 httpx 客户端")
    select_client("httpx")


# 客户端最长复用时长（秒）。超过则在下一次解析前主动重建，
# 避免底层 keep-alive 连接被服务端单方面关闭后请求挂起。
_BILI_CLIENT_MAX_AGE = 1800  # 30 分钟


class BilibiliParser(BaseParser):
    platform: ClassVar[Platform] = Platform(name=PlatformEnum.BILIBILI, display_name="哔哩哔哩")

    def __init__(self, downloader, bili_ck: str | None = None, config_dir=None):
        super().__init__(downloader)
        self.headers = HEADERS.copy()
        self._credential: Credential | None = None
        self._bili_ck = bili_ck
        self._cookies_file = (config_dir / "bilibili_cookies.json") if config_dir else None
        self._client_born_at: float = 0.0  # bilibili-api client 上次重建时间

    async def _ensure_fresh_client(self):
        """若 bilibili-api 的 HTTP client 复用超过阈值，主动重建，防止连接老化。"""
        if time.monotonic() - self._client_born_at < _BILI_CLIENT_MAX_AGE:
            return
        await reset_bili_api_client_safely()
        self._client_born_at = time.monotonic()

    @handle("b23.tv", r"b23\.tv/[0-9a-zA-Z._?%&+-=/#]+")
    @handle("bili2233", r"bili2233\.cn/[0-9a-zA-Z._?%&+-=/#]+")
    async def _parse_short_link(self, searched: re.Match[str]):
        url = f"https://{searched.group(0)}"
        return await self.parse_with_redirect(url)

    @handle("BV", r"^(?P<bvid>BV[0-9a-zA-Z]{10})(?:\s)?(?P<page_num>\d{1,3})?$")
    @handle("/BV", r"bilibili\.com(?:/video)?/(?P<bvid>BV[0-9A-Za-z]{10})(?:.*?[?&]p=(?P<page_num>\d{1,3}))?")
    async def _parse_bv(self, searched: re.Match[str]):
        bvid = str(searched.group("bvid"))
        page_num = int(searched.group("page_num") or 1)
        return await self.parse_video(bvid=bvid, page_num=page_num)

    @handle("av", r"^av(?P<avid>\d{6,})(?:\s)?(?P<page_num>\d{1,3})?$")
    @handle("/av", r"bilibili\.com(?:/video)?/av(?P<avid>\d{6,})(?:.*?[?&]p=(?P<page_num>\d{1,3}))?")
    async def _parse_av(self, searched: re.Match[str]):
        avid = int(searched.group("avid"))
        page_num = int(searched.group("page_num") or 1)
        return await self.parse_video(avid=avid, page_num=page_num)

    @handle("/dynamic/", r"bilibili\.com/dynamic/(?P<dynamic_id>\d+)")
    @handle("/opus/", r"bilibili\.com/opus/(?P<dynamic_id>\d+)")
    @handle("t.bili", r"t\.bilibili\.com/(?P<dynamic_id>\d+)")
    async def _parse_dynamic(self, searched: re.Match[str]):
        dynamic_id = int(searched.group("dynamic_id"))
        return await self.parse_dynamic_or_opus(dynamic_id)

    @handle("live.bili", r"live\.bilibili\.com/(?P<room_id>\d+)")
    async def _parse_live(self, searched: re.Match[str]):
        room_id = int(searched.group("room_id"))
        return await self.parse_live(room_id)

    @handle("/favlist", r"favlist\?fid=(?P<fav_id>\d+)")
    async def _parse_favlist(self, searched: re.Match[str]):
        fav_id = int(searched.group("fav_id"))
        return await self.parse_favlist(fav_id)

    @handle("/read/", r"bilibili\.com/read/cv(?P<read_id>\d+)")
    async def _parse_read(self, searched: re.Match[str]):
        from bilibili_api.article import Article
        read_id = int(searched.group("read_id"))
        article = Article(read_id)
        opus = await article.turn_to_opus()
        return await self._parse_bilibli_api_opus(opus)

    async def parse_video(self, *, bvid: str | None = None, avid: int | None = None, page_num: int = 1):
        from ..bili_models.video import VideoInfo, AIConclusion

        # 重建可能已经老化的 bilibili-api HTTP client，防止连接池失效
        await self._ensure_fresh_client()

        video = Video(bvid=bvid, aid=avid, credential=await self.credential)
        video_info = convert(await video.get_info(), VideoInfo)
        author = self.create_author(video_info.owner.name, video_info.owner.face)
        page_info = video_info.extract_info_with_page(page_num)

        from ..config import get_config
        pconfig = get_config()

        cid = page_info.cid
        if self._credential and cid is not None:
            ai_result = await video.get_ai_conclusion(cid=cid)
            ai_conclusion = convert(ai_result, AIConclusion)
            ai_summary = ai_conclusion.summary
        else:
            ai_summary = "哔哩哔哩 cookie 未配置或失效, 无法使用 AI 总结"

        url = f"https://bilibili.com/{video_info.bvid}"
        if page_info.index > 0:
            url += f"?p={page_info.index + 1}"

        # 格式化时长
        duration_str = fmt_duration(page_info.duration)

        # 格式化统计数据
        s = video_info.stat
        stats_map = {
            "👍": s.like, "🪙": s.coin, "⭐": s.favorite,
            "↩️": s.share, "💬": s.reply, "👀": s.view, "💭": s.danmaku,
        }

        def fmt_num(n: int) -> str:
            return f"{n / 10000:.1f}万" if n >= 10000 else str(n)

        stats_line = " ".join(f"{k} {fmt_num(v)}" for k, v in stats_map.items() if v > 0)

        # 获取实时在线人数
        online_text = ""
        if cid is not None:
            try:
                online_data = await video.get_online(cid=cid)
                total = int(online_data.get("total", 0))
                count = int(online_data.get("count", 0))
                if total > 0:
                    online_text = f"🏄‍♂️ {total} 人正在观看，{count} 人在网页端观看"
            except Exception as e:
                pass
        else:
            logger.debug("cid 为 None，跳过在线人数获取")

        # 时长限制提示（大小限制在下载时动态检查）
        limit_warnings = []
        if page_info.duration > pconfig.VIDEO_DURATION_MAXIMUM:
            limit_warnings.append(f"⚠️ 视频时长({duration_str})超过限制({fmt_duration(pconfig.VIDEO_DURATION_MAXIMUM)})，不会下载视频")

        extra = {
            "info": ai_summary,
            "stats_line": stats_line,
            "duration": duration_str,
            "online": online_text,
            "content_type": "视频",
            "limit_warnings": limit_warnings,
        }

        async def download_video():
            output_path = pconfig.cache_dir / f"{video_info.bvid}-{page_num}.mp4"
            if output_path.exists():
                return output_path
            try:
                v_url, a_url = await self.extract_download_urls(video=video, page_index=page_info.index)
            except Exception as e:
                # 兜底：重建 bilibili-api client 后重试一次，应对连接池老化
                logger.warning(f"获取下载地址失败，重建 client 重试: {e}")
                await reset_bili_api_client()
                self._client_born_at = time.monotonic()
                v_url, a_url = await self.extract_download_urls(video=video, page_index=page_info.index)
            if page_info.duration > pconfig.VIDEO_DURATION_MAXIMUM:
                raise IgnoreException
            if a_url is not None:
                path = await self.downloader.download_av_and_merge(
                    v_url, a_url, output_path=output_path, ext_headers=self.headers,
                )
            else:
                path = await self.downloader._download_file(
                    v_url, file_name=output_path.name, ext_headers=self.headers,
                )
            return path

        video_content = self.create_video(
            asyncio.create_task(download_video()),
            page_info.cover, page_info.duration,
        )

        return self.result(
            url=url, title=page_info.title, timestamp=page_info.timestamp,
            text=video_info.desc, author=author, contents=[video_content],
            extra=extra,
        )

    async def parse_dynamic_or_opus(self, dynamic_id: int):
        from bilibili_api.dynamic import Dynamic
        from ..bili_models.dynamic import DynamicWrapper

        dynamic = Dynamic(dynamic_id, await self.credential)
        if await dynamic.is_article():
            return await self._parse_bilibli_api_opus(dynamic.turn_to_opus())

        dynamic_info = convert(await dynamic.get_info(), DynamicWrapper).item
        return await self._parse_dynamic_info(dynamic_info)

    async def _parse_dynamic_info(self, dynamic_info):
        from ..bili_models.dynamic import DynamicInfo

        if dynamic_info.is_video():
            if (major := dynamic_info.modules.major) and (archive := major.archive):
                result = await self.parse_video(bvid=archive.bvid)
                result.text = dynamic_info.text
                result.extra["content_type"] = "动态"
                return result

        author = self.create_author(dynamic_info.name, dynamic_info.avatar)
        contents: list[MediaContent] = []
        contents.extend(self.create_images(dynamic_info.image_urls))

        repost = None
        if dynamic_info.type == "DYNAMIC_TYPE_FORWARD" and dynamic_info.orig is not None:
            repost = await self._parse_dynamic_info(dynamic_info.orig)

        return self.result(
            title=dynamic_info.title, text=dynamic_info.text,
            timestamp=dynamic_info.timestamp, author=author,
            contents=contents, repost=repost, extra={"content_type": "动态"},
        )

    async def parse_opus_by_id(self, opus_id: int):
        opus = Opus(opus_id, await self.credential)
        return await self._parse_bilibli_api_opus(opus)

    async def _parse_bilibli_api_opus(self, bili_opus: Opus):
        from ..bili_models.opus import OpusItem

        opus_info = await bili_opus.get_info()
        if not isinstance(opus_info, dict):
            raise ParseException("获取图文动态信息失败")

        opus_data = convert(opus_info, OpusItem)
        author = self.create_author(*opus_data.name_avatar)

        result = self.result(author=author, title=opus_data.title, timestamp=opus_data.timestamp)
        for node in opus_data.extract_nodes():
            if isinstance(node, str):
                result.graphics.append(node)
            else:
                result.graphics.append(self.create_image(node.url, alt=node.alt))
        return result

    async def parse_live(self, room_id: int):
        from bilibili_api.live import LiveRoom
        from ..bili_models.live import RoomData

        room = LiveRoom(room_display_id=room_id, credential=await self.credential)
        info_dict = await room.get_room_info()
        room_data = convert(info_dict, RoomData)
        contents: list[MediaContent] = []
        if cover := room_data.cover:
            contents.append(self.create_image(self.downloader.download_img(cover, ext_headers=self.headers)))
        if keyframe := room_data.keyframe:
            contents.append(self.create_image(self.downloader.download_img(keyframe, ext_headers=self.headers)))
        author = self.create_author(room_data.name, room_data.avatar)
        url = f"https://www.bilibili.com/blackboard/live/live-activity-player.html?enterTheRoom=0&cid={room_id}"
        return self.result(url=url, title=room_data.title, text=room_data.detail,
                          contents=contents, author=author, extra={"content_type": "直播"})

    async def parse_favlist(self, fav_id: int):
        from bilibili_api.favorite_list import get_video_favorite_list_content
        from ..bili_models.favlist import FavData

        fav_dict = await get_video_favorite_list_content(fav_id)
        if fav_dict["medias"] is None:
            raise ParseException("收藏夹内容为空, 或被风控")
        favdata = convert(fav_dict, FavData)
        author = self.create_author(favdata.info.upper.name, favdata.info.upper.face)
        graphics: list[str | ImageContent] = []
        for fav in favdata.medias:
            graphics.append(self.create_image(fav.cover, alt=fav.desc))
            graphics.append(fav.desc)
        return self.result(title=favdata.title, timestamp=favdata.timestamp,
                          author=author, graphics=graphics, extra={"content_type": "收藏夹"})

    async def extract_download_urls(self, video: Video | None = None, *, bvid: str | None = None,
                                     avid: int | None = None, page_index: int = 0):
        from bilibili_api.video import (
            AudioStreamDownloadURL, VideoStreamDownloadURL, FLVStreamDownloadURL,
            MP4StreamDownloadURL, VideoDownloadURLDataDetecter, VideoQuality, VideoCodecs,
        )
        from ..config import get_config

        # 清晰度字符串 → VideoQuality 枚举映射
        QUALITY_MAP = {
            "360P": VideoQuality._360P,
            "480P": VideoQuality._480P,
            "720P": VideoQuality._720P,
            "1080P": VideoQuality._1080P,
            "1080P+": VideoQuality._1080P_PLUS,
            "4K": VideoQuality._4K,
            "8K": VideoQuality._8K,
        }

        # 从配置读取用户设置的清晰度，不区分大小写
        pconfig = get_config()
        raw_quality = pconfig.BILI_QUALITY.strip().upper().replace("＋", "+")
        target_quality = QUALITY_MAP.get(raw_quality, VideoQuality._1080P)

        if video is None:
            video = Video(bvid=bvid, aid=avid, credential=await self.credential)

        download_url_data = await video.get_download_url(page_index=page_index)
        detecter = VideoDownloadURLDataDetecter(download_url_data)
        streams = detecter.detect_best_streams(
            video_max_quality=target_quality,
            codecs=[VideoCodecs.AV1, VideoCodecs.AVC, VideoCodecs.HEV],
            no_dolby_video=True, no_hdr=True,
        )

        # 筛选视频流和音频流
        video_stream = next(
            (s for s in streams if isinstance(s, (VideoStreamDownloadURL, FLVStreamDownloadURL, MP4StreamDownloadURL))),
            None,
        )
        audio_stream = next(
            (s for s in streams if isinstance(s, AudioStreamDownloadURL)), None,
        )

        if video_stream is None:
            raise DownloadException("未找到可下载的视频流")

        if audio_stream is None:
            return video_stream.url, None

        return video_stream.url, audio_stream.url

    def _save_credential(self):
        if self._credential is None or self._cookies_file is None:
            return
        self._cookies_file.write_text(json.dumps(self._credential.get_cookies()))

    def _load_credential(self):
        if self._cookies_file is None or not self._cookies_file.exists():
            return
        try:
            self._credential = Credential.from_cookies(json.loads(self._cookies_file.read_text()))
        except Exception as e:
            logger.error(f"加载已保存的凭证失败: {e}")

    def _save_cookie_str(self, cookie_str: str):
        """将cookie字符串持久化保存，供下次启动时自动加载"""
        if self._cookies_file is None:
            return
        try:
            ck_dict = ck2dict(cookie_str)
            self._cookies_file.parent.mkdir(parents=True, exist_ok=True)
            self._cookies_file.write_text(json.dumps(ck_dict))
            logger.info("B站 Cookie 已持久化保存")
        except Exception as e:
            logger.error(f"保存 Cookie 失败: {e}")

    async def _init_credential(self):
        # 优先从已持久化的cookie文件加载
        self._load_credential()
        if self._credential is not None:
            if await self._credential.check_valid():
                logger.info("从持久化文件加载的B站 Cookie 有效")
                return
            logger.info("持久化文件中的 Cookie 已过期")

        # 其次从配置中的 BILI_CK 加载
        if self._bili_ck:
            credential = Credential.from_cookies(ck2dict(self._bili_ck))
            if await credential.check_valid():
                logger.info(f"B站配置中的 Cookie 有效, 已持久化保存")
                self._credential = credential
                self._save_credential()
                self._save_cookie_str(self._bili_ck)
                return
            logger.info("B站配置中的 Cookie 已过期")

    def update_cookie(self, cookie_str: str):
        """运行时更新B站Cookie，立即生效"""
        if not cookie_str:
            return
        self._bili_ck = cookie_str
        self._credential = None
        # 持久化保存，重启后自动生效
        self._save_cookie_str(cookie_str)
        logger.info("B站 Cookie 已更新，将在下次请求时重新初始化凭证")

    @property
    async def credential(self) -> Credential | None:
        if self._credential is None:
            await self._init_credential()
            if self._credential is None:
                return None
            return self._credential

        # 已过期时尝试重新初始化
        if not await self._credential.check_valid():
            logger.warning("哔哩哔哩凭证已过期, 尝试重新初始化")
            self._credential = None
            await self._init_credential()
            if self._credential is None:
                return None

        # 尝试刷新
        if self._credential and await self._credential.check_refresh():
            logger.info("哔哩哔哩凭证需要刷新")
            if self._credential.has_ac_time_value() and self._credential.has_bili_jct():
                await self._credential.refresh()
                self._save_credential()

        return self._credential
