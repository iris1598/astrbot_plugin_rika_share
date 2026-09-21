"""莉卡解析 - 链接分享解析插件

支持 B站 | 抖音 | 快手 | 微博 | 小红书 | Twitter | AcFun | NGA

移植自 nonebot-plugin-parser (https://github.com/fllesser/nonebot-plugin-parser)
内置B站扫码登录、Cookie监控、自动应用Cookie功能

本文件只承载 AstrBot 要求的插件类与事件处理器（Handler 必须定义在插件模块内才能被
框架注册）。具体实现按职责分层放在 ``link_parser`` 包中：

    link_parser/adapters   平台解析适配器（自注册，新增平台无需改动本文件的事件注册）
    link_parser/models     数据类型
    link_parser/services   下载 / 渲染 / 截图 / 实况照片 / B站账号
    link_parser/output     解析结果到消息链的输出构建
    link_parser/utils      通用工具
"""

import asyncio
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator

from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult, MessageChain
import astrbot.api.message_components as Comp
from astrbot.api.star import Context, Star, register, StarTools

from .link_parser.adapters import get_adapter, iter_adapters
from .link_parser.adapters.registry import AdapterBuildContext
from .link_parser.config import get_config, init_config, migrate_grouped_config
from .link_parser.constants import GENERIC_URL_PATTERN
from .link_parser.exceptions import (
    DownloadException,
    IgnoreException,
    ParseException,
    SilentException,
)
from .link_parser.models import ParseResult, VideoContent
from .link_parser.output import (
    EventUrlWrapper,
    build_platform_output,
    error_result,
    extract_links_from_event,
    has_json_component,
    send_nodes_batched,
    send_plain_output,
    try_send_media,
)
from .link_parser.services.bilibili_account import BiliAccountService
from .link_parser.services.card_render import ShareCardRenderer
from .link_parser.services.downloader import StreamDownloader
from .link_parser.services.web_screenshot import (
    CloudflareScreenshotClient,
    fetch_page_title,
    is_url_blacklisted,
)
from .link_parser.utils import clear_cache_dir, cleanup_cache_dir
from .link_parser.webui import WebUIApi, read_schema_problems


def _get_plugin_data_dir() -> Path:
    from astrbot.core.utils.astrbot_path import get_astrbot_data_path

    return Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_rika_share"


def _pattern(name: str) -> str:
    """取适配器注册的 URL 触发正则。

    新增平台时只需在 ``link_parser/adapters`` 中注册，此处无需改动。
    """
    spec = get_adapter(name)
    return spec.url_pattern.pattern if spec else r"(?!)"


#: 「原始链接 → 内容标识」记忆上限，超过则整体清空（避免长跑无限累积）
_IDENTITY_MEMO_MAX = 2048


@dataclass
class _ContentCacheEntry:
    """一条内容缓存：解析结果 + 解析时刻 + 卡片文件。

    以「内容标识」（见 ``BaseParser.cache_identity``）为键，因此同一内容的不同
    短链 / 长链共用一条。``parsed_at`` 用于按适配器声明的 ``CACHE_TTL_SECONDS``
    判断是否过期——B站这类带实时数据的平台超时后会重新解析。
    """

    result: ParseResult
    parsed_at: float
    render_path: Path | None = None
    #: 重新解析的次数：>0 时卡片文件名会带上代次，避免复用（或覆盖）上一代卡片
    generation: int = 0

    def expired(self, ttl: int | None, now: float | None = None) -> bool:
        """``ttl`` 为 ``None`` 表示不设有效期。"""
        if ttl is None:
            return False
        return (now if now is not None else time.monotonic()) - self.parsed_at > ttl


@register("链接解析器", "fllesser (ported to AstrBot)",
          "链接分享自动解析插件，支持 B站|抖音|快手|微博|小红书|Twitter|AcFun|NGA", "v3.0.0")
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
                    f"[link_parser] 检测到 OneBot 平台: {platform_name}，使用合并转发"
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
        # 内容标识 → 解析结果缓存（含卡片路径、解析时刻与代次）
        self._content_cache: dict[str, _ContentCacheEntry] = {}
        # 原始链接 → 内容标识（含短链跳转结果），避免重复解析/跳转
        self._identity_cache: dict[str, str] = {}
        self._cache_cleanup_task: asyncio.Task | None = None

        # ========== 解析图片渲染 ==========
        self._renderer = self._build_renderer()
        # 构造参数快照：网页保存配置后据此判断要不要重建渲染器
        self._renderer_sig = self._renderer_signature()
        if self._renderer.enabled:
            logger.info(
                f"解析图片渲染已启用 (主题: {pconfig.RENDER_THEME}, "
                f"布局: {pconfig.RENDER_LAYOUT}, "
                f"封面全尺寸: {pconfig.RENDER_COVER_FULL_SIZE}, "
                f"宽度: {pconfig.RENDER_WIDTH}px)"
            )
        else:
            logger.info("解析图片渲染已关闭，使用文本输出")

        # ========== B站 Cookie 监控 / 扫码登录 ==========
        self.bili = BiliAccountService(
            context,
            StarTools.get_data_dir("astrbot_plugin_rika_share"),
            self.parsers,
        )

        # ========== Cloudflare 截图 Fallback ==========
        self._cloudflare_client: CloudflareScreenshotClient | None = None
        self._cloudflare_sig = self._cloudflare_signature()
        if pconfig.CLOUDFLARE_FALLBACK_ENABLED:
            self._cloudflare_client = CloudflareScreenshotClient(config)
            if self._cloudflare_client.is_configured:
                logger.info("Cloudflare 网页截图 Fallback 已启用")
            else:
                logger.warning(
                    "Cloudflare 截图 Fallback 已开启但未配置 Account ID / API Token，"
                    "请检查插件配置"
                )

        self._register_webui()

    # ==================== 网页设置页 ==================== #

    def _register_webui(self) -> None:
        """注册插件网页设置页（``pages/rika``）的后端接口。

        老版本 AstrBot 没有 ``register_web_api``，此时静默跳过——
        聊天命令与解析功能都不受影响，只是没有网页设置页。
        """
        # 自检：_conf_schema.json 与 CONFIG_META 不一致会让保存的值在重载时丢失；
        # 分组可见性不一致会在原生面板留下空标题（两者都由 read_schema_problems 逐条打日志）
        read_schema_problems()

        if not hasattr(self.context, "register_web_api"):
            logger.info("[link_parser] 当前 AstrBot 不支持插件页面，跳过 WebUI 注册")
            return
        try:
            self._webui = WebUIApi(self)
            self._webui.register()
            logger.info("[link_parser] WebUI 接口已注册（插件页面 pages/rika）")
        except Exception:
            logger.warning("[link_parser] WebUI 接口注册失败，网页设置页不可用", exc_info=True)

    async def apply_runtime_config(self) -> dict[str, Any]:
        """把刚保存的配置应用到运行中的组件，避免用户还要重载插件。

        ``self.parsers`` 用原地更新的方式重建：B站账号服务持有的是同一个 dict 引用，
        换成新 dict 会让它继续操作已经被丢弃的解析器。
        """
        result: dict[str, Any] = {}

        if self._renderer_signature() != self._renderer_sig:
            self._renderer = self._build_renderer()
            self._renderer_sig = self._renderer_signature()
            result["renderer"] = self._renderer.enabled

        pconfig = get_config()
        disabled = pconfig.DISABLED_PLATFORMS
        if disabled != self.disabled_platforms:
            self.disabled_platforms = disabled
            self.parsers.clear()
            self._init_parsers()
            result["platforms"] = sorted(self.parsers)

        if self._cloudflare_signature() != self._cloudflare_sig:
            self._cloudflare_sig = self._cloudflare_signature()
            self._cloudflare_client = (
                CloudflareScreenshotClient(self.config)
                if self._cloudflare_sig is not None
                else None
            )
            result["cloudflare"] = bool(
                self._cloudflare_client and self._cloudflare_client.is_configured
            )

        return result

    def _cloudflare_signature(self) -> tuple | None:
        """Cloudflare 截图客户端的构造参数快照（``None`` 表示未启用）。"""
        pconfig = get_config()
        if not pconfig.CLOUDFLARE_FALLBACK_ENABLED:
            return None
        return (
            pconfig.CLOUDFLARE_ACCOUNT_ID,
            pconfig.CLOUDFLARE_API_TOKEN,
            pconfig.CLOUDFLARE_TIMEOUT,
            pconfig.CLOUDFLARE_VIEWPORT_WIDTH,
            pconfig.CLOUDFLARE_VIEWPORT_HEIGHT,
            pconfig.CLOUDFLARE_WAIT_UNTIL,
            pconfig.CLOUDFLARE_GOTO_TIMEOUT,
            pconfig.CLOUDFLARE_FULL_PAGE,
            pconfig.CLOUDFLARE_DEVICE_SCALE_FACTOR,
            pconfig.CLOUDFLARE_SCREENSHOT_TYPE,
            pconfig.CLOUDFLARE_SCREENSHOT_QUALITY,
            pconfig.CLOUDFLARE_OMIT_BACKGROUND,
            pconfig.CLOUDFLARE_SELECTOR,
            pconfig.CLOUDFLARE_WAIT_FOR_SELECTOR,
            pconfig.CLOUDFLARE_WAIT_FOR_TIMEOUT,
            pconfig.CLOUDFLARE_USER_AGENT,
            pconfig.CLOUDFLARE_EXTRA_HEADERS,
            pconfig.CLOUDFLARE_COOKIES,
            pconfig.CLOUDFLARE_CACHE_TTL,
        )

    def _build_renderer(self) -> ShareCardRenderer:
        """按当前配置构造卡片渲染器。"""
        pconfig = get_config()
        return ShareCardRenderer(
            self.cache_dir,
            enabled=pconfig.RENDER_ENABLED,
            width=pconfig.RENDER_WIDTH,
            theme=pconfig.RENDER_THEME,
            font_path=pconfig.RENDER_FONT_PATH or None,
            layout=pconfig.RENDER_LAYOUT,
            cover_full_size=pconfig.RENDER_COVER_FULL_SIZE,
        )

    def _renderer_signature(self) -> tuple:
        """渲染器的构造参数快照，用于判断保存配置后是否需要重建。"""
        pconfig = get_config()
        return (
            pconfig.RENDER_ENABLED,
            pconfig.RENDER_WIDTH,
            pconfig.RENDER_THEME,
            pconfig.RENDER_FONT_PATH,
            pconfig.RENDER_LAYOUT,
            pconfig.RENDER_COVER_FULL_SIZE,
        )

    def _init_parsers(self) -> None:
        """按适配器注册表实例化已启用的平台解析器。"""
        build_context = AdapterBuildContext(
            downloader=self.downloader,
            config=get_config(),
            config_dir=self.config_dir,
        )
        for spec in iter_adapters():
            if spec.name in self.disabled_platforms:
                continue
            self.parsers[spec.name] = spec.create(build_context)
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
                        # 文件清理后同步清空内存缓存（解析结果 + 卡片路径 + 内容标识）
                        self._content_cache.clear()
                        self._identity_cache.clear()
                        await asyncio.sleep(interval)
                except asyncio.CancelledError:
                    logger.info("缓存清理任务已停止")
                    raise

            self._cache_cleanup_task = asyncio.create_task(_cache_cleanup_loop())
        else:
            logger.info("缓存自动清理已禁用 (CACHE_TTL_HOURS=0)")

        # ========== B站 Cookie 初始化 ==========
        await self.bili.initialize()

    # ==================== 平台处理器 ====================

    async def _dispatch(
        self, event: AstrMessageEvent, name: str
    ) -> AsyncGenerator[MessageEventResult, None]:
        if has_json_component(event):
            return
        parser = self.parsers.get(name)
        if not parser:
            return
        async for r in self._process_url(event, parser):
            yield r

    @filter.regex(_pattern("bilibili"))
    async def bilibili_handler(self, event: AstrMessageEvent, matched: re.Match | None = None):
        async for r in self._dispatch(event, "bilibili"):
            yield r

    @filter.regex(_pattern("douyin"))
    async def douyin_handler(self, event: AstrMessageEvent, matched: re.Match | None = None):
        async for r in self._dispatch(event, "douyin"):
            yield r

    @filter.regex(_pattern("kuaishou"))
    async def kuaishou_handler(self, event: AstrMessageEvent, matched: re.Match | None = None):
        async for r in self._dispatch(event, "kuaishou"):
            yield r

    @filter.regex(_pattern("weibo"))
    async def weibo_handler(self, event: AstrMessageEvent, matched: re.Match | None = None):
        async for r in self._dispatch(event, "weibo"):
            yield r

    @filter.regex(_pattern("xiaohongshu"))
    async def xiaohongshu_handler(self, event: AstrMessageEvent, matched: re.Match | None = None):
        async for r in self._dispatch(event, "xiaohongshu"):
            yield r

    @filter.regex(_pattern("twitter"))
    async def twitter_handler(self, event: AstrMessageEvent, matched: re.Match | None = None):
        async for r in self._dispatch(event, "twitter"):
            yield r

    @filter.regex(_pattern("nga"))
    async def nga_handler(self, event: AstrMessageEvent, matched: re.Match | None = None):
        async for r in self._dispatch(event, "nga"):
            yield r

    @filter.regex(_pattern("acfun"))
    async def acfun_handler(self, event: AstrMessageEvent, matched: re.Match | None = None):
        async for r in self._dispatch(event, "acfun"):
            yield r

    # ==================== JSON 卡片处理器 ====================

    @filter.regex(r".*")
    async def json_card_handler(self, event: AstrMessageEvent, matched: re.Match | None = None):
        if not has_json_component(event):
            return
        links = extract_links_from_event(event)
        if not links:
            return
        unique_links = list(dict.fromkeys(links))
        for link in unique_links:
            for _, parser in self.parsers.items():
                try:
                    _, _ = parser.search_url(link)
                    wrapped = EventUrlWrapper(event, link)
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
        if has_json_component(event):
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

    async def _content_cache_key(self, parser: Any, text: str) -> str:
        """取解析结果的缓存键。

        由适配器把链接归一为内容标识（见 ``BaseParser.cache_identity``）：
        同一内容的不同短链 / 长链会得到同一标识，从而共用一条缓存；
        结果按原始文本记忆，避免同一条链接重复做短链跳转。
        """
        cached = self._identity_cache.get(text)
        if cached is not None:
            return cached

        try:
            identity = await parser.cache_identity(text)
        except Exception:
            # cache_identity 设计上不抛异常，这里只做兜底，避免缓存键问题影响解析主流程
            logger.warning("解析内容标识失败，回退按链接缓存", exc_info=True)
            identity = parser.url_fallback_identity(text)

        if len(self._identity_cache) >= _IDENTITY_MEMO_MAX:
            self._identity_cache.clear()
        self._identity_cache[text] = identity
        return identity

    async def _process_url(
        self, event: AstrMessageEvent, parser: Any
    ) -> AsyncGenerator[MessageEventResult, None]:
        url = event.message_str.strip()

        try:
            # 缓存键 = 内容标识：不同短链 / 长链指向同一内容时命中同一条缓存
            cache_key = await self._content_cache_key(parser, url)
            entry = self._content_cache.get(cache_key)

            # 结果缓存过期：内容带实时数据（如 B站在线人数），不能继续复用旧结果
            if entry is not None and entry.expired(parser.CACHE_TTL_SECONDS):
                logger.info(
                    f"解析缓存已过期（>{parser.CACHE_TTL_SECONDS}s），重新解析以刷新实时数据: "
                    f"{entry.result.platform.display_name} [{cache_key}]"
                )
                entry = None

            if entry is None:
                # 若上一代结果仍在（过期场景），代次 +1 让新卡片另存文件，
                # 避免覆盖可能正在被发送的旧卡片
                previous = self._content_cache.pop(cache_key, None)
                generation = previous.generation + 1 if previous else 0
                keyword, searched = parser.search_url(url)
                result = await parser.parse(keyword, searched)
                entry = _ContentCacheEntry(
                    result=result, parsed_at=time.monotonic(), generation=generation
                )
                self._content_cache[cache_key] = entry
            else:
                # 命中缓存只在日志里提示，不向对话发送消息
                age = time.monotonic() - entry.parsed_at
                logger.info(
                    f"命中解析缓存（{age:.0f}s 前解析），跳过重复解析: "
                    f"{entry.result.platform.display_name} [{cache_key}] {url[:80]}"
                )
                result = entry.result

            # 根据平台构建：标题头 + 合并转发内容列表
            header, nodes_content = await build_platform_output(
                result, result.platform.name
            )

            # 渲染精美解析卡片（失败时 render_path 为 None，自动回退文本输出）
            render_path: Path | None = None
            if self._renderer is not None and self._renderer.enabled:
                render_path = await self._renderer.render(
                    result,
                    cache_key=cache_key,
                    existing=entry.render_path,
                    # 代次 >0 表示内容被重新解析过，卡片文件名要跟着换代
                    salt=str(entry.generation) if entry.generation else None,
                )
                if render_path is not None:
                    entry.render_path = render_path

            warnings = result.extra.get("limit_warnings") or []
            is_video = any(
                isinstance(c, VideoContent) and not c.is_image_like
                for c in result.contents
            )

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
                    async for r in send_nodes_batched(event, header_text, text_items):
                        yield r
                else:
                    # 其他平台（QQ Official / Telegram 等）：拆分为独立消息
                    async for r in send_plain_output(event, header_text, text_items):
                        yield r

            # 单独发送媒体文件（Video / Audio）
            # 注意：图片已在 Nodes（OneBot）或 send_plain_output（其他平台）中处理
            async for r in try_send_media(event, result):
                yield r

        except SilentException:
            return  # 匹配不到模式时静默失败，不发送通知
        except IgnoreException as e:
            result = error_result(event, f"ℹ️ {e.message}")
            if result is not None:
                yield result
        except ParseException as e:
            result = error_result(event, f"❌ 解析失败: {e.message}")
            if result is not None:
                yield result
        except DownloadException as e:
            result = error_result(event, f"⚠️ 下载失败: {e.message}")
            if result is not None:
                yield result
        except Exception as e:
            logger.exception("解析异常")
            result = error_result(event, f"❌ 处理出错: {str(e)[:100]}")
            if result is not None:
                yield result

    # ==================== B站 Cookie 指令 ====================

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("bili_login")
    async def bili_qr_login(self, event: AstrMessageEvent):
        """B站扫码登录 - 获取二维码图片并轮询扫码结果"""
        async for r in self.bili.login(event):
            yield r

    @filter.command("bili_check")
    async def bili_check_cookie(self, event: AstrMessageEvent):
        """手动检测B站Cookie状态"""
        async for r in self.bili.check(event):
            yield r

    @filter.command("bili_status")
    async def bili_status(self, event: AstrMessageEvent):
        """查看B站Cookie状态"""
        yield event.plain_result(self.bili.status_text())

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("clear_cache", alias={"清理缓存"})
    async def clear_cache(self, event: AstrMessageEvent):
        """手动清理插件缓存。"""
        try:
            cleaned = await clear_cache_dir(self.cache_dir)
            self._content_cache.clear()
            self._identity_cache.clear()
            yield event.plain_result(f"✅ 莉卡解析缓存清理完成，共清理 {cleaned} 个文件")
        except Exception as exc:
            logger.exception("手动清理莉卡解析缓存失败")
            result = error_result(event, f"❌ 缓存清理失败: {exc}")
            if result is not None:
                yield result

    async def terminate(self):
        if self._cache_cleanup_task is not None and not self._cache_cleanup_task.done():
            self._cache_cleanup_task.cancel()
            try:
                await self._cache_cleanup_task
            except asyncio.CancelledError:
                pass
            self._cache_cleanup_task = None
        await self.downloader.aclose()

        # ========== 清理B站监控 / 扫码登录任务 ==========
        await self.bili.aclose()
