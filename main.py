"""莉卡解析 - 链接分享解析插件

支持 B站 | 抖音 | 快手 | 微博 | 小红书 | Twitter | AcFun | NGA | GitHub | 酷安
网易云音乐由外部插件联动提供（安装 astrbot_plugin_multincm 后自动接入）

移植自 nonebot-plugin-parser (https://github.com/fllesser/nonebot-plugin-parser)
内置 B站扫码登录、Cookie 监控、自动应用 Cookie 功能

本文件承载 AstrBot 4.x 插件类（基于 ``Star`` + ``metadata.yaml`` 自动识别）与
事件处理器（Handler 必须归属在插件模块下才能被框架注册）。其中各平台的 Handler 由
``link_parser.adapters`` 的注册表自动生成（见 ``_PLATFORM_HANDLERS``），
具体实现按职责分层放在 ``link_parser`` 包中：

    link_parser/adapters   平台解析适配器（自动发现 + 自注册 + 外部插件接入）
    link_parser/config     配置元数据、Schema 自检与运行时配置
    link_parser/models     数据类型
    link_parser/services   下载 / 渲染 / 截图 / 实况照片 / B站账号
    link_parser/output     解析结果到消息链的输出构建
    link_parser/utils      通用工具
    link_parser/webui.py   插件设置页（views/rika）后端 API
"""

import asyncio
import hashlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator

from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult, MessageChain
import astrbot.api.message_components as Comp
from astrbot.api.star import Context, Star, StarTools

from .link_parser.adapters import iter_adapters
from .link_parser.adapters._external import register_external_adapters
from .link_parser.adapters.registry import AdapterBuildContext
from .link_parser.config import (
    detect_content_mode,
    get_config,
    get_global_config,
    init_config,
    scoped_config_for,
)
from .link_parser.constants import (
    COVER_COMMAND_PATTERN,
    GENERIC_URL_PATTERN,
    MINIAPP_CARD_PATTERN,
)
from .link_parser.exceptions import (
    DownloadException,
    IgnoreException,
    ParseException,
    SilentException,
)
from .link_parser.models import ParseResult
from .link_parser.output import (
    EventUrlWrapper,
    build_official_card_assets,
    create_webpage,
    error_result,
    extract_card_link,
    extract_card_title,
    extract_links_from_event,
    find_reply_component,
    format_share_message,
    has_json_component,
    is_miniapp_card,
    parse_miniapp_card,
    plan_output_segments,
    quoted_links,
    quoted_text,
    send_nodes_batched,
    send_plain_output,
    webpage_token_expired,
)
from .link_parser.services.bilibili_account import BiliAccountService
from .link_parser.services.card_render import ShareCardRenderer
from .link_parser.services.card_render.toolkit import FontBook
from .link_parser.services.cover import CoverPick, download_cover
from .link_parser.services.downloader import StreamDownloader
from .link_parser.services.web_screenshot import (
    CloudflareScreenshotClient,
    fetch_page_title,
    is_url_blacklisted,
)
from .link_parser.utils import (
    DEFAULT_BRAND_NAME,
    cleanup_cache_dir,
    clear_cache_dir,
    resolve_brand_name,
)
from .link_parser.webui import WebUIApi, read_schema_problems


def _make_platform_handler(name: str, pattern: str):
    """按适配器注册表生成一个平台 Handler。

    框架以 ``handler.__module__`` **精确匹配**插件模块路径来归属 Handler
    （见 docs/ARCHITECTURE.md），所以函数必须在本模块内构造，并显式改写
    ``__module__`` / ``__name__`` 后再套 ``@filter.regex``。
    """

    async def _handler(
        self: "ParserPlugin",
        event: AstrMessageEvent,
        matched: re.Match | None = None,
    ) -> AsyncGenerator[MessageEventResult, None]:
        async for r in self._dispatch(event, name):
            yield r

    _handler.__name__ = f"{name}_handler"
    _handler.__qualname__ = f"ParserPlugin.{name}_handler"
    _handler.__module__ = __name__
    _handler.__doc__ = f"解析 {name} 平台链接。"
    filter.regex(pattern)(_handler)  # 装饰即注册；函数本身仍由下面的 dict 挂到类上
    return _handler


#: 平台 Handler（``平台名 -> 函数``）。
#:
#: **必须在插件类定义之前生成**：装饰器求值的先后就是 ``star_handlers_registry``
#: 里的注册顺序，也就是同一条消息上各 Handler 的执行顺序。改造前平台 Handler
#: 排在 JSON 卡片 / Cloudflare 兜底 / 指令之前，这里保持不变。
#:
#: 新增平台不需要动本文件：注册了适配器就会在这里自动多出一个 Handler。
#: 外部解析器插件（见 ``link_parser/adapters/_external.py``）也在这一步之前接入，
#: 因此已安装外部插件时会自动多出对应平台；未安装则没有该平台，一切照旧。
register_external_adapters()

_PLATFORM_HANDLERS: dict[str, Any] = {
    spec.name: _make_platform_handler(spec.name, spec.url_pattern.pattern)
    for spec in iter_adapters()
}


#: 「原始链接 → 内容标识」记忆上限，超过则整体清空（避免长跑无限累积）
_IDENTITY_MEMO_MAX = 2048

#: 「内容标识 → (网页原始链接, 页面 token)」复用表上限，超过则整体清空（同上）
_WEBPAGE_LINKS_MAX = 2048


@dataclass
class _ContentCacheEntry:
    """一条内容缓存：解析结果 + 解析时刻 + 卡片文件。

    以「内容标识」（见 ``BaseParser.cache_identity``）为键，因此同一内容的不同
    短链 / 长链共用一条。``parsed_at`` 用于按适配器声明的 ``CACHE_TTL_SECONDS``
    判断是否过期——B站这类带实时数据的平台超时后会重新解析。
    """

    result: ParseResult
    parsed_at: float
    #: (渲染器配置快照, 署名文案) → 成品卡片路径（跨人格共用底卡，成品按署名分开记录）
    render_paths: dict[tuple[tuple[Any, ...], str], Path] = field(default_factory=dict)
    #: 重新解析的次数：>0 时卡片文件名会带上代次，避免复用（或覆盖）上一代卡片
    generation: int = 0

    def expired(self, ttl: int | None, now: float | None = None) -> bool:
        """``ttl`` 为 ``None`` 表示不设有效期。"""
        if ttl is None:
            return False
        return (now if now is not None else time.monotonic()) - self.parsed_at > ttl


class ParserPlugin(Star):
    """莉卡解析插件主类（AstrBot 4.x 自动通过 Star 子类与 metadata.yaml 加载）。"""

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

        data_dir = Path(StarTools.get_data_dir("astrbot_plugin_rika_share"))
        data_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = data_dir
        self.cache_dir = data_dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir = data_dir / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        # 网页分享的 HTML 页面（仅页面本体；图片不复制, 经文件服务热链缓存目录里的原文件）
        self.webpage_dir = data_dir / "webpage"
        self.webpage_dir.mkdir(parents=True, exist_ok=True)
        # 内容标识 → (网页原始链接, 页面 token)：同一内容在链接有效期内复用同一网页。
        # 不随 _content_cache 一起清空——它的有效性由 token 自校验（失效即重建），
        # 这样跨清理周期重复分享拿到的仍是同一个链接
        self._webpage_links: dict[str, tuple[str, str]] = {}

        pconfig = init_config(config, self.cache_dir, self.config_dir)

        self.downloader = StreamDownloader(self.cache_dir)
        self.disabled_platforms = pconfig.DISABLED_PLATFORMS

        self.parsers: dict[str, Any] = {}
        self._init_parsers()
        # 内容标识 → 解析结果缓存（含卡片路径、解析时刻与代次）
        self._content_cache: dict[str, _ContentCacheEntry] = {}
        # 原始链接 → 内容标识（含短链跳转结果），避免重复解析/跳转
        self._identity_cache: dict[str, str] = {}
        self._cache_cleanup_task: asyncio.Task | None = None

        self._renderers: dict[tuple, ShareCardRenderer] = {}
        self._font_books: dict[str, FontBook] = {}
        self._renderer_sig = self._renderer_signature(pconfig)
        self._renderer = self._renderer_for(pconfig)
        if self._renderer.enabled:
            logger.info(
                f"解析图片渲染已启用 (配色: {pconfig.RENDER_THEME}, "
                f"样式: {pconfig.RENDER_STYLE}, "
                f"封面全尺寸: {pconfig.RENDER_COVER_FULL_SIZE}, "
                f"宽度: {pconfig.RENDER_WIDTH}px)"
            )
        else:
            logger.info("解析图片渲染已关闭，使用文本输出")

        # ========== B站 Cookie 监控 / 扫码登录 ==========
        self.bili = BiliAccountService(
            context,
            data_dir,
            self.parsers,
        )

        # ========== Cloudflare 截图 Fallback ==========
        self._cloudflare_client: CloudflareScreenshotClient | None = None
        self._cloudflare_sig = self._cloudflare_signature(pconfig)
        if self._cloudflare_sig is not None:
            self._cloudflare_client = CloudflareScreenshotClient(pconfig)
        if pconfig.CLOUDFLARE_FALLBACK_ENABLED:
            if self._cloudflare_client and self._cloudflare_client.is_configured:
                logger.info("Cloudflare 网页截图 Fallback 已启用")
            else:
                logger.warning(
                    "Cloudflare 截图 Fallback 已开启但未配置 Account ID / API Token，"
                    "请检查插件配置"
                )

        self._register_webui()

    # ==================== 网页设置页 ==================== #

    def _register_webui(self) -> None:
        """注册插件网页设置页（``views/rika``）的后端接口。

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
            logger.info("[link_parser] WebUI 接口已注册（插件页面 views/rika）")
        except Exception:
            logger.warning("[link_parser] WebUI 接口注册失败，网页设置页不可用", exc_info=True)

    async def apply_runtime_config(self) -> dict[str, Any]:
        """把刚保存的配置应用到运行中的组件，避免用户还要重载插件。"""
        result: dict[str, Any] = {}
        pconfig = get_global_config()

        sig = self._renderer_signature(pconfig)
        if sig != self._renderer_sig:
            self._renderers.clear()
            self._renderer = self._renderer_for(pconfig)
            self._renderer_sig = sig
            result["renderer"] = self._renderer.enabled

        disabled = pconfig.DISABLED_PLATFORMS
        if disabled != self.disabled_platforms:
            self.disabled_platforms = disabled
        result["platforms"] = sorted(
            name for name in self.parsers if name not in set(self.disabled_platforms)
        )

        cf_sig = self._cloudflare_signature(pconfig)
        if cf_sig != self._cloudflare_sig:
            self._cloudflare_sig = cf_sig
            self._cloudflare_client = (
                CloudflareScreenshotClient(pconfig) if cf_sig is not None else None
            )
        result["cloudflare"] = bool(
            pconfig.CLOUDFLARE_FALLBACK_ENABLED
            and self._cloudflare_client
            and self._cloudflare_client.is_configured
        )

        return result

    def _cloudflare_signature(self, pconfig: Any = None) -> tuple | None:
        """Cloudflare 截图客户端的凭据与浏览器参数快照（凭据完整时即就绪，供分群开启）。"""
        cfg = pconfig or get_global_config()
        if not cfg.CLOUDFLARE_ACCOUNT_ID or not cfg.CLOUDFLARE_API_TOKEN:
            return None
        return (
            cfg.CLOUDFLARE_ACCOUNT_ID,
            cfg.CLOUDFLARE_API_TOKEN,
            cfg.CLOUDFLARE_TIMEOUT,
            cfg.CLOUDFLARE_VIEWPORT_WIDTH,
            cfg.CLOUDFLARE_VIEWPORT_HEIGHT,
            cfg.CLOUDFLARE_WAIT_UNTIL,
            cfg.CLOUDFLARE_GOTO_TIMEOUT,
            cfg.CLOUDFLARE_FULL_PAGE,
            cfg.CLOUDFLARE_DEVICE_SCALE_FACTOR,
            cfg.CLOUDFLARE_SCREENSHOT_TYPE,
            cfg.CLOUDFLARE_SCREENSHOT_QUALITY,
            cfg.CLOUDFLARE_OMIT_BACKGROUND,
            cfg.CLOUDFLARE_SELECTOR,
            cfg.CLOUDFLARE_WAIT_FOR_SELECTOR,
            cfg.CLOUDFLARE_WAIT_FOR_TIMEOUT,
            cfg.CLOUDFLARE_USER_AGENT,
            cfg.CLOUDFLARE_EXTRA_HEADERS,
            cfg.CLOUDFLARE_COOKIES,
            cfg.CLOUDFLARE_CACHE_TTL,
        )

    def _renderer_for(self, pconfig: Any = None) -> ShareCardRenderer:
        """按生效配置获取或懒构造共享字体表的卡片渲染器。"""
        cfg = pconfig or get_config()
        sig = self._renderer_signature(cfg)
        renderer = self._renderers.get(sig)
        if renderer is not None:
            return renderer
        font_key = cfg.RENDER_FONT_PATH or ""
        font_book = self._font_books.get(font_key)
        if font_book is None:
            font_book = FontBook(cfg.RENDER_FONT_PATH or None)
            if len(self._font_books) >= 8:
                self._font_books.clear()
            self._font_books[font_key] = font_book
        renderer = ShareCardRenderer(
            self.cache_dir,
            enabled=cfg.RENDER_ENABLED,
            width=cfg.RENDER_WIDTH,
            theme=cfg.RENDER_THEME,
            font_path=cfg.RENDER_FONT_PATH or None,
            style=cfg.RENDER_STYLE,
            cover_full_size=cfg.RENDER_COVER_FULL_SIZE,
            font_book=font_book,
        )
        if len(self._renderers) >= 16:
            self._renderers.clear()
        self._renderers[sig] = renderer
        return renderer

    def _build_renderer(self) -> ShareCardRenderer:
        """按当前生效配置构造或获取卡片渲染器。"""
        return self._renderer_for(get_config())

    def _renderer_signature(self, pconfig: Any = None) -> tuple:
        """渲染器的构造参数快照。"""
        cfg = pconfig or get_config()
        return (
            cfg.RENDER_ENABLED,
            cfg.RENDER_WIDTH,
            cfg.RENDER_THEME,
            cfg.RENDER_FONT_PATH,
            cfg.RENDER_STYLE,
            cfg.RENDER_COVER_FULL_SIZE,
        )

    def _init_parsers(self) -> None:
        """按适配器注册表实例化全部平台解析器；分群启用状态在调度时动态过滤。"""
        build_context = AdapterBuildContext(
            downloader=self.downloader,
            config=get_global_config(),
            config_dir=self.config_dir,
        )
        for spec in iter_adapters():
            self.parsers[spec.name] = spec.create(build_context)
        enabled = [
            k for k in self.parsers if k not in set(self.disabled_platforms)
        ]
        logger.info(
            f"已加载适配器 {len(self.parsers)} 个；全局启用平台: {', '.join(enabled)}"
        )

    @staticmethod
    def _is_platform_enabled(name: str, pconfig: Any = None) -> bool:
        cfg = pconfig or get_config()
        return name not in set(cfg.DISABLED_PLATFORMS)

    @staticmethod
    def _event_scope_info(event: AstrMessageEvent) -> tuple[str, str, str]:
        """提取事件所属的 ``(umo, group_id, platform_id)``。"""
        umo = str(getattr(event, "unified_msg_origin", "") or "").strip()
        gid = ""
        pid = ""
        try:
            gid = str(event.get_group_id() or "").strip()
        except Exception:
            gid = ""
        try:
            pid = str(event.get_platform_id() or "").strip()
        except Exception:
            pid = ""
        return umo, gid, pid

    def _enter_event_scope(self, event: AstrMessageEvent):
        """记录活跃群组并返回绑定的配置作用域上下文管理器。"""
        umo, gid, pid = self._event_scope_info(event)
        if umo or gid:
            try:
                get_global_config().groups.record_seen_group(
                    umo, group_id=gid, platform_id=pid
                )
            except Exception:
                logger.debug("[link_parser] 记录活跃群信息失败", exc_info=True)
        return scoped_config_for(umo=umo, group_id=gid)

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
                        # 网页分享的页面文件与缓存共用同一 TTL（链接时效也由它决定）
                        await cleanup_cache_dir(self.webpage_dir, ttl_hours=ttl)
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
        with self._enter_event_scope(event) as pconfig:
            if not self._is_platform_enabled(name, pconfig):
                return
            async for r in self._process_url(event, parser):
                yield r

    # ==================== 平台处理器 ====================
    #
    # 每个平台一个 ``@filter.regex`` Handler，由文件开头按适配器注册表自动生成并挂到
    # 类上（``_PLATFORM_HANDLERS``）。新增平台只要注册了适配器就有 Handler，无需改本文件。

    # ==================== JSON 卡片处理器 ====================

    @filter.regex(r".*")
    async def json_card_handler(self, event: AstrMessageEvent, matched: re.Match | None = None):
        if not has_json_component(event):
            return
        links = extract_links_from_event(event)
        if not links:
            return
        unique_links = list(dict.fromkeys(links))
        with self._enter_event_scope(event) as pconfig:
            for link in unique_links:
                for pname, parser in self.parsers.items():
                    if not self._is_platform_enabled(pname, pconfig):
                        continue
                    try:
                        _, _ = parser.search_url(link)
                        wrapped = EventUrlWrapper(event, link)
                        async for r in self._process_url(wrapped, parser):
                            yield r
                        return
                    except ParseException:
                        continue

    # ==================== 官方机器人分享卡片处理器 ====================

    def _card_source_parser(self, source: str) -> Any | None:
        """按卡片 ``source`` 字段挑出对应解析器（精确匹配平台名 / 展示名）。"""
        if not source:
            return None
        for parser in self.parsers.values():
            platform = getattr(parser, "platform", None)
            if platform is not None and source in (platform.name, platform.display_name):
                return parser
        return None

    @filter.regex(MINIAPP_CARD_PATTERN.pattern)
    async def miniapp_card_handler(
        self, event: AstrMessageEvent, matched: re.Match | None = None
    ):
        """QQ 官方机器人的分享卡片（纯文本形态）：按链接或卡片标题解析。

        官方机器人收到的分享卡片是**纯文本**（字段形态见 ``output/miniapp_card.py``）：
        「图文H5」卡片带 ``jump_url``，链接可认领时由平台 Handler 按链接解析（见上）；
        「小程序」卡片只有标题没有链接，取 ``title`` 去对应平台搜索——目前 B站
        适配器实现了 ``search_video_by_title``，其他平台的卡片静默跳过。
        """
        fields = parse_miniapp_card(event.message_str)
        if fields is None:
            return
        with self._enter_event_scope(event) as pconfig:
            # 「图文H5」等带 jump_url 的卡片**优先按链接解析**：链接能被已启用的平台
            # 认领时交给平台 Handler（其 filter 已命中并先行处理），这里不再按标题
            # 搜索，避免同一条卡片解析两次；认领不了才回退标题搜索
            link = extract_card_link(fields)
            if link:
                for pname, existing in self.parsers.items():
                    if not self._is_platform_enabled(pname, pconfig):
                        continue
                    try:
                        existing.search_url(link)
                    except Exception:
                        continue
                return
            title = extract_card_title(fields)
            if not title:
                return
            # 「小程序」卡片的平台字段是 source，「图文H5」卡片是 tag
            parser = self._card_source_parser(fields.get("source") or fields.get("tag") or "")
            if parser is not None and not self._is_platform_enabled(parser.platform.name, pconfig):
                return
            search_fn = getattr(parser, "search_video_by_title", None) if parser else None
            if search_fn is None:
                return  # 非已支持平台的卡片，或不支持按标题搜索
            try:
                url = await search_fn(title)
            except ParseException as e:
                result = error_result(event, f"❌ 解析失败: {e.message}")
                if result is not None:
                    yield result
                return
            except Exception:
                logger.exception("小程序卡片标题搜索异常")
                result = error_result(event, "❌ 处理出错: 标题搜索失败")
                if result is not None:
                    yield result
                return
            if not url:
                result = error_result(
                    event,
                    f"❌ 未能在{parser.platform.display_name}找到与「{title[:40]}」匹配的内容",
                )
                if result is not None:
                    yield result
                return
            logger.info(f"小程序卡片标题搜索命中: {title[:50]} → {url}")
            # 命中后包装成链接，复用与 JSON 卡片相同的解析主干（缓存 / 渲染 / 输出全一致）
            wrapped = EventUrlWrapper(event, url)
            async for r in self._process_url(wrapped, parser):
                yield r

    # ==================== Cloudflare 截图 Fallback ====================

    async def _resolve_brand_name(self, event: AstrMessageEvent) -> str:
        """根据配置解析当前会话署名（关闭人格跟随或使用默认人格时回退自定义署名）。"""
        pconfig = get_config()
        return await resolve_brand_name(
            self.context,
            event,
            enabled=pconfig.RENDER_PERSONA_WATERMARK,
            default=pconfig.RENDER_BRAND_NAME or DEFAULT_BRAND_NAME,
        )

    def _is_cloudflare_available(self, pconfig: Any = None) -> bool:
        """Cloudflare 截图 Fallback 是否可用（凭据全局就绪 + 当前作用域已启用）。"""
        cfg = pconfig or get_config()
        if not cfg.CLOUDFLARE_FALLBACK_ENABLED:
            return False
        if self._cloudflare_client is None:
            return False
        return self._cloudflare_client.is_configured

    async def _do_cloudflare_fallback(
        self, event: AstrMessageEvent, url: str
    ):
        """Cloudflare 网页截图 fallback 处理：渲染网页并发送截图"""
        # 先获取标题（并发：和截图并行）
        title_task = asyncio.create_task(fetch_page_title(url))
        brand_task = asyncio.create_task(self._resolve_brand_name(event))

        save_dir = self.cache_dir / "cloudflare_screenshots"
        path = await self._cloudflare_client.screenshot(url, save_dir)

        title, brand_name = await asyncio.gather(title_task, brand_task)
        # 对齐其它解析器的 header 格式：署名 | 标题
        fallback_title = title or url[:80]
        header = f"{brand_name} | 网站 - {fallback_title}"

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
        with self._enter_event_scope(event) as pconfig:
            if not self._is_cloudflare_available(pconfig):
                return
            # JSON 卡片由 json_card_handler 处理，避免重复
            if has_json_component(event):
                return
            # 官方机器人的小程序卡片（纯文本）由 miniapp_card_handler 处理：
            # 卡片文本里的 source_logo / preview URL 不是网页，不该被截图
            if is_miniapp_card(event.message_str):
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
            for pname, parser in self.parsers.items():
                if not self._is_platform_enabled(pname, pconfig):
                    continue
                try:
                    parser.search_url(url)
                    return  # 已有适配器，让平台专用 handler 处理
                except Exception:
                    continue

            # 命中黑名单则跳过 Cloudflare 截图
            if is_url_blacklisted(url, pconfig.CLOUDFLARE_BLACKLIST):
                logger.info(f"Cloudflare Fallback: URL 命中黑名单，跳过: {url[:80]}")
                return

            logger.info(f"Cloudflare Fallback: 未匹配适配器，渲染网页截图: {url[:80]}")
            async for r in self._do_cloudflare_fallback(event, url):
                yield r

    # ==================== 核心处理流程 ====================

    #: 支持 ``Comp.Music`` 音乐卡片的平台（与 multincm._send_song 的判断保持一致）
    _MUSIC_CARD_PLATFORMS = frozenset({"qq", "aiocqhttp", "qqguild"})

    @staticmethod
    def _supports_music_card(event: AstrMessageEvent) -> bool:
        """当前平台是否能发送 ``Comp.Music`` 音乐卡片。

        按平台类型名（``platform_meta.name``，如 ``aiocqhttp``）判断；对
        OneBot 生态的变体命名再放行子串（与 ``_is_onebot`` 的口径一致）。
        """
        try:
            name = (event.get_platform_name() or "").lower()
        except Exception:
            return False
        return name in ParserPlugin._MUSIC_CARD_PLATFORMS or "aiocqhttp" in name

    @staticmethod
    def _build_music_card(spec: dict[str, Any]) -> "Comp.Music | None":
        """按外部解析器下发的规格构造 ``Comp.Music``（type=163，按歌曲 ID 由协议端签名）。

        Pydantic v1 会忽略 ``_`` 前缀字段，``_type`` 需经 ``__dict__`` 注入
        （与 multincm._send_music_card 的做法一致）。构造失败返回 ``None``，
        由调用方回退常规输出。
        """
        try:
            card = Comp.Music(id=int(spec["id"]))
            card.__dict__["_type"] = str(spec.get("type") or "163")
            return card
        except Exception:
            logger.warning("构造音乐卡片失败，回退常规解析输出", exc_info=True)
            return None

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

    async def _resolve_entry(
        self, parser: Any, url: str, *, refresh: bool = False
    ) -> tuple[str, _ContentCacheEntry]:
        """取「内容标识 → 缓存条目」，未命中或已过期则解析一次并写入缓存。

        ``refresh=True`` 跳过缓存直接重新解析（封面下载遇到缓存文件已被回收时用）。
        返回 ``(cache_key, entry)``，``cache_key`` 同时用于派生卡片文件名。
        """
        # 缓存键 = 内容标识：不同短链 / 长链指向同一内容时命中同一条缓存
        cache_key = await self._content_cache_key(parser, url)
        entry = None if refresh else self._content_cache.get(cache_key)

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
        return cache_key, entry

    async def _video_service_url(self, path: Path) -> str | None:
        """若 AstrBot 配置了 callback_api_base，则将视频注册为 /api/file URL 以兼容跨容器合并转发。"""
        if not self._get_callback_base():
            return None
        try:
            return await Comp.Video.fromFileSystem(str(path)).register_to_file_service()
        except Exception:
            logger.debug(f"[link_parser] 注册合并视频文件服务链接失败: {path.name}", exc_info=True)
            return None

    async def _emit_proactive_or_yield(
        self, event: AstrMessageEvent, item: list[Any]
    ) -> AsyncGenerator[MessageEventResult, None]:
        """优先主动发送独立图片（防 @ 引用污染），失败或平台不支持时回退事件回复。"""
        try:
            sent = await self.context.send_message(
                event.unified_msg_origin,
                MessageChain(chain=list(item)),
            )
            if sent:
                return
        except Exception as e:
            logger.debug(f"独立图片主动发送回退管线回复: {e}")
        yield event.chain_result(item)

    async def _process_url(
        self, event: AstrMessageEvent, parser: Any
    ) -> AsyncGenerator[MessageEventResult, None]:
        url = event.message_str.strip()

        try:
            cache_key, entry = await self._resolve_entry(parser, url)
            result = entry.result
            pconfig = get_config()

            music_card_spec = result.extra.get("music_card")
            music_card = None
            if music_card_spec:
                if self._supports_music_card(event):
                    music_card = self._build_music_card(music_card_spec)
                else:
                    logger.info(
                        f"[link_parser] 平台 {event.get_platform_name()} 不支持音乐卡片，"
                        "回退常规解析输出（卡片图 + 语音）"
                    )

            brand_name = await self._resolve_brand_name(event)

            # 仅当当前内容模式的规则启用了 card 节点时才渲染卡片图
            mode = detect_content_mode(result)
            mode_rules = pconfig.NODE_RULES.get(mode) or []
            card_enabled = any(r.get("id") == "card" and r.get("enabled") for r in mode_rules)

            renderer = self._renderer_for(pconfig)
            renderer_sig = self._renderer_signature(pconfig)
            render_path: Path | None = None
            if card_enabled and renderer is not None and renderer.enabled:
                render_cache_key = (renderer_sig, brand_name)
                render_path = await renderer.render(
                    result,
                    cache_key=cache_key,
                    existing=entry.render_paths.get(render_cache_key),
                    # 代次 >0 表示内容被重新解析过，卡片文件名要跟着换代
                    salt=str(entry.generation) if entry.generation else None,
                    watermark=brand_name,
                )
                if render_path is not None:
                    entry.render_paths[render_cache_key] = render_path

            is_onebot = self._is_onebot(event)
            try:
                chat_platform = event.get_platform_name() or ""
            except Exception:
                chat_platform = ""

            plan = await plan_output_segments(
                result,
                pconfig=pconfig,
                is_onebot=is_onebot,
                chat_platform=chat_platform,
                brand_name=brand_name,
                render_path=render_path,
                music_card=music_card,
                video_url_resolver=self._video_service_url,
            )

            rules_digest = hashlib.md5(
                repr((plan["mode"], plan["rules"], brand_name)).encode("utf-8")
            ).hexdigest()[:8]

            for seg_idx, seg in enumerate(plan["segments"]):
                if seg["kind"] == "merge":
                    if is_onebot:
                        async for r in send_nodes_batched(
                            event,
                            seg["header"] or plan["header"],
                            seg["items"],
                            header_inline=bool(seg["header"]),
                        ):
                            yield r
                    else:
                        seg_items = list(seg["items"])
                        seg_header = seg["header"] or plan["header"]
                        if seg["header"] and seg["has_non_header"]:
                            seg_items = [
                                item
                                for item in seg_items
                                if not (
                                    len(item) == 1
                                    and isinstance(item[0], Comp.Plain)
                                    and item[0].text == seg["header"]
                                )
                            ]
                        if not seg_items:
                            seg_items = [[Comp.Plain(seg_header)]]
                        webpage_key = f"{cache_key}:{rules_digest}:{seg_idx}"
                        async for r in self._send_text_output(
                            event, seg_header, seg_items, webpage_key
                        ):
                            yield r
                else:
                    nid = seg.get("nid")
                    if nid == "music_card" and music_card_spec:
                        logger.info(
                            f"[link_parser] 发送音乐卡片 ({music_card_spec.get('type')}) "
                            f"ID={music_card_spec.get('id')}"
                        )
                    for item in seg["items"]:
                        if seg.get("proactive_image"):
                            async for r in self._emit_proactive_or_yield(event, item):
                                yield r
                        else:
                            yield event.chain_result(item)

        except SilentException:
            return  # 匹配不到模式时静默失败，不发送通知
        except IgnoreException as e:
            result = error_result(event, f"ℹ️ {e.message}")
            if result is not None:
                yield result
        # 顺序要紧：DownloadException 是 ParseException 的子类，放在父类之后就成了死代码
        except DownloadException as e:
            result = error_result(event, f"⚠️ 下载失败: {e.message}")
            if result is not None:
                yield result
        except ParseException as e:
            result = error_result(event, f"❌ 解析失败: {e.message}")
            if result is not None:
                yield result
        except Exception as e:
            logger.exception("解析异常")
            result = error_result(event, f"❌ 处理出错: {str(e)[:100]}")
            if result is not None:
                yield result

    # ==================== 网页分享（非 OneBot 平台的合并转发替代） ====================

    async def _send_text_output(
        self,
        event: AstrMessageEvent,
        header: str,
        text_items: list[list],
        cache_key: str,
    ) -> AsyncGenerator[MessageEventResult, None]:
        """非 OneBot 平台的文本输出：合并转发内容全部转网页，聊天里只发一条链接通知。

        QQ 官方平台的三级形态（详见 5.16）：
        ① 图文卡片（仅 qq_official_full 适配器有 msg_type=8 通道；卡片不能带引用，
           走主动发送）；② markdown 链接（use_markdown，机器人无 md 权限时适配器
           自动降级纯文本）；③ 纯文本。其他平台为纯文本链接。
        同一内容（同 ``cache_key``）在链接有效期内复用同一网页——token 失效自动重建。
        未启用 / 未配置「对外可达的回调接口地址」（callback_api_base）/ 全链失败时，
        回退到 :func:`send_plain_output` 的纯文本 + 图片链（与旧版行为一致）。
        """
        try:
            pconfig = get_config()
            if pconfig.WEBPAGE_FALLBACK_ENABLED:
                base_url = self._get_callback_base()
                if base_url:
                    cached = self._webpage_links.get(cache_key)
                    if cached and not await webpage_token_expired(cached[1]):
                        url = cached[0]
                    else:
                        url, token = await create_webpage(
                            event,
                            header,
                            text_items,
                            page_dir=self.webpage_dir,
                            base_url=base_url,
                            ttl_hours=pconfig.CACHE_TTL_HOURS,
                        )
                        if len(self._webpage_links) >= _WEBPAGE_LINKS_MAX:
                            self._webpage_links.clear()
                        self._webpage_links[cache_key] = (url, token)

                    try:
                        platform = (event.get_platform_name() or "").lower()
                    except Exception:
                        platform = ""
                    is_qq_official = "qq_official" in platform
                    is_qq_full = "qq_official_full" in platform

                    # ① 图文卡片：仅 qq_official_full 有 msg_type=8 通道。
                    #    卡片不能带引用（带引用客户端会显示「请使用新版手机QQ查看」），
                    #    所以走主动发送，与解析卡片图同一模式
                    if is_qq_full:
                        try:
                            card = await build_official_card_assets(
                                event,
                                header,
                                text_items,
                                page_url=url,
                                page_dir=self.webpage_dir,
                                base_url=base_url,
                                ttl_hours=pconfig.CACHE_TTL_HOURS,
                            )
                            if card is not None:
                                sent = await self.context.send_message(
                                    event.unified_msg_origin,
                                    MessageChain(
                                        chain=[Comp.Json(data={"msg_type": 8, "card": card})]
                                    ),
                                )
                                if sent:
                                    return
                                logger.info(
                                    "[link_parser] 图文卡片主动发送未匹配到会话，回退 markdown/纯文本"
                                )
                        except Exception as e:
                            logger.warning(
                                f"[link_parser] 图文卡片发送失败，回退 markdown/纯文本: {e}"
                            )

                    # ② markdown 链接（QQ 官方；无 md 权限时适配器自动降级纯文本）
                    # ③ 其他平台 / 非官方形态：纯文本
                    msg = format_share_message(
                        event, header, text_items, url, markdown=is_qq_official
                    )
                    yield event.plain_result(msg).use_markdown(
                        True if is_qq_official else None
                    )
                    return
        except Exception:
            logger.warning("[link_parser] 合并转发转网页失败，回退纯文本输出", exc_info=True)
        async for r in send_plain_output(event, header, text_items):
            yield r

    def _get_callback_base(self) -> str:
        """AstrBot「对外可达的回调接口地址」（顶层配置键 ``callback_api_base``）。

        空串表示未配置——链接发出去也打不开，此时直接回退纯文本输出。
        """
        try:
            cfg = self.context.get_config()
            return str(cfg.get("callback_api_base") or "").strip().rstrip("/")
        except Exception:
            return ""

    # ==================== 封面下载（引用回复触发） ====================

    def _pick_supported_link(self, links: list[str]) -> tuple[Any, str] | None:
        """挑出第一个「有适配器认领」的链接。

        没被任何已启用解析器认领的链接（普通网页、已关闭的平台）不算命中——
        与其对无关链接回一句「解析失败」，不如让调用方按「没找到」处理。
        """
        pconfig = get_config()
        for link in links:
            link = link.rstrip(".,!?;:)'\"】」》）")
            for pname, parser in self.parsers.items():
                if not self._is_platform_enabled(pname, pconfig):
                    continue
                try:
                    parser.search_url(link)
                except Exception:
                    continue
                return parser, link
        return None

    async def _cover_for(
        self, parser: Any, url: str
    ) -> tuple[CoverPick | None, Path | None]:
        """解析（或复用缓存）并取封面文件，返回 ``(选择结果, 路径)``。

        缓存里的文件可能已被 TTL 清理（``PathTask`` 会把旧路径原样返回），
        所以取到路径后要确认文件还在，否则丢掉这条缓存重新解析一次。
        """
        last_pick: CoverPick | None = None
        for attempt in (0, 1):
            cache_key, entry = await self._resolve_entry(
                parser, url, refresh=attempt > 0
            )
            pick, path = await download_cover(entry.result)
            last_pick = pick
            if path is not None and path.is_file():
                return pick, path
            self._content_cache.pop(cache_key, None)
            if pick is None:
                break  # 这条内容本来就没有封面，重试也没有意义
        return last_pick, None

    @filter.regex(COVER_COMMAND_PATTERN.pattern)
    async def cover_command_handler(self, event: AstrMessageEvent):
        """引用一条含分享链接的消息并回复「下载封面」，下载该内容的封面图。"""
        if find_reply_component(event) is None:
            # 没有引用任何消息：只有明确叫到机器人时才提示用法，避免在群里插话
            if event.is_at_or_wake_command:
                yield event.plain_result(
                    "ℹ️ 请先引用一条含分享链接的消息，再回复「下载封面」"
                )
            return

        with self._enter_event_scope(event):
            async for r in self._download_cover(event):
                yield r

    async def _download_cover(
        self, event: AstrMessageEvent
    ) -> AsyncGenerator[MessageEventResult, None]:
        text = await quoted_text(event)
        target = self._pick_supported_link(quoted_links(event, text))
        if target is None:
            yield event.plain_result("❌ 引用的消息里没有可解析的分享链接")
            return

        parser, url = target
        try:
            pick, path = await self._cover_for(parser, url)
            if pick is None:
                yield event.plain_result("ℹ️ 这条内容没有可下载的封面")
                return
            if path is None:
                yield event.plain_result("⚠️ 封面下载失败")
                return

            brand_name = await self._resolve_brand_name(event)
            header = f"{brand_name} | {parser.platform.display_name} - {pick.label}"
            logger.info(f"封面已下载: {url[:80]} → {path.name}")
            if self._is_onebot(event):
                yield event.chain_result([
                    Comp.Plain(header),
                    Comp.Image.fromFileSystem(str(path)),
                ])
            else:
                # 非 OneBot 平台：主动发送，避免「回复时 @ 发送人」污染图片消息
                try:
                    sent = await self.context.send_message(
                        event.unified_msg_origin,
                        MessageChain().message(f"{header}\n").file_image(str(path)),
                    )
                    if not sent:
                        logger.warning(f"封面主动发送未找到匹配平台会话: {path.name}")
                except Exception as e:
                    logger.warning(f"封面主动发送异常: {e}")

        except SilentException:
            return  # 匹配不到模式时静默失败，不发送通知
        except IgnoreException as e:
            result = error_result(event, f"ℹ️ {e.message}")
            if result is not None:
                yield result
        # 顺序要紧：DownloadException 是 ParseException 的子类，放在父类之后就成了死代码
        except DownloadException as e:
            result = error_result(event, f"⚠️ 下载失败: {e.message}")
            if result is not None:
                yield result
        except ParseException as e:
            result = error_result(event, f"❌ 解析失败: {e.message}")
            if result is not None:
                yield result
        except Exception as e:
            logger.exception("封面下载异常")
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

    async def clear_all_caches(self) -> int:
        """清理磁盘缓存、临时分享网页与内存解析缓存，返回删除的文件总数。"""
        cleaned = await clear_cache_dir(self.cache_dir)
        cleaned += await clear_cache_dir(self.webpage_dir)
        self._content_cache.clear()
        self._identity_cache.clear()
        self._webpage_links.clear()
        return cleaned

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("clear_cache", alias={"清理缓存"})
    async def clear_cache(self, event: AstrMessageEvent):
        """手动清理插件缓存。"""
        try:
            cleaned = await self.clear_all_caches()
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


def _attach_platform_handlers(plugin_cls: type) -> None:
    """把自动生成的平台 Handler 挂到插件类上。

    框架是按 ``star_handlers_registry``（按模块路径归属）调用 Handler 的，
    并不要求它一定是类的方法；挂载只是为了让 ``ParserPlugin.bilibili_handler``
    这类按名字引用的写法依旧可用，也方便阅读与测试。
    """
    for handler in _PLATFORM_HANDLERS.values():
        setattr(plugin_cls, handler.__name__, handler)


_attach_platform_handlers(ParserPlugin)
