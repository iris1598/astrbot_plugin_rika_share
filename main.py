"""
莉卡解析 - 链接分享解析插件

支持 B站 | 抖音 | 快手 | 微博 | 小红书 | Twitter | AcFun | NGA
选项: YouTube | TikTok (需安装 yt-dlp)

移植自 nonebot-plugin-parser (https://github.com/fllesser/nonebot-plugin-parser)
"""

import re
import asyncio
from pathlib import Path
from typing import Any, AsyncGenerator

from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
import astrbot.api.message_components as Comp
from astrbot.api.star import Context, Star, register

from .core.utils import cleanup_cache_dir
from .core.config import init_config, get_config
from .core.download import StreamDownloader
from .core.data import ParseResult
from .core.exception import ParseException, IgnoreException, DownloadException, SilentException
from .core.parsers import (
    BilibiliParser, DouyinParser, KuaiShouParser, WeiBoParser,
    XiaoHongShuParser, TwitterParser, NGAParser, AcfunParser,
)


def _get_plugin_data_dir() -> Path:
    from astrbot.core.utils.astrbot_path import get_astrbot_data_path
    return Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_rika_share"


# ========== URL 匹配模式 ==========
BILIBILI_PATTERN = re.compile(r"(bilibili\.com|b23\.tv|bili2233\.cn|BV[1-9a-zA-Z]{10}|av\d{6,})")
DOUYIN_PATTERN = re.compile(r"(v\.douyin\.com|douyin\.com|iesdouyin\.com|m\.douyin\.com|jx\.douyin\.com|jingxuan\.douyin\.com)")
KUAISHOU_PATTERN = re.compile(r"(v\.kuaishou\.com|kuaishou\.com|chenzhongtech\.com)")
WEIBO_PATTERN = re.compile(r"(weibo\.com|weibo\.cn|m\.weibo\.cn|video\.weibo\.com|mapp\.api\.weibo\.cn)")
XHS_PATTERN = re.compile(r"(xhslink\.com|xiaohongshu\.com)")
TWITTER_PATTERN = re.compile(r"x\.com")
NGA_PATTERN = re.compile(r"nga\.178\.com|ngabbs\.com|bbs\.nga\.cn")
ACFUN_PATTERN = re.compile(r"acfun\.cn")


class _EventUrlWrapper:
    def __init__(self, event: AstrMessageEvent, url: str):
        self._event = event
        self.message_str = url

    def __getattr__(self, name):
        return getattr(self._event, name)


@register("链接解析器", "fllesser (ported to AstrBot)",
          "链接分享自动解析插件，支持 B站|抖音|快手|微博|小红书|Twitter|AcFun|NGA", "2.6.5")
class ParserPlugin(Star):
    # QQ Official Bot 平台标识符（不支持 Comp.Nodes 合并转发）
    # 同时检测字符串包含匹配，覆盖 "qq_official" / "qqofficial" / "qq_official_webhook" 等变体
    @staticmethod
    def _is_qqofficial(event: AstrMessageEvent) -> bool:
        """检测当前平台是否为 QQ Official Bot。"""
        try:
            platform_name = event.get_platform_name().lower()
            is_qqoff = "qqofficial" in platform_name or "qq_official" in platform_name
            if is_qqoff:
                logger.debug(f"[rika_share] 检测到 QQ Official Bot 平台: {platform_name}")
            return is_qqoff
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
        self.downloader = StreamDownloader(self.cache_dir)
        self.disabled_platforms = pconfig.DISABLED_PLATFORMS

        self.parsers: dict[str, Any] = {}
        self._init_parsers()
        self._result_cache: dict[str, ParseResult] = {}
        self._cache_cleanup_task: asyncio.Task | None = None

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
                        # 文件清理后同步清空内存缓存
                        self._result_cache.clear()
                        await asyncio.sleep(interval)
                except asyncio.CancelledError:
                    logger.info("缓存清理任务已停止")
                    raise

            self._cache_cleanup_task = asyncio.create_task(_cache_cleanup_loop())
        else:
            logger.info("缓存自动清理已禁用 (CACHE_TTL_HOURS=0)")

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
    async def bilibili_handler(self, event: AstrMessageEvent):
        async for r in self._dispatch(event, "bilibili"):
            yield r

    @filter.regex(DOUYIN_PATTERN)
    async def douyin_handler(self, event: AstrMessageEvent):
        async for r in self._dispatch(event, "douyin"):
            yield r

    @filter.regex(KUAISHOU_PATTERN)
    async def kuaishou_handler(self, event: AstrMessageEvent):
        async for r in self._dispatch(event, "kuaishou"):
            yield r

    @filter.regex(WEIBO_PATTERN)
    async def weibo_handler(self, event: AstrMessageEvent):
        async for r in self._dispatch(event, "weibo"):
            yield r

    @filter.regex(XHS_PATTERN)
    async def xiaohongshu_handler(self, event: AstrMessageEvent):
        async for r in self._dispatch(event, "xiaohongshu"):
            yield r

    @filter.regex(TWITTER_PATTERN)
    async def twitter_handler(self, event: AstrMessageEvent):
        async for r in self._dispatch(event, "twitter"):
            yield r

    @filter.regex(NGA_PATTERN)
    async def nga_handler(self, event: AstrMessageEvent):
        async for r in self._dispatch(event, "nga"):
            yield r

    @filter.regex(ACFUN_PATTERN)
    async def acfun_handler(self, event: AstrMessageEvent):
        async for r in self._dispatch(event, "acfun"):
            yield r

    # ==================== JSON 卡片处理器 ====================

    # 小程序卡片 source 字段 → parser 名称映射
    _SOURCE_PARSER_MAP: dict[str, str] = {
        "哔哩哔哩": "bilibili",
        "bilibili": "bilibili",
        "微博": "weibo",
        "weibo": "weibo",
        "抖音": "douyin",
        "douyin": "douyin",
        "快手": "kuaishou",
        "kuaishou": "kuaishou",
        "小红书": "xiaohongshu",
        "xiaohongshu": "xiaohongshu",
        "twitter": "twitter",
        "x": "twitter",
        "acfun": "acfun",
        "AcFun": "acfun",
        "NGA": "nga",
        "nga": "nga",
    }

    @filter.regex(r".*")
    async def json_card_handler(self, event: AstrMessageEvent):
        if not self._has_json_component(event):
            return

        # 提取小程序来源平台，用于优先匹配
        source = self._extract_miniprogram_source(event)

        # 提取链接
        links = self._extract_links_from_event(event)

        if links:
            unique_links = list(dict.fromkeys(links))
            parser_order: list = []
            if source and source in self.parsers:
                parser_order.append((source, self.parsers[source]))
            for name, parser in self.parsers.items():
                if name != source:
                    parser_order.append((name, parser))

            for link in unique_links:
                for _, parser in parser_order:
                    try:
                        _, _ = parser.search_url(link)
                        wrapped = _EventUrlWrapper(event, link)
                        async for r in self._process_url(wrapped, parser):
                            yield r
                        return
                    except ParseException:
                        continue
        else:
            # 没有提取到链接时，记录卡片结构便于排查
            logger.debug(f"[rika_share] 小程序卡片未提取到链接 (source={source})")

    def _extract_miniprogram_source(self, event: AstrMessageEvent) -> str | None:
        """从小程序卡片中提取来源平台名称，并映射到 parser 名称。"""
        if not hasattr(event, "message_obj") or not hasattr(event.message_obj, "message"):
            return None
        for c in event.message_obj.message:
            data = None
            if isinstance(c, dict):
                data = c.get("data", c)
            elif isinstance(c, Comp.Json):
                try:
                    import json
                    data = json.loads(c.data) if isinstance(c.data, str) else c.data
                except Exception:
                    continue

            if data is None:
                continue

            # 递归搜索 source 字段
            def find_source(obj, depth=0):
                if depth > 5 or obj is None:
                    return None
                if isinstance(obj, dict):
                    s = obj.get("source", "")
                    if isinstance(s, str) and s:
                        mapped = ParserPlugin._SOURCE_PARSER_MAP.get(s)
                        if mapped:
                            return mapped
                    for v in obj.values():
                        if isinstance(v, (dict, list)):
                            r = find_source(v, depth + 1)
                            if r:
                                return r
                    # 检查 prompt 字段: "[QQ小程序]标题" 可能包含来源线索
                    prompt = obj.get("prompt", "")
                    if isinstance(prompt, str) and "哔哩哔哩" in prompt:
                        return "bilibili"
                elif isinstance(obj, list):
                    for item in obj:
                        if isinstance(item, (dict, list)):
                            r = find_source(item, depth + 1)
                            if r:
                                return r
                return None

            result = find_source(data)
            if result:
                return result
        return None

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

            if self._is_qqofficial(event):
                # QQ Official Bot: 拆分为独立消息序列（不支持 Comp.Nodes）
                async for r in self._send_qqofficial_output(event, header, nodes_content):
                    yield r
            else:
                # AIOCQHTTP / 其他平台：使用合并转发
                sender_name = event.get_sender_name()
                sender_id = event.get_sender_id()
                nodes = Comp.Nodes([])
                nodes.nodes.append(Comp.Node(uin=sender_id, name=sender_name, content=[Comp.Plain(header)]))
                for item in nodes_content:
                    nodes.nodes.append(Comp.Node(uin=sender_id, name=sender_name, content=item))
                yield event.chain_result([nodes])

            # 单独发送媒体文件（Video / Audio）
            # 注意：图片已在 Nodes（AIOCQHTTP）或 _send_qqofficial_output（QQOFFICIAL）中处理
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

        QQ Official Bot 有文件上传大小限制，超限文件将跳过并给出提示。
        """
        from .core.data import VideoContent, AudioContent

        # QQ Official Bot 视频上传限制约 30MB，保守设为 28MB
        QQOFFICIAL_VIDEO_MAX_BYTES = 28 * 1024 * 1024
        is_qqoff = self._is_qqofficial(event)

        for cont in result.contents:
            if not isinstance(cont, (VideoContent, AudioContent)):
                continue  # 图片已在合并转发中
            path = await cont.path_task.safe_get()
            if path is None:
                continue

            if isinstance(cont, VideoContent):
                if is_qqoff:
                    file_size = path.stat().st_size
                    if file_size > QQOFFICIAL_VIDEO_MAX_BYTES:
                        size_mb = file_size / (1024 * 1024)
                        yield event.plain_result(
                            f"⚠️ 视频文件过大 ({size_mb:.1f}MB)，超过 QQ 官方机器人上传限制，已跳过"
                        )
                        continue
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
            if warnings := result.extra.get("limit_warnings"):
                for w in warnings:
                    prefix = "\n" if node3_parts else ""
                    node3_parts.append(f"{prefix}{w}")
            node3 = [Comp.Plain("".join(node3_parts))] if node3_parts else []
            nodes = []
            if node1:
                nodes.append(node1)
            if node2:
                nodes.append(node2)
            if node3:
                nodes.append(node3)
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

    async def _send_qqofficial_output(
        self,
        event: AstrMessageEvent,
        header: str,
        nodes_content: list[list],
    ):
        """为 QQ Official Bot 合并所有非视频内容为一条消息。

        QQ Official Bot 不支持 Comp.Nodes（合并转发），因此将
        header + 所有文本 + 所有图片合并到一条 chain_result 中发送。
        视频由 _try_send_media() 单独处理。
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
        """检测消息中是否包含 JSON 卡片 / 小程序卡片 / Ark 消息。"""
        if not hasattr(event, "message_obj") or not hasattr(event.message_obj, "message"):
            return False
        for c in event.message_obj.message:
            if isinstance(c, dict):
                t = str(c.get("type", "")).lower()
                if t == "reply":
                    continue
                # JSON 卡片、小程序卡片、Ark 消息
                if t and any(kw in t for kw in ("json", "mini", "program", "ark", "app")):
                    return True
                continue
            if isinstance(c, Comp.Json):
                return True
            t = str(getattr(c, "type", "")).lower()
            if t and any(kw in t for kw in ("json", "mini", "program", "ark", "app")):
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
                    t = str(c.get("type", "")).lower()
                    if t == "reply":
                        continue
                    # JSON 卡片、小程序卡片、Ark 消息
                    if t and any(kw in t for kw in ("json", "mini", "program", "ark", "app")):
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
                    # QQ 小程序卡片: meta → detail_1 / detail / news / music → qqdocurl / url / jumpUrl
                    meta = obj.get("meta", {})
                    if isinstance(meta, dict):
                        for dk in ("detail_1", "detail", "news", "music"):
                            d = meta.get(dk, {})
                            if isinstance(d, dict):
                                for uk in ("qqdocurl", "url", "jumpUrl"):
                                    v = d.get(uk, "")
                                    if isinstance(v, str) and v:
                                        found.append(v)
                    # 小程序卡片顶层可能直接有 jumpUrl / url
                    for uk in ("qqdocurl", "jumpUrl", "url"):
                        v = obj.get(uk, "")
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
