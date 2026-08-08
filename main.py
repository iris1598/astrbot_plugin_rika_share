"""
莉卡解析 - 链接分享解析插件

支持 B站 | 抖音 | 快手 | 微博 | 小红书 | Twitter | AcFun | NGA

移植自 nonebot-plugin-parser (https://github.com/fllesser/nonebot-plugin-parser)
内置B站扫码登录、Cookie监控、自动应用Cookie功能
"""

import os
import re
import json
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Optional, Dict

import aiohttp
import qrcode
from cryptography.fernet import Fernet
from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult, MessageChain
import astrbot.api.message_components as Comp
from astrbot.api.star import Context, Star, register, StarTools

from .core.utils import clear_cache_dir, cleanup_cache_dir
from .core.config import init_config, get_config
from .core.download import StreamDownloader
from .core.data import ParseResult
from .core.exception import (
    ParseException, IgnoreException, DownloadException, SilentException,
    is_timeout_exception,
)
from .core.cloudflare_screenshot import (
    CloudflareScreenshotClient,
    fetch_page_title,
    is_url_blacklisted,
)
from .core.render import ShareCardRenderer
from .core.parsers import (
    BilibiliParser, DouyinParser, KuaiShouParser, WeiBoParser,
    XiaoHongShuParser, TwitterParser, NGAParser, AcfunParser,
)

# ========== B站扫码登录 API ==========
BILI_QR_GENERATE_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
BILI_QR_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"

# 扫码状态码
QR_CODE_UNSCANNED = 86101
QR_CODE_SCANNED = 86090
QR_CODE_EXPIRED = 86038
QR_CODE_SUCCESS = 0

# 二维码有效期（秒）
QR_CODE_EXPIRE_TIME = 180
POLL_INTERVAL = 5


def _get_plugin_data_dir() -> Path:
    from astrbot.core.utils.astrbot_path import get_astrbot_data_path
    return Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_rika_share"


# ========== URL 匹配模式 ==========
BILIBILI_PATTERN = re.compile(r"(bilibili\.com|b23\.tv|bili2233\.cn|BV[1-9a-zA-Z]{10}|av\d{6,})")
DOUYIN_PATTERN = re.compile(r"(v\.douyin\.com|douyin\.com|iesdouyin\.com|m\.douyin\.com|jx\.douyin\.com|jingxuan\.douyin\.com)")
KUAISHOU_PATTERN = re.compile(r"(v\.kuaishou\.com|kuaishou\.com|chenzhongtech\.com)")
WEIBO_PATTERN = re.compile(r"(weibo\.com|weibo\.cn|m\.weibo\.cn|video\.weibo\.com|mapp\.api\.weibo\.cn)")
XHS_PATTERN = re.compile(r"(xhslink\.com|xhslink\.cn|xiaohongshu\.com)")
TWITTER_PATTERN = re.compile(r"x\.com")
NGA_PATTERN = re.compile(r"nga\.178\.com|ngabbs\.com|bbs\.nga\.cn")
ACFUN_PATTERN = re.compile(r"acfun\.cn")

# 通用 URL 匹配（用于 Cloudflare 截图 Fallback）
GENERIC_URL_PATTERN = re.compile(r"https?://[^\s'\"<>]+")


class _EventUrlWrapper:
    def __init__(self, event: AstrMessageEvent, url: str):
        self._event = event
        self.message_str = url

    def __getattr__(self, name):
        return getattr(self._event, name)


@register("链接解析器", "fllesser (ported to AstrBot)",
          "链接分享自动解析插件，支持 B站|抖音|快手|微博|小红书|Twitter|AcFun|NGA", "2.10.0")
class ParserPlugin(Star):
    # 合并转发（Comp.Nodes）是 OneBot v11 独有特性，其他平台均不支持
    @staticmethod
    def _is_onebot(event: AstrMessageEvent) -> bool:
        """检测当前平台是否为 OneBot v11（aiocqhttp 适配器）。"""
        try:
            platform_name = event.get_platform_name().lower()
            is_ob = "aiocqhttp" in platform_name
            if is_ob:
                logger.info(
                    f"[rika_share] 检测到 OneBot 平台: {platform_name}，使用合并转发"
                )
            return is_ob
        except Exception:
            return False

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        data_dir = _get_plugin_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir = data_dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir = data_dir / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)

        pconfig = init_config(config, self.cache_dir, self.config_dir)

        # 将旧版扁平配置迁移到分组配置，避免设置页整理后已有设置丢失
        try:
            from .core.config import migrate_grouped_config

            if migrate_grouped_config(config):
                save = getattr(config, "save_config", None)
                if callable(save):
                    save()
                logger.info("已迁移旧版扁平配置到分组配置")
        except Exception:
            logger.warning("旧版配置迁移失败，将使用兼容回退读取", exc_info=True)

        self.downloader = StreamDownloader(self.cache_dir)
        self.disabled_platforms = pconfig.DISABLED_PLATFORMS

        self.parsers: dict[str, Any] = {}
        self._init_parsers()
        self._result_cache: dict[str, ParseResult] = {}
        self._render_cache: dict[str, Path] = {}
        self._cache_cleanup_task: asyncio.Task | None = None

        # ========== 解析图片渲染 ==========
        self._renderer = ShareCardRenderer(
            self.cache_dir,
            enabled=pconfig.RENDER_ENABLED,
            width=pconfig.RENDER_WIDTH,
            theme=pconfig.RENDER_THEME,
            font_path=pconfig.RENDER_FONT_PATH or None,
            layout=pconfig.RENDER_LAYOUT,
            cover_full_size=pconfig.RENDER_COVER_FULL_SIZE,
        )
        if self._renderer.enabled:
            logger.info(
                f"解析图片渲染已启用 (主题: {pconfig.RENDER_THEME}, "
                f"布局: {pconfig.RENDER_LAYOUT}, "
                f"封面全尺寸: {pconfig.RENDER_COVER_FULL_SIZE}, "
                f"宽度: {pconfig.RENDER_WIDTH}px)"
            )
        else:
            logger.info("解析图片渲染已关闭，使用文本输出")

        # ========== B站 Cookie 监控状态 ==========
        self._bili_cookie: str = ""
        self._bili_http_session: aiohttp.ClientSession | None = None
        self._bili_monitor_running: bool = False
        self._bili_monitor_task: asyncio.Task | None = None
        self._bili_login_tasks: Dict[str, asyncio.Task] = {}
        self._bili_cookie_lock = asyncio.Lock()
        self._bili_file_lock = asyncio.Lock()
        self._bili_last_status: Optional[Dict] = None
        self._bili_last_check_time: Optional[datetime] = None
        self._bili_was_invalid: bool = False

        # Cookie 持久化目录
        self._bili_data_dir = StarTools.get_data_dir("astrbot_plugin_rika_share")
        self._bili_data_dir.mkdir(parents=True, exist_ok=True)
        self._bili_status_file = self._bili_data_dir / "bili_cookie_status.json"
        self._bili_key_file = self._bili_data_dir / ".bili_cookie_key"

        # ========== Cloudflare 截图 Fallback ==========
        self._cloudflare_client: CloudflareScreenshotClient | None = None
        if pconfig.CLOUDFLARE_FALLBACK_ENABLED:
            self._cloudflare_client = CloudflareScreenshotClient(config)
            if self._cloudflare_client.is_configured:
                logger.info("Cloudflare 网页截图 Fallback 已启用")
            else:
                logger.warning(
                    "Cloudflare 截图 Fallback 已开启但未配置 Account ID / API Token，"
                    "请检查插件配置"
                )

    def _init_parsers(self):
        pconfig = get_config()
        disabled = self.disabled_platforms
        if "bilibili" not in disabled:
            self.parsers["bilibili"] = BilibiliParser(self.downloader, bili_ck=pconfig.BILI_CK, config_dir=self.config_dir)
        if "douyin" not in disabled:
            self.parsers["douyin"] = DouyinParser(self.downloader)
        if "kuaishou" not in disabled:
            self.parsers["kuaishou"] = KuaiShouParser(self.downloader)
        if "weibo" not in disabled:
            self.parsers["weibo"] = WeiBoParser(self.downloader)
        if "xiaohongshu" not in disabled:
            self.parsers["xiaohongshu"] = XiaoHongShuParser(self.downloader, xhs_ck=pconfig.XHS_CK)
        if "twitter" not in disabled:
            self.parsers["twitter"] = TwitterParser(self.downloader)
        if "nga" not in disabled:
            self.parsers["nga"] = NGAParser(self.downloader)
        if "acfun" not in disabled:
            self.parsers["acfun"] = AcfunParser(self.downloader)
        logger.info(f"已启用平台: {', '.join(self.parsers.keys())}")

    async def initialize(self):
        pconfig = get_config()
        ttl = pconfig.CACHE_TTL_HOURS
        if ttl > 0:
            interval = max(pconfig.CACHE_CLEANUP_INTERVAL_MINUTES, 1) * 60

            async def _cache_cleanup_loop():
                logger.info(
                    f"缓存清理已启动 (TTL={ttl}h, 间隔={pconfig.CACHE_CLEANUP_INTERVAL_MINUTES}min)"
                )
                try:
                    while True:
                        await cleanup_cache_dir(self.cache_dir, ttl_hours=ttl)
                        # 文件清理后同步清空内存缓存（解析结果 + 渲染图片）
                        self._result_cache.clear()
                        self._render_cache.clear()
                        await asyncio.sleep(interval)
                except asyncio.CancelledError:
                    logger.info("缓存清理任务已停止")
                    raise

            self._cache_cleanup_task = asyncio.create_task(_cache_cleanup_loop())
        else:
            logger.info("缓存自动清理已禁用 (CACHE_TTL_HOURS=0)")

        # ========== B站 Cookie 初始化 ==========
        await self._bili_load_last_status()
        await self._bili_load_cookie()
        self._bili_http_session = aiohttp.ClientSession()

        # 如果已有cookie（从持久化加载或配置中），更新到BilibiliParser
        if self._bili_cookie:
            self._bili_apply_cookie_to_parser(self._bili_cookie)

        # 启动监控循环
        if pconfig.BILI_COOKIE_MONITOR_ENABLED and self._bili_cookie:
            self._bili_start_monitor()

    # ==================== 平台处理器 ====================

    async def _dispatch(self, event: AstrMessageEvent, name: str):
        if self._has_json_component(event):
            return
        parser = self.parsers.get(name)
        if not parser:
            return
        async for r in self._process_url(event, parser):
            yield r

    @filter.regex(BILIBILI_PATTERN)
    async def bilibili_handler(self, event: AstrMessageEvent, matched: re.Match | None = None):
        async for r in self._dispatch(event, "bilibili"):
            yield r

    @filter.regex(DOUYIN_PATTERN)
    async def douyin_handler(self, event: AstrMessageEvent, matched: re.Match | None = None):
        async for r in self._dispatch(event, "douyin"):
            yield r

    @filter.regex(KUAISHOU_PATTERN)
    async def kuaishou_handler(self, event: AstrMessageEvent, matched: re.Match | None = None):
        async for r in self._dispatch(event, "kuaishou"):
            yield r

    @filter.regex(WEIBO_PATTERN)
    async def weibo_handler(self, event: AstrMessageEvent, matched: re.Match | None = None):
        async for r in self._dispatch(event, "weibo"):
            yield r

    @filter.regex(XHS_PATTERN)
    async def xiaohongshu_handler(self, event: AstrMessageEvent, matched: re.Match | None = None):
        async for r in self._dispatch(event, "xiaohongshu"):
            yield r

    @filter.regex(TWITTER_PATTERN)
    async def twitter_handler(self, event: AstrMessageEvent, matched: re.Match | None = None):
        async for r in self._dispatch(event, "twitter"):
            yield r

    @filter.regex(NGA_PATTERN)
    async def nga_handler(self, event: AstrMessageEvent, matched: re.Match | None = None):
        async for r in self._dispatch(event, "nga"):
            yield r

    @filter.regex(ACFUN_PATTERN)
    async def acfun_handler(self, event: AstrMessageEvent, matched: re.Match | None = None):
        async for r in self._dispatch(event, "acfun"):
            yield r

    # ==================== JSON 卡片处理器 ====================

    @filter.regex(r".*")
    async def json_card_handler(self, event: AstrMessageEvent, matched: re.Match | None = None):
        if not self._has_json_component(event):
            return
        links = self._extract_links_from_event(event)
        if not links:
            return
        unique_links = list(dict.fromkeys(links))
        for link in unique_links:
            for _, parser in self.parsers.items():
                try:
                    _, _ = parser.search_url(link)
                    wrapped = _EventUrlWrapper(event, link)
                    async for r in self._process_url(wrapped, parser):
                        yield r
                    return
                except ParseException:
                    continue

    # ==================== Cloudflare 截图 Fallback ====================

    def _is_cloudflare_available(self) -> bool:
        """Cloudflare 截图 Fallback 是否可用"""
        if self._cloudflare_client is None:
            return False
        return self._cloudflare_client.is_configured

    async def _do_cloudflare_fallback(
        self, event: AstrMessageEvent, url: str
    ):
        """Cloudflare 网页截图 fallback 处理：渲染网页并发送截图"""
        # 先获取标题（并发：和截图并行）
        title_task = asyncio.create_task(fetch_page_title(url))

        save_dir = self.cache_dir / "cloudflare_screenshots"
        path = await self._cloudflare_client.screenshot(url, save_dir)

        title = await title_task
        # 对齐其它解析器的 header 格式：平台名 | 标题
        fallback_title = title or url[:80]
        header = f"莉卡解析 | 网站 - {fallback_title}"

        if path is None:
            # 静默失败：出错不回复；是否记录日志由“启用详细错误日志”开关控制
            if get_config().DEBUG_LOG_ENABLED:
                err = getattr(self._cloudflare_client, "last_error", None)
                if err:
                    logger.warning(
                        f"Cloudflare 截图失败，已静默跳过: {url[:80]} | {err}"
                    )
                else:
                    logger.warning(f"Cloudflare 截图失败，已静默跳过: {url[:80]}")
            return

        # 发送截图
        if self._is_onebot(event):
            sender_name = event.get_sender_name()
            sender_id = event.get_sender_id()
            nodes = Comp.Nodes([])
            nodes.nodes.append(Comp.Node(
                uin=sender_id, name=sender_name,
                content=[Comp.Plain(header)]
            ))
            nodes.nodes.append(Comp.Node(
                uin=sender_id, name=sender_name,
                content=[Comp.Image.fromFileSystem(str(path))]
            ))
            yield event.chain_result([nodes])
        else:
            # 非 OneBot 平台：主动发送，不经过事件回复管线，
            # 避免 AstrBot 开启“回复时 @ 发送人”时，在图片 markdown 前插入 @ 导致格式异常
            try:
                sent = await self.context.send_message(
                    event.unified_msg_origin,
                    MessageChain().message(f"{header}\n").file_image(str(path)),
                )
                if not sent:
                    logger.warning(f"Cloudflare 截图主动发送未找到匹配平台会话: {path.name}")
                else:
                    logger.info(f"Cloudflare 网页截图已主动发送: {path.name}")
            except Exception as e:
                logger.warning(f"Cloudflare 截图主动发送异常: {e}")

    @filter.regex(GENERIC_URL_PATTERN)
    async def cloudflare_fallback_handler(
        self, event: AstrMessageEvent, matched: re.Match | None = None
    ):
        """通用 URL 兜底处理：不匹配任何适配器的链接 → Cloudflare 网页截图"""
        if not self._is_cloudflare_available():
            return
        # JSON 卡片由 json_card_handler 处理，避免重复
        if self._has_json_component(event):
            return

        # 注意：AstrBot 的 @filter.regex 不传递 match 对象给 handler
        # 需要自己从 event.message_str 中提取 URL
        msg = event.message_str.strip()
        m = GENERIC_URL_PATTERN.search(msg)
        if not m:
            return
        url = m.group(0)
        # 清理 URL 尾部可能带上的标点
        url = url.rstrip(".,!?;:)'\"】」》）")

        # 遍历所有已启用的解析器，若已有适配器能处理则跳过
        for parser in self.parsers.values():
            try:
                parser.search_url(url)
                return  # 已有适配器，让平台专用 handler 处理
            except Exception:
                continue

        # 命中黑名单则跳过 Cloudflare 截图
        if is_url_blacklisted(url, get_config().CLOUDFLARE_BLACKLIST):
            logger.info(f"Cloudflare Fallback: URL 命中黑名单，跳过: {url[:80]}")
            return

        logger.info(f"Cloudflare Fallback: 未匹配适配器，渲染网页截图: {url[:80]}")
        async for r in self._do_cloudflare_fallback(event, url):
            yield r

    # ==================== 核心处理流程 ====================

    async def _process_url(self, event: AstrMessageEvent, parser: Any) -> AsyncGenerator[MessageEventResult, None]:
        url = event.message_str.strip()
        pconfig = get_config()

        try:
            cache_key = url[:64]
            result = self._result_cache.get(cache_key)

            if result is None:
                keyword, searched = parser.search_url(url)
                result = await parser.parse(keyword, searched)
                self._result_cache[cache_key] = result
            else:
                yield event.plain_result("🔄 命中缓存...")

            # 根据平台构建：标题头 + 合并转发内容列表
            header, nodes_content = await self._build_platform_output(event, result, result.platform.name)

            # 渲染精美解析卡片（失败时 render_path 为 None，自动回退文本输出）
            render_path: Path | None = None
            if self._renderer is not None and self._renderer.enabled:
                render_path = await self._renderer.render(
                    result,
                    cache_key=cache_key,
                    existing=self._render_cache.get(cache_key),
                )
                if render_path is not None:
                    self._render_cache[cache_key] = render_path

            warnings = result.extra.get("limit_warnings") or []
            is_video = bool(result.video_contents)

            if render_path is not None:
                # 渲染图单独发送（主动发送，不经过事件回复管线，
                # 避免被 AstrBot 的“回复时引用原消息”设置附加引用回复）
                try:
                    sent = await self.context.send_message(
                        event.unified_msg_origin,
                        MessageChain().file_image(str(render_path)),
                    )
                    if not sent:
                        logger.warning(f"解析卡片主动发送未找到匹配平台会话: {render_path.name}")
                    else:
                        logger.info(f"解析卡片已单独发送: {render_path.name}")
                except Exception as e:
                    logger.warning(f"解析卡片主动发送异常: {e}")

                if is_video:
                    # 视频：卡片已承载全部信息（含时长超限警告），不再重复发送文字摘要或警告
                    header_text = ""
                    text_items = []
                else:
                    # 图文 / 动态：保留文字部分与图集图片，按平台规则发送（警告已合并在卡片图中）
                    header_text = header
                    text_items = list(nodes_content)
            else:
                # 未启用 / 渲染失败：保持原有文本输出逻辑
                header_text = header
                text_items = list(nodes_content)
                for w in warnings:
                    text_items.append([Comp.Plain(w)])

            if text_items:
                # 按平台规则发送剩余内容：OneBot 使用合并转发，其他平台直接发送
                if self._is_onebot(event):
                    sender_name = event.get_sender_name()
                    sender_id = event.get_sender_id()
                    nodes = Comp.Nodes([])
                    if header_text:
                        nodes.nodes.append(Comp.Node(
                            uin=sender_id, name=sender_name,
                            content=[Comp.Plain(header_text)],
                        ))
                    for item in text_items:
                        nodes.nodes.append(Comp.Node(
                            uin=sender_id, name=sender_name, content=item,
                        ))
                    yield event.chain_result([nodes])
                else:
                    # 其他平台（QQ Official / Telegram 等）：拆分为独立消息
                    async for r in self._send_plain_output(event, header_text, text_items):
                        yield r

            # 单独发送媒体文件（Video / Audio）
            # 注意：图片已在 Nodes（OneBot）或 _send_plain_output（其他平台）中处理
            async for r in self._try_send_media(event, result):
                yield r

        except SilentException:
            return  # 匹配不到模式时静默失败，不发送通知
        except IgnoreException as e:
            yield event.plain_result(f"ℹ️ {e.message}")
        except ParseException as e:
            yield event.plain_result(f"❌ 解析失败: {e.message}")
        except DownloadException as e:
            yield event.plain_result(f"⚠️ 下载失败: {e.message}")
        except Exception as e:
            logger.exception(f"解析异常")
            yield event.plain_result(f"❌ 处理出错: {str(e)[:100]}")

    async def _try_send_media(self, event: AstrMessageEvent, result: ParseResult):
        """单独发送媒体文件。所有图片/封面已在合并转发中，不重复发送。

        qqofficial_full 适配器支持分片上传（>20MB 自动走 chunked upload），
        因此不再在插件层做文件大小限制，交由适配器处理。
        """
        from .core.data import VideoContent, AudioContent

        for cont in result.contents:
            if not isinstance(cont, (VideoContent, AudioContent)):
                continue  # 图片已在合并转发中
            path = await cont.path_task.safe_get()
            if path is None:
                continue

            if isinstance(cont, VideoContent):
                yield event.chain_result([Comp.Video.fromFileSystem(str(path))])
            elif isinstance(cont, AudioContent):
                yield event.chain_result([Comp.Record(file=str(path))])

    async def _build_platform_output(self, event, result, platform: str):
        """构建各平台输出：返回 (标题头, 合并转发节点内容列表)"""
        from .core.data import VideoContent, ImageContent
        platform_name = result.platform.display_name
        content_type = result.extra.get("content_type", "动态")

        if platform == "bilibili":
            header = f"莉卡解析 | {platform_name} - {content_type}"
            # 第一条消息：链接 + 标题 + 封面
            node1_text = "\n".join([v for v in [result.url, result.title] if v])
            node1 = [Comp.Plain(node1_text)] if node1_text else []
            if result.contents:
                from .core.data import VideoContent
                vc = next((c for c in result.contents if isinstance(c, VideoContent)), None)
                if vc and vc.cover:
                    cover_path = await vc.cover.safe_get()
                    if cover_path:
                        node1.append(Comp.Image.fromFileSystem(str(cover_path)))
            # 第二条消息：时长
            node2 = []
            if dur := result.extra.get("duration"):
                node2.append(Comp.Plain(f"⏱ 时长：{dur}"))
            # 第三条消息：统计 + 简介 + 在线
            node3_parts = []
            if stats := result.extra.get("stats_line"):
                node3_parts.append(stats)
            if result.text:
                prefix = "\n" if node3_parts else ""
                node3_parts.append(f"{prefix}📝 简介：{result.text[:200]}")
            if online := result.extra.get("online"):
                prefix = "\n" if node3_parts else ""
                node3_parts.append(f"{prefix}{online}")
            node3 = [Comp.Plain("".join(node3_parts))] if node3_parts else []
            nodes = []
            if node1:
                nodes.append(node1)
            if node2:
                nodes.append(node2)
            if node3:
                nodes.append(node3)
            # 图片内容：来自图文(Opus)解析的 graphics
            for g in result.graphics:
                if isinstance(g, ImageContent):
                    path = await g.path_task.safe_get()
                    if path:
                        nodes.append([Comp.Image.fromFileSystem(str(path))])
                elif isinstance(g, str):
                    nodes.append([Comp.Plain(g)])
            # 图片内容：来自动态解析的 contents
            for c in result.contents:
                if isinstance(c, ImageContent):
                    path = await c.path_task.safe_get()
                    if path:
                        nodes.append([Comp.Image.fromFileSystem(str(path))])
            return header, nodes

        if platform == "xiaohongshu":
            header = f"莉卡解析 | {platform_name} - {'视频' if result.extra.get('is_video') else '图文'}"
            nodes = []
            # 正文文字
            if result.text:
                nodes.append([Comp.Plain(result.text[:300])])
            # 正文中的图片
            for g in result.graphics:
                if isinstance(g, ImageContent):
                    path = await g.path_task.safe_get()
                    if path:
                        nodes.append([Comp.Image.fromFileSystem(str(path))])
                elif isinstance(g, str):
                    nodes.append([Comp.Plain(g)])
            # 内容中的图片
            for c in result.contents:
                if isinstance(c, ImageContent):
                    path = await c.path_task.safe_get()
                    if path:
                        nodes.append([Comp.Image.fromFileSystem(str(path))])
            return header, nodes

        if platform == "douyin":
            from .core.data import VideoContent as _Vc
            is_video = any(isinstance(c, _Vc) for c in result.contents)
            header = f"莉卡解析 | {platform_name} - {'视频' if is_video else '图文'}"
            nodes = []
            text_items = []
            if result.title:
                text_items.append(result.title)
            if result.text:
                tags = " #".join(result.text.split()[:5])
                if tags:
                    text_items.append(f"#{tags}")
            # 简介 + 封面放在同一条消息
            if text_items:
                content = [Comp.Plain("\n".join(text_items))]
                # 尝试加入封面
                if result.contents:
                    from .core.data import VideoContent
                    vc = next((c for c in result.contents if isinstance(c, VideoContent)), None)
                    if vc and vc.cover:
                        cover_path = await vc.cover.safe_get()
                        if cover_path:
                            content.append(Comp.Image.fromFileSystem(str(cover_path)))
                nodes.append(content)
            # 图片内容也放进合并转发
            for c in result.contents:
                if isinstance(c, ImageContent):
                    path = await c.path_task.safe_get()
                    if path:
                        nodes.append([Comp.Image.fromFileSystem(str(path))])
            return header, nodes

        if platform == "kuaishou":
            from .core.data import VideoContent as _Vc
            is_video = any(isinstance(c, _Vc) for c in result.contents)
            header = f"莉卡解析 | {platform_name} - {'视频' if is_video else '图文'}"
            nodes = []
            if result.title:
                nodes.append([Comp.Plain(result.title)])
            if result.text:
                nodes.append([Comp.Plain(result.text[:100])])
            # 图片/封面
            if result.contents:
                from .core.data import VideoContent
                vc = next((c for c in result.contents if isinstance(c, VideoContent)), None)
                if vc and vc.cover:
                    cover_path = await vc.cover.safe_get()
                    if cover_path:
                        nodes.append([Comp.Image.fromFileSystem(str(cover_path))])
            return header, nodes

        # 通用平台
        header = f"莉卡解析 | {platform_name} - {content_type}"
        nodes = []
        if result.title:
            nodes.append([Comp.Plain(result.title)])
        if result.text:
            nodes.append([Comp.Plain(result.text[:150])])
        # 图片放进合并转发
        for c in result.contents:
            if isinstance(c, ImageContent):
                path = await c.path_task.safe_get()
                if path:
                    nodes.append([Comp.Image.fromFileSystem(str(path))])
            elif isinstance(c, VideoContent) and c.cover:
                cover_path = await c.cover.safe_get()
                if cover_path:
                    nodes.append([Comp.Image.fromFileSystem(str(cover_path))])
        return header, nodes

    async def _send_plain_output(
        self,
        event: AstrMessageEvent,
        header: str,
        nodes_content: list[list],
    ):
        """将 header + 所有文本 + 所有图片合并为一条消息链发送。

        适用于不支持 Comp.Nodes（合并转发）的平台，包括 QQ Official Bot、
        Telegram 等。视频由 _try_send_media() 单独处理。
        """
        parts: list = []

        # header 文本
        if header:
            parts.append(Comp.Plain(header + "\n"))

        # 收集所有节点的文本和图片
        text_lines: list[str] = []
        for node_content in nodes_content:
            for comp in node_content:
                if isinstance(comp, Comp.Plain):
                    text_lines.append(comp.text)
                elif isinstance(comp, Comp.Image):
                    parts.append(comp)

        if text_lines:
            parts.append(Comp.Plain("\n".join(text_lines)))

        if parts:
            yield event.chain_result(parts)

    # ==================== B站 Cookie 扫码登录 / 监控 / 自动应用 ====================

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("bili_login")
    async def bili_qr_login(self, event: AstrMessageEvent):
        """B站扫码登录 - 获取二维码图片并轮询扫码结果"""
        sender_id = event.get_sender_id()

        # 检查是否有正在进行的登录
        if sender_id in self._bili_login_tasks and not self._bili_login_tasks[sender_id].done():
            yield event.plain_result("⏳ 你有一个正在进行的扫码登录，请先完成或等待超时")
            return

        try:
            if not self._bili_http_session:
                self._bili_http_session = aiohttp.ClientSession()

            yield event.plain_result("🔄 正在生成B站登录二维码...")

            async with self._bili_http_session.get(
                BILI_QR_GENERATE_URL,
                headers=self._bili_get_headers(),
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                data = await resp.json()

            if data.get("code") != 0:
                yield event.plain_result(f"❌ 获取二维码失败: {data.get('message', '未知错误')}")
                return

            qrcode_url = data["data"]["url"]
            qrcode_key = data["data"]["qrcode_key"]

            if not qrcode_key:
                yield event.plain_result("❌ 获取qrcode_key失败")
                return

            # 生成二维码图片
            qr_image = self._bili_generate_qrcode_image(qrcode_url)
            if not qr_image:
                yield event.plain_result("❌ 二维码生成失败，请检查是否已安装 qrcode 库")
                return

            # 保存并发送二维码图片
            qr_path = self._bili_data_dir / f"qrcode_{sender_id}.png"
            os.makedirs(self._bili_data_dir, exist_ok=True)
            qr_image.save(str(qr_path), "PNG")

            yield event.image_result(str(qr_path))

            yield event.plain_result(
                "📱 请使用 **B站App** 扫描上方二维码登录\n"
                "⏱️ 二维码有效期约3分钟\n"
                "📋 扫码后请在手机上点击「确认登录」"
            )

            logger.info(f"已发送B站登录二维码给用户 {sender_id}，qrcode_key: {qrcode_key[:8]}...")

            # 启动异步轮询
            task = asyncio.create_task(
                self._bili_poll_qr_login(sender_id, qrcode_key, qr_path)
            )
            self._bili_login_tasks[sender_id] = task

        except asyncio.TimeoutError:
            yield event.plain_result("❌ 请求超时，请稍后重试")
        except aiohttp.ClientError as e:
            yield event.plain_result(f"❌ 网络错误: {e}")
        except Exception as e:
            logger.exception("扫码登录出错")
            yield event.plain_result(f"❌ 生成二维码失败: {e}")

    @filter.command("bili_check")
    async def bili_check_cookie(self, event: AstrMessageEvent):
        """手动检测B站Cookie状态"""
        if not self._bili_cookie:
            yield event.plain_result(
                "⚠️ 尚未配置B站Cookie，请使用 /bili_login 扫码登录\n"
                "或在插件配置中填入 BILI_CK"
            )
            return

        if not self._bili_http_session:
            yield event.plain_result("⚠️ 插件正在初始化中，请稍后再试")
            return

        result = await self._bili_check_cookie_valid()

        if result["valid"]:
            msg = f"✅ B站Cookie有效\n用户: {result.get('username', '未知')}\nUID: {result.get('uid', 0)}"
        else:
            msg = f"❌ B站Cookie失效\n错误: {result.get('error', '未知错误')}"

        self._bili_last_status = result
        self._bili_last_check_time = datetime.now()
        await self._bili_save_last_status()

        yield event.plain_result(msg)

    @filter.command("bili_status")
    async def bili_status(self, event: AstrMessageEvent):
        """查看B站Cookie状态"""
        lines = [
            f"Cookie状态: {'已配置' if self._bili_cookie else '未配置'}",
            f"监控状态: {'运行中' if self._bili_monitor_running else '已停止'}",
        ]
        if self._bili_last_status:
            status = "有效" if self._bili_last_status.get("valid") else "失效"
            lines.append(f"上次检测: {status}")
            if self._bili_last_check_time:
                lines.append(f"检测时间: {self._bili_last_check_time.strftime('%Y-%m-%d %H:%M:%S')}")
        yield event.plain_result("\n".join(lines))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("rika_clear_cache", alias={"clear_cache", "清理缓存"})
    async def rika_clear_cache(self, event: AstrMessageEvent):
        """手动清理插件缓存。"""
        try:
            cleaned = await clear_cache_dir(self.cache_dir)
            self._result_cache.clear()
            self._render_cache.clear()
            yield event.plain_result(f"✅ 莉卡解析缓存清理完成，共清理 {cleaned} 个文件")
        except Exception as exc:
            logger.exception("手动清理莉卡解析缓存失败")
            yield event.plain_result(f"❌ 缓存清理失败: {exc}")

    # ---------- 内部方法 ----------

    @staticmethod
    def _bili_get_headers() -> dict:
        """获取B站API请求头"""
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com/",
            "Accept": "application/json, text/plain, */*",
        }

    @staticmethod
    def _bili_generate_qrcode_image(url: str):
        """生成二维码图片"""
        try:
            qr = qrcode.QRCode(
                version=None,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=10,
                border=4,
            )
            qr.add_data(url)
            qr.make(fit=True)
            return qr.make_image(fill_color="black", back_color="white")
        except Exception as e:
            logger.error(f"生成二维码失败: {e}")
            return None

    async def _bili_poll_qr_login(self, sender_id: str, qrcode_key: str, qr_path: Path):
        """异步轮询扫码状态"""
        try:
            start_time = datetime.now()
            last_notified_status = None

            while True:
                elapsed = (datetime.now() - start_time).total_seconds()

                if elapsed >= QR_CODE_EXPIRE_TIME:
                    logger.info(f"用户 {sender_id} 的二维码已过期")
                    await self._bili_notify_user(sender_id, "⏱️ 二维码已过期\n请重新发送 /bili_login 获取新二维码")
                    break

                if not self._bili_http_session or self._bili_http_session.closed:
                    break

                try:
                    async with self._bili_http_session.get(
                        BILI_QR_POLL_URL,
                        params={"qrcode_key": qrcode_key},
                        headers=self._bili_get_headers(),
                        timeout=aiohttp.ClientTimeout(total=15)
                    ) as resp:
                        poll_data = await resp.json()
                        set_cookie_headers = resp.headers.getall("Set-Cookie", [])
                except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                    logger.warning(f"轮询扫码状态失败: {e}")
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                code = poll_data.get("data", {}).get("code", -1)

                if code == QR_CODE_UNSCANNED:
                    pass

                elif code == QR_CODE_SCANNED:
                    if last_notified_status != QR_CODE_SCANNED:
                        await self._bili_notify_user(sender_id, "✅ 已扫码\n请在手机上点击「确认登录」完成授权")
                        last_notified_status = QR_CODE_SCANNED

                elif code == QR_CODE_EXPIRED:
                    await self._bili_notify_user(sender_id, "⏱️ 二维码已过期\n请重新发送 /bili_login 获取新二维码")
                    break

                elif code == QR_CODE_SUCCESS:
                    logger.info(f"用户 {sender_id} 扫码登录成功")

                    # 从Set-Cookie头提取cookie
                    cookie_dict = {}
                    for header in set_cookie_headers:
                        cookie_part = header.split(";")[0].strip()
                        if "=" in cookie_part:
                            name, value = cookie_part.split("=", 1)
                            cookie_dict[name.strip()] = value.strip()

                    if not cookie_dict:
                        await self._bili_notify_user(sender_id, "❌ 登录成功但未获取到Cookie，请重试")
                        break

                    cookie_str = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())

                    # 更新状态
                    async with self._bili_cookie_lock:
                        self._bili_cookie = cookie_str

                    # 持久化保存
                    await self._bili_save_cookie(cookie_str)

                    # 立即应用到BilibiliParser
                    self._bili_apply_cookie_to_parser(cookie_str)

                    # 如果监控未启动，启动监控
                    if not self._bili_monitor_running:
                        self._bili_start_monitor()

                    # 验证cookie
                    result = await self._bili_check_cookie_valid()
                    self._bili_last_status = result
                    self._bili_last_check_time = datetime.now()
                    await self._bili_save_last_status()

                    if result["valid"]:
                        await self._bili_notify_user(
                            sender_id,
                            f"🎉 登录成功，B站Cookie已生效并自动应用！\n"
                            f"👤 用户: {result.get('username', '未知')}\n"
                            f"🆔 UID: {result.get('uid', 0)}\n"
                            f"{'👑 大会员' if result.get('vip') else '🐟 普通用户'}\n"
                            f"{'🚀 监控已自动启动' if self._bili_monitor_running else '⚠️ 监控未运行'}"
                        )
                        self._bili_was_invalid = False
                    else:
                        await self._bili_notify_user(
                            sender_id,
                            f"⚠️ Cookie已保存但验证失败: {result.get('error')}"
                        )
                    break

                else:
                    logger.warning(f"未知扫码状态码: {code}")

                await asyncio.sleep(POLL_INTERVAL)

        except asyncio.CancelledError:
            logger.info(f"用户 {sender_id} 的扫码轮询被取消")
        except Exception:
            logger.exception(f"扫码轮询出错 (用户: {sender_id})")
        finally:
            if sender_id in self._bili_login_tasks:
                del self._bili_login_tasks[sender_id]
            if qr_path.exists():
                try:
                    qr_path.unlink()
                except Exception:
                    pass

    def _bili_apply_cookie_to_parser(self, cookie_str: str):
        """将Cookie立即应用到BilibiliParser"""
        parser = self.parsers.get("bilibili")
        if parser and hasattr(parser, "update_cookie"):
            parser.update_cookie(cookie_str)
            logger.info("B站Cookie已自动应用到BilibiliParser")
        else:
            logger.warning("BilibiliParser 不可用，无法应用Cookie")

    async def _bili_check_cookie_valid(self) -> dict:
        """检测B站Cookie是否有效"""
        if not self._bili_cookie:
            return {"valid": False, "error": "Cookie为空"}
        if not self._bili_http_session:
            return {"valid": False, "error": "HTTP会话未初始化"}

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Cookie": self._bili_cookie,
            "Referer": "https://www.bilibili.com/"
        }

        try:
            async with self._bili_http_session.get(
                "https://api.bilibili.com/x/web-interface/nav",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                data = await resp.json()

                if data.get("code") == 0 and data.get("data", {}).get("isLogin"):
                    # Cookie有效时从响应头刷新
                    set_cookie_headers = resp.headers.getall("Set-Cookie", [])
                    if set_cookie_headers:
                        await self._bili_refresh_cookie_from_headers(set_cookie_headers)

                    u = data["data"]
                    return {
                        "valid": True,
                        "username": u.get("uname", ""),
                        "uid": u.get("mid", 0),
                        "vip": u.get("vipStatus") == 1
                    }
                error_msg = data.get("message", "未知错误")
                code = data.get("code")
                if code == -101:
                    error_msg = "账号未登录或Cookie已过期"
                elif code == -352:
                    error_msg = "请求被风控"
                return {"valid": False, "error": error_msg, "code": code}

        except asyncio.TimeoutError:
            return {"valid": False, "error": "请求超时"}
        except aiohttp.ClientError as e:
            return {"valid": False, "error": f"网络错误: {e}"}
        except Exception as e:
            return {"valid": False, "error": f"未知错误: {e}"}

    async def _bili_refresh_cookie_from_headers(self, set_cookie_headers: list) -> bool:
        """从Set-Cookie响应头中刷新Cookie"""
        if not set_cookie_headers:
            return False

        new_cookies = {}
        for header in set_cookie_headers:
            cookie_part = header.split(";")[0].strip()
            if "=" in cookie_part:
                name, value = cookie_part.split("=", 1)
                name = name.strip()
                value = value.strip()
                if value:
                    new_cookies[name] = value

        if not new_cookies:
            return False

        async with self._bili_cookie_lock:
            existing = {}
            for part in self._bili_cookie.split(";"):
                part = part.strip()
                if "=" in part:
                    k, v = part.split("=", 1)
                    existing[k.strip()] = v.strip()

            merged = {**existing, **new_cookies}
            new_cookie_str = "; ".join(f"{k}={v}" for k, v in merged.items())

            if new_cookie_str != self._bili_cookie:
                self._bili_cookie = new_cookie_str
                await self._bili_save_cookie(new_cookie_str)
                self._bili_apply_cookie_to_parser(new_cookie_str)
                logger.info(f"B站Cookie已自动刷新，更新了 {len(new_cookies)} 个字段")
                return True

        return False

    def _bili_start_monitor(self):
        """启动Cookie监控循环"""
        if self._bili_monitor_task and not self._bili_monitor_task.done():
            return
        self._bili_monitor_running = True
        self._bili_monitor_task = asyncio.create_task(self._bili_monitor_loop())
        pconfig = get_config()
        logger.info(f"B站Cookie监控已启动，检测间隔: {pconfig.BILI_COOKIE_CHECK_INTERVAL}秒")

    async def _bili_monitor_loop(self):
        """Cookie监控循环 - 只在状态翻转时通知一次"""
        pconfig = get_config()
        while self._bili_monitor_running:
            try:
                result = await self._bili_check_cookie_valid()
                self._bili_last_status = result
                self._bili_last_check_time = datetime.now()
                await self._bili_save_last_status()

                is_valid = result["valid"]
                if is_valid:
                    if self._bili_was_invalid:
                        # 从失效→恢复，发一次通知
                        await self._bili_notify_admin("✅ B站Cookie已恢复", f"用户: {result.get('username')}")
                        self._bili_was_invalid = False
                else:
                    if not self._bili_was_invalid:
                        # 从有效→失效，发一次通知
                        await self._bili_notify_admin("❌ B站Cookie已失效", f"错误: {result.get('error')}")
                        self._bili_was_invalid = True
                    logger.warning(f"B站Cookie仍处于失效状态: {result.get('error')}")

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("B站Cookie监控出错")

            if self._bili_monitor_running:
                await asyncio.sleep(pconfig.BILI_COOKIE_CHECK_INTERVAL)

    async def _bili_notify_user(self, sender_id: str, message: str):
        """向指定用户发送消息"""
        try:
            umo = sender_id if ":" in sender_id else f"default:FriendMessage:{sender_id}"
            await self.context.send_message(umo, MessageChain().message(message))
        except Exception as e:
            logger.error(f"发送消息给 {sender_id} 失败: {e}")

    async def _bili_notify_admin(self, title: str, message: str):
        """向配置的通知目标QQ号发送Cookie状态通知（只发一次，不重复）"""
        pconfig = get_config()
        user_id = pconfig.BILI_NOTIFY_USER_ID
        if not user_id:
            logger.info(f"[B站Cookie监控] {title}: {message} (未配置通知目标，仅记录日志)")
            return
        try:
            umo = user_id if ":" in user_id else f"default:FriendMessage:{user_id}"
            await self.context.send_message(umo, MessageChain().message(f"{title}\n{message}"))
            logger.info(f"已发送B站Cookie通知到 {user_id}: {title}")
        except Exception as e:
            logger.error(f"发送B站Cookie通知失败: {e}")

    # ==================== 持久化 ====================

    async def _bili_load_last_status(self):
        """加载上次Cookie检测状态"""
        async with self._bili_file_lock:
            try:
                if self._bili_status_file.exists():
                    with open(self._bili_status_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self._bili_last_status = data.get("last_status")
                    self._bili_was_invalid = data.get("was_invalid", False)
                    if data.get("last_check_time"):
                        self._bili_last_check_time = datetime.fromisoformat(data["last_check_time"])
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.error(f"加载B站Cookie状态失败: {e}")

    async def _bili_save_last_status(self):
        """保存当前Cookie检测状态"""
        async with self._bili_file_lock:
            try:
                os.makedirs(self._bili_data_dir, exist_ok=True)
                data = {
                    "last_status": self._bili_last_status,
                    "last_check_time": self._bili_last_check_time.isoformat() if self._bili_last_check_time else None,
                    "was_invalid": self._bili_was_invalid,
                }
                with open(self._bili_status_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except (IOError, OSError) as e:
                logger.error(f"保存B站Cookie状态失败: {e}")

    async def _bili_load_cookie(self):
        """从持久化存储中加载Cookie（优先），其次从配置加载"""
        # 先尝试从持久化文件加载
        try:
            config_path = self._bili_data_dir / "bili_cookie_encrypted.json"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
                saved = config_data.get("cookie", "")
                if saved:
                    decrypted = self._bili_decrypt_cookie(saved)
                    if decrypted:
                        self._bili_cookie = decrypted
                        logger.info("已从持久化存储加载B站Cookie")
                        return
                    logger.warning("B站Cookie解密失败")
        except (IOError, OSError, json.JSONDecodeError) as e:
            logger.error(f"加载持久化Cookie失败: {e}")

        # 再从配置加载
        pconfig = get_config()
        if pconfig.BILI_CK:
            self._bili_cookie = pconfig.BILI_CK
            logger.info("已从插件配置加载B站Cookie")

    async def _bili_save_cookie(self, cookie_str: str):
        """加密持久化保存Cookie"""
        if not cookie_str:
            return
        try:
            config_path = self._bili_data_dir / "bili_cookie_encrypted.json"
            config_data = {}
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
            config_data["cookie"] = self._bili_encrypt_cookie(cookie_str)
            config_data["timestamp"] = datetime.now().isoformat()
            os.makedirs(self._bili_data_dir, exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
            logger.info("B站Cookie已加密保存")
        except (IOError, OSError, json.JSONDecodeError) as e:
            logger.error(f"保存B站Cookie失败: {e}")

    def _bili_get_fernet(self) -> Fernet:
        """获取或生成加密密钥"""
        os.makedirs(self._bili_data_dir, exist_ok=True)
        if self._bili_key_file.exists():
            key = self._bili_key_file.read_bytes()
            return Fernet(key)
        key = Fernet.generate_key()
        self._bili_key_file.write_bytes(key)
        try:
            os.chmod(str(self._bili_key_file), 0o600)
        except (OSError, NotImplementedError):
            pass
        return Fernet(key)

    def _bili_encrypt_cookie(self, cookie_str: str) -> str:
        """加密Cookie字符串"""
        if not cookie_str:
            return ""
        fernet = self._bili_get_fernet()
        return fernet.encrypt(cookie_str.encode("utf-8")).decode("utf-8")

    def _bili_decrypt_cookie(self, encrypted: str) -> str:
        """解密Cookie字符串"""
        if not encrypted:
            return ""
        try:
            fernet = self._bili_get_fernet()
            return fernet.decrypt(encrypted.encode("utf-8")).decode("utf-8")
        except Exception:
            logger.error("B站Cookie解密失败，密钥可能已变更，请重新扫码登录")
            return ""

    def _format_generic(self, result) -> tuple[str, bool]:
        lines = [f"莉卡解析 | {result.platform.display_name}"]
        if result.title:
            lines.append(f"- {result.title}")
        text = " ".join(lines)
        if result.text:
            text += f"\n{result.text[:150]}"
        return text, False

    # ==================== JSON 工具方法 ====================

    @staticmethod
    def _has_json_component(event: AstrMessageEvent) -> bool:
        if not hasattr(event, "message_obj") or not hasattr(event.message_obj, "message"):
            return False
        for c in event.message_obj.message:
            if isinstance(c, dict):
                t = c.get("type")
                if t == "reply":
                    continue
                if t and "json" in str(t).lower():
                    return True
                continue
            if isinstance(c, Comp.Json):
                return True
            t = getattr(c, "type", None)
            if t and "json" in str(t).lower():
                return True
        return False

    @staticmethod
    def _extract_links_from_text(text: str) -> list[str]:
        if not text:
            return []
        return re.findall(r"https?://[^\s'\"<>]+", text)

    def _extract_links_from_event(self, event: AstrMessageEvent) -> list[str]:
        links = []
        if hasattr(event, "message_obj") and hasattr(event.message_obj, "message"):
            for c in event.message_obj.message:
                if isinstance(c, dict):
                    t = c.get("type")
                    if t == "reply":
                        continue
                    if t and "json" in str(t).lower():
                        links.extend(self._extract_links_from_json(c.get("data", c)))
                    continue
                if isinstance(c, Comp.Json):
                    links.extend(self._extract_links_from_json(c.data))
                elif isinstance(c, Comp.Plain):
                    links.extend(self._extract_links_from_text(c.text))
        links.extend(self._extract_links_from_text(event.message_str))
        return links

    def _extract_links_from_json(self, data) -> list[str]:
        links = []
        try:
            import json
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    return links

            def search(obj):
                found = []
                if isinstance(obj, dict):
                    for v in obj.values():
                        if isinstance(v, str) and (v.startswith("http://") or v.startswith("https://")):
                            found.append(v)
                        elif isinstance(v, (dict, list)):
                            found.extend(search(v))
                    meta = obj.get("meta", {})
                    if isinstance(meta, dict):
                        for dk in ("detail_1", "detail", "news", "music"):
                            d = meta.get(dk, {})
                            if isinstance(d, dict):
                                for uk in ("qqdocurl", "url", "jumpUrl"):
                                    v = d.get(uk, "")
                                    if isinstance(v, str) and v:
                                        found.append(v)
                elif isinstance(obj, list):
                    for item in obj:
                        if isinstance(item, (dict, list)):
                            found.extend(search(item))
                return found
            links.extend(search(data))
        except Exception as e:
            logger.warning(f"解析 JSON 消息组件失败: {e}")
        return links

    async def terminate(self):
        if self._cache_cleanup_task is not None and not self._cache_cleanup_task.done():
            self._cache_cleanup_task.cancel()
            try:
                await self._cache_cleanup_task
            except asyncio.CancelledError:
                pass
            self._cache_cleanup_task = None
        await self.downloader.aclose()

        # ========== 清理B站监控 ==========
        self._bili_monitor_running = False

        # 取消扫码登录任务
        for uid, task in list(self._bili_login_tasks.items()):
            if not task.done():
                task.cancel()
        self._bili_login_tasks.clear()

        if self._bili_monitor_task and not self._bili_monitor_task.done():
            self._bili_monitor_task.cancel()
            try:
                await self._bili_monitor_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("终止B站监控任务时发生异常")

        if self._bili_http_session and not self._bili_http_session.closed:
            await self._bili_http_session.close()
            logger.debug("B站 HTTP 会话已关闭")
