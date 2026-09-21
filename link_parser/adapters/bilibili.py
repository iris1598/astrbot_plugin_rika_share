"""Bilibili 解析器 - 支持视频、动态、直播、专栏、收藏夹"""

import re
import json
import time
import asyncio
from typing import ClassVar

from astrbot.api import logger
from bilibili_api import HEADERS, Credential, select_client, request_settings
from bilibili_api.opus import Opus
from bilibili_api.video import Video
from msgspec import convert

from ..constants import PlatformEnum
from ..exceptions import DownloadException, IgnoreException, ParseException
from ..models import ImageContent, MediaContent, Platform
from ..models.platforms.bilibili import (
    AIConclusion,
    DynamicWrapper,
    FavData,
    OpusItem,
    RoomData,
    VideoInfo,
)
from ..utils.cookie import ck2dict
from ..utils.formatting import fmt_duration
from .base import BaseParser, handle
from .registry import AdapterSpec, register_adapter

try:
    select_client("curl_cffi")
    request_settings.set("impersonate", "chrome131")
except Exception:
    logger.warning("curl_cffi 未注册/未安装，B站解析器将使用默认 httpx 客户端")
    select_client("httpx")


#: ``Credential.get_cookies()`` 会把自身的**属性名**也一并输出，与规范 cookie 名重复：
#: ``sessdata`` ↔ ``SESSDATA``、``dedeuserid`` ↔ ``DedeUserID``，另有 ``proxy``。
#: 它们不是真实 cookie，混进请求头只会让 cookie 串变长（实测 716 → 约 400 字符）并
#: 徒增被风控注意的机会，因此统一剔除。
_CREDENTIAL_ALIAS_KEYS = frozenset({"sessdata", "dedeuserid", "proxy"})


def _credential_cookie_dict(credential: "Credential") -> dict[str, str]:
    """把 ``Credential`` 归一化成可直接持久化 / 拼请求头的 cookie 字典（丢弃空值）。"""
    return {
        key: value
        for key, value in credential.get_cookies().items()
        if value and key not in _CREDENTIAL_ALIAS_KEYS
    }


class BilibiliParser(BaseParser):
    platform: ClassVar[Platform] = Platform(name=PlatformEnum.BILIBILI, display_name="哔哩哔哩")

    #: B站解析结果带「实时数据」——视频的在线观看人数、直播间的场次标题与封面，
    #: 这些值会随时间变化，永久缓存会导致重复分享时展示过期内容。
    #: 因此结果缓存只保留 5 分钟：期间重复分享仍走缓存，超过则重新解析拿新数据。
    CACHE_TTL_SECONDS = 300

    #: b23.tv / bili2233.cn 短链：需先跟随跳转才能拿到 BV 号等内容标识
    SHORT_LINK_KEYWORDS = ("b23.tv", "bili2233.cn")

    #: 凭证校验（有效性 + 是否需要刷新）的最小间隔（秒）。
    #: ``check_valid`` / ``check_refresh`` 都是网络请求，早期实现每条链接都打两次，
    #: 既浪费又容易触发风控；这里做时间窗缓存，只在窗口过期后才重新校验。
    VALIDATE_INTERVAL = 600

    @staticmethod
    def _is_transient_api_error(error: Exception) -> bool:
        """判断 B 站接口错误是否适合重试。

        -504 是 B 站上游服务调用超时，通常是临时性错误；网络层超时也按同样方式处理。
        """
        if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
            return True

        code = getattr(error, "code", None)
        if code is None:
            code = getattr(error, "retcode", None)
        try:
            if int(code) == -504:
                return True
        except (TypeError, ValueError):
            pass

        message = str(error).lower()
        return "-504" in message or "服务调用超时" in message or "timeout" in message or "timed out" in message

    async def _call_bili_api_with_retry(self, call, *, operation: str, retries: int = 2):
        """对 B 站临时超时做少量退避重试，避免瞬时故障直接导致解析失败。"""
        for attempt in range(retries + 1):
            try:
                return await call()
            except Exception as error:
                if not self._is_transient_api_error(error) or attempt >= retries:
                    raise

                delay = 0.8 * (attempt + 1)
                logger.warning(
                    f"B站{operation}接口临时超时，{delay:.1f}秒后重试 "
                    f"({attempt + 1}/{retries})：{error}"
                )
                await asyncio.sleep(delay)

    def __init__(self, downloader, bili_ck: str | None = None, config_dir=None):
        super().__init__(downloader)
        self.headers = HEADERS.copy()
        self._credential: Credential | None = None
        self._bili_ck = bili_ck
        self._cookies_file = (config_dir / "bilibili_cookies.json") if config_dir else None
        #: 上次凭证校验的时刻（monotonic），配合 VALIDATE_INTERVAL 做降频
        self._validated_at: float = 0.0

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
        credential = await self.credential
        video = Video(bvid=bvid, aid=avid, credential=credential)
        video_info = convert(
            await self._call_bili_api_with_retry(video.get_info, operation="视频信息"),
            VideoInfo,
        )
        author = self.create_author(video_info.owner.name, video_info.owner.face)
        page_info = video_info.extract_info_with_page(page_num)

        from ..config import get_config
        pconfig = get_config()

        cid = page_info.cid
        ai_summary = "B站 AI 总结暂时不可用"
        if credential and cid is not None:
            try:
                ai_result = await self._call_bili_api_with_retry(
                    lambda: video.get_ai_conclusion(cid=cid),
                    operation="AI总结",
                )
                ai_conclusion = convert(ai_result, AIConclusion)
                ai_summary = ai_conclusion.summary
            except Exception as error:
                # AI 总结是附加信息，接口临时超时不应阻断标题、封面和视频解析。
                logger.warning(f"B站 AI 总结获取失败，跳过该字段继续解析：{error}")
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
            except Exception:
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
            v_url, v_backups, a_url, a_backups = await self.extract_download_urls(video=video, page_index=page_info.index)
            if page_info.duration > pconfig.VIDEO_DURATION_MAXIMUM:
                raise IgnoreException

            url_pairs = [(v_url, a_url)]
            for i, v_bu in enumerate(v_backups):
                a_bu = a_backups[i] if i < len(a_backups) else a_url
                url_pairs.append((v_bu, a_bu))

            last_error = None
            for idx, (v_try, a_try) in enumerate(url_pairs):
                try:
                    if idx > 0:
                        logger.info(f"B站 CDN 重试 ({idx+1}/{len(url_pairs)})")
                    if a_try is not None:
                        return await self.downloader.download_av_and_merge(
                            v_try, a_try, output_path=output_path, ext_headers=self.headers,
                        )
                    else:
                        return await self.downloader._download_file(
                            v_try, file_name=output_path.name, ext_headers=self.headers,
                        )
                except Exception as e:
                    if idx > 0:
                        logger.warning(f"B站 CDN 重试 ({idx+1}/{len(url_pairs)}) 失败: {e}")
                    last_error = e
                    continue

            raise DownloadException("视频下载失败，已尝试所有CDN") from last_error

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

        dynamic = Dynamic(dynamic_id, await self.credential)
        if await dynamic.is_article():
            return await self._parse_bilibli_api_opus(dynamic.turn_to_opus())

        dynamic_info = convert(await dynamic.get_info(), DynamicWrapper).item
        return await self._parse_dynamic_info(dynamic_info)

    async def _parse_dynamic_info(self, dynamic_info):

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

        download_url_data = await self._call_bili_api_with_retry(
            lambda: video.get_download_url(page_index=page_index),
            operation="视频流地址",
        )
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

        v_backups = video_stream.backup_url if isinstance(video_stream, VideoStreamDownloadURL) else []
        a_backups = audio_stream.backup_url if audio_stream and isinstance(audio_stream, AudioStreamDownloadURL) else []

        if audio_stream is None:
            return video_stream.url, v_backups, None, []

        return video_stream.url, v_backups, audio_stream.url, a_backups

    # ---------- 凭证（Cookie）管理 ----------
    #
    # 本解析器是 cookie 的**唯一持有者**：磁盘上写 config/bilibili_cookies.json，
    # 内存里是 self._credential。BiliAccountService 只做检测与通知，通过
    # ``export_cookie()`` 回读、通过 ``update_cookie()`` 写入，不再自己存一份权威副本。

    def _save_credential(self):
        if self._credential is None or self._cookies_file is None:
            return
        try:
            self._cookies_file.parent.mkdir(parents=True, exist_ok=True)
            self._cookies_file.write_text(
                json.dumps(_credential_cookie_dict(self._credential), ensure_ascii=False)
            )
        except (OSError, TypeError) as e:
            logger.error(f"保存B站凭证失败: {e}")

    def _load_credential(self) -> bool:
        """从持久化文件加载凭证，返回是否成功。"""
        if self._cookies_file is None or not self._cookies_file.exists():
            return False
        try:
            data = json.loads(self._cookies_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"加载已保存的凭证失败: {e}")
            return False
        self._credential = Credential.from_cookies(data)
        return True

    def _save_cookie_str(self, cookie_str: str):
        """将cookie字符串持久化保存，供下次启动时自动加载"""
        if self._cookies_file is None:
            return
        try:
            self._cookies_file.parent.mkdir(parents=True, exist_ok=True)
            self._cookies_file.write_text(
                json.dumps(ck2dict(cookie_str), ensure_ascii=False)
            )
            logger.info("B站 Cookie 已持久化保存")
        except (OSError, TypeError) as e:
            logger.error(f"保存 Cookie 失败: {e}")

    def export_cookie(self) -> str | None:
        """导出当前生效的 cookie 串，供账号服务回读（保证 cookie 只有一份真相）。

        ``_credential`` 尚未初始化时回退到磁盘文件，再回退到配置项。
        """
        if self._credential is not None:
            items = _credential_cookie_dict(self._credential)
            if items:
                return "; ".join(f"{k}={v}" for k, v in items.items())
        if self._cookies_file is not None and self._cookies_file.exists():
            try:
                data = json.loads(self._cookies_file.read_text(encoding="utf-8"))
                items = {k: v for k, v in data.items() if v}
                if items:
                    return "; ".join(f"{k}={v}" for k, v in items.items())
            except (OSError, json.JSONDecodeError):
                pass
        return self._bili_ck or None

    def update_cookie(self, cookie_str: str):
        """运行时更新B站Cookie，立即生效。

        这里**刻意不写回 ``_bili_ck``**：配置项是只读的静态回退来源，早期实现把它
        也覆盖掉之后，运行期一旦合并出不可用的 cookie，连最后的干净回退都没了，
        只能靠重载插件重新读配置来恢复。
        """
        if not cookie_str:
            return
        self._save_cookie_str(cookie_str)
        self._credential = None
        self._validated_at = 0.0
        logger.info("B站 Cookie 已更新，将在下次请求时重新初始化凭证")

    async def _safe_check_valid(self) -> bool:
        """``check_valid`` 的网络异常按「校验不通过」处理，不让它冒泡打断解析。"""
        if self._credential is None:
            return False
        try:
            return bool(await self._credential.check_valid())
        except Exception as e:
            logger.warning(f"B站凭证有效性校验失败: {e}")
            return False

    async def _ensure_buvid(self) -> None:
        """补齐设备指纹 ``buvid3`` / ``buvid4``。

        扫码登录的响应里通常不带这两个（Set-Cookie 里也没有，实测为空），而它们是
        B站 的设备标识。缺失时 bilibili-api 会在**每次请求**临时生成，等于每次换一个
        指纹，反而更容易被判定为异常流量。这里一次性取回并落盘，之后所有请求都用同一个。
        """
        if self._credential is None:
            return
        if self._credential.has_buvid3() and self._credential.has_buvid4():
            return
        try:
            from bilibili_api.utils.network import get_buvid

            buvid3, buvid4 = await get_buvid()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"获取设备指纹 buvid3/buvid4 失败（不影响登录态）：{e}")
            return
        if not self._credential.has_buvid3():
            self._credential.buvid3 = buvid3
        if not self._credential.has_buvid4():
            self._credential.buvid4 = buvid4
        logger.info("已补齐设备指纹 buvid3 / buvid4")
        self._save_credential()

    async def _init_credential(self) -> None:
        """确定当前凭证：持久化文件优先，其次配置项。

        校验不通过的来源会被**显式丢弃**（置 None）。早期实现保留了这个已判定失效的
        ``Credential``，属性又看到「非 None」就直接返回，于是解析器拿着失效凭证去请求
        ``playurl``，被 B站 当成未登录，只能拿到 540P 流（而标题/封面等公开接口仍正常，
        所以表面上看解析是成功的）。
        """
        if self._load_credential():
            if await self._safe_check_valid():
                logger.info("从持久化文件加载的B站 Cookie 有效")
                await self._ensure_buvid()
                return
            logger.info("持久化文件中的 Cookie 已失效，丢弃")
            self._credential = None

        if self._bili_ck:
            try:
                self._credential = Credential.from_cookies(ck2dict(self._bili_ck))
            except Exception as e:
                logger.error(f"配置中的B站 Cookie 解析失败: {e}")
                self._credential = None
                return
            if await self._safe_check_valid():
                logger.info("B站配置中的 Cookie 有效, 已持久化保存")
                await self._ensure_buvid()
                self._save_credential()
                return
            logger.info("B站配置中的 Cookie 已失效，丢弃")
            self._credential = None

    async def _revalidate(self) -> None:
        """低频重校验：失效则重载，需要则刷新。任何失败都保留当前凭证继续使用。"""
        if not await self._safe_check_valid():
            logger.info("B站凭证已失效，尝试重新加载")
            self._credential = None
            await self._init_credential()
            return

        try:
            if not await self._credential.check_refresh():
                return
            if not (
                self._credential.has_ac_time_value() and self._credential.has_bili_jct()
            ):
                # ac_time_value 只在扫码登录的响应体（data.refresh_token）里下发，
                # 旧实现只解析 Set-Cookie 导致它恒为空 —— 于是「一直提示需要刷新，
                # 却永远刷新不了」。这里明确把原因打出来，避免再次误判。
                logger.warning(
                    "B站凭证提示需要刷新，但缺少 ac_time_value（扫码登录未保存 "
                    "refresh_token）或 bili_jct，无法自动刷新，请重新扫码登录"
                )
                return
            logger.info("B站凭证需要刷新，正在刷新")
            await self._credential.refresh()
            self._save_credential()
            logger.info("B站凭证已刷新并保存")
        except Exception as e:
            logger.warning(f"B站凭证刷新失败（保留当前凭证继续使用）: {e}")

    @property
    async def credential(self) -> Credential | None:
        """取当前凭证，按 ``VALIDATE_INTERVAL`` 降频校验。

        未拿到凭证时也会遵守时间窗：避免在「cookie 确实失效」期间每条链接都发起
        两次校验请求，反而更容易被风控。
        """
        now = time.monotonic()
        if now - self._validated_at >= self.VALIDATE_INTERVAL:
            self._validated_at = now
            if self._credential is None:
                await self._init_credential()
            else:
                await self._revalidate()
        return self._credential


ADAPTER = register_adapter(
    AdapterSpec(
        name=PlatformEnum.BILIBILI.value,
        url_pattern=re.compile(
            r"(bilibili\.com|b23\.tv|bili2233\.cn|BV[1-9a-zA-Z]{10}|av\d{6,})"
        ),
        parser_cls=BilibiliParser,
        description="视频 / 动态 / 图文(Opus) / 直播 / 专栏 / 收藏夹",
        build=lambda ctx: BilibiliParser(
            ctx.downloader, bili_ck=ctx.config.BILI_CK, config_dir=ctx.config_dir
        ),
    )
)
