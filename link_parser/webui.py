"""插件网页控制面板（views/rika）的后端接口层。

页面在 ``views/rika/``，通过 AstrBot 4.x 的 ``window.AstrBotPluginView`` bridge 调用本模块注册的接口。
接口分工：

- 本模块只做「参数提取 → 校验 → 调用运行时服务与 :mod:`link_parser.config` → 返回 JSON」，
  不重复实现解析、渲染或账号登录业务逻辑。
- 路由统一带插件名前缀（``/astrbot_plugin_rika_share/...``）；页面侧通过 bridge 传入去掉前缀的相对路径。
- 页面运行在受限 iframe 中，但后端仍按不可信输入处理：
  配置更新仅接受 :data:`~link_parser.config.CONFIG_META` 白名单内的键，并通过
  :func:`~link_parser.config.coerce_value` 做类型与范围校验；状态接口只暴露脱敏后的摘要，不返回任何密钥或 Cookie 原文。
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime
import re
from pathlib import Path
import time
from typing import Any, Callable

from astrbot.api import logger

from .config import (
    config_meta_payload,
    get_config,
    get_global_config,
    normalize_scope_id,
    platform_options,
    scoped_config_for,
    verify_schema_alignment,
)
from .services.card_render import ShareCardRenderer, iter_styles
from .services.card_render.preview import (
    PREVIEW_SAMPLE_SPECS,
    build_preview_sample,
    preview_images_for,
)
from .services.card_render.toolkit import FontBook
from .utils.persona import DEFAULT_BRAND_NAME, format_brand_name

PLUGIN_NAME = "astrbot_plugin_rika_share"

#: 调试接口接受的链接长度上限
MAX_URL_LENGTH = 2048

#: 调试日志标识的合法形态（纯十六进制，防目录穿越）
_DEBUG_TOKEN_RE = re.compile(r"[0-9a-f]{12}")


def _json_response(data: Any, status_code: int = 200):
    from astrbot.api.web import json_response

    return json_response(data, status_code=status_code)


def _error(message: str, status_code: int = 400):
    from astrbot.api.web import error_response

    return error_response(message, status_code=status_code)


def _plugin_version() -> str:
    """读取 ``metadata.yaml`` 中的版本号。"""
    try:
        path = Path(__file__).resolve().parent.parent / "metadata.yaml"
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("version:"):
                return line.split(":", 1)[1].strip().strip('"').strip("'")
    except Exception:  # noqa: BLE001 - 版本号仅作展示
        logger.debug("[link_parser] 读取 metadata.yaml 版本号失败", exc_info=True)
    return ""


def _registered_style_cards() -> list[dict[str, str]]:
    """读取卡片样式元数据，供前端渲染可视化样式选择器。"""
    try:
        from .services.card_render.styles import iter_styles

        return [
            {
                "name": spec.name,
                "display_name": spec.display_name,
                "description": spec.description,
            }
            for spec in iter_styles()
        ]
    except Exception:  # noqa: BLE001 - 样式注册表异常不影响设置页可用
        logger.debug("[link_parser] 读取卡片样式详情失败", exc_info=True)
        return [
            {"name": "standard", "display_name": "标准横幅", "description": "顶部全宽封面 + 纵向信息流"},
            {"name": "magazine", "display_name": "双栏杂志", "description": "封面左置、标题作者右置"},
            {"name": "immersive", "display_name": "沉浸全屏", "description": "封面铺满整卡，无图回退 standard"},
            {"name": "feed", "display_name": "社交动态", "description": "作者行置顶，媒体内嵌为圆角块"},
        ]


def _ensure_current_style(payload: dict[str, Any], current: Any) -> None:
    """若当前样式不在动态下拉中，补充一条提示项防止选择器空白。"""
    name = str(current or "").strip()
    if not name:
        return
    for item in payload.get("items") or []:
        if item.get("key") != "RENDER_STYLE":
            continue
        options = item.setdefault("options", [])
        if name in options:
            return
        options.append(name)
        item.setdefault("labels", []).append(f"{name}（未注册，渲染时回退 standard）")
        return


def _scan_dir_stats(directory: Path | None) -> tuple[int, int]:
    """统计目录下的文件数与总字节数（在后台线程运行，避免阻塞事件循环）。"""
    if directory is None or not directory.exists():
        return 0, 0
    files = 0
    total_bytes = 0
    try:
        for entry in directory.rglob("*"):
            try:
                if entry.is_file():
                    files += 1
                    total_bytes += entry.stat().st_size
            except OSError:
                continue
    except OSError:
        return files, total_bytes
    return files, total_bytes


def _serialize_bili_status(bili: Any) -> dict[str, Any]:
    """构造脱敏的 B 站账号状态摘要（不返回 Cookie 原文）。"""
    if bili is None:
        return {
            "available": False,
            "has_cookie": False,
            "refreshable": False,
            "monitor_running": False,
            "valid": None,
            "username": "",
            "uid": 0,
            "vip": False,
            "error": "账号服务未初始化",
            "last_check_time": "",
            "status_text": "B站账号服务未初始化",
            "qr": {"active": False, "state": "idle", "message": "", "remaining_seconds": 0},
        }

    parser_cookie = ""
    getter = getattr(bili, "_parser_cookie", None)
    if callable(getter):
        try:
            parser_cookie = getter() or ""
        except Exception:  # noqa: BLE001
            parser_cookie = ""

    has_cookie = bool(getattr(bili, "_cookie", "") or parser_cookie)
    refreshable_fn = getattr(bili, "is_refreshable", None)
    refreshable = bool(refreshable_fn()) if callable(refreshable_fn) else False
    qr_fn = getattr(bili, "web_qr_snapshot", None)
    qr_snapshot = qr_fn() if callable(qr_fn) else {"active": False, "state": "idle", "message": "", "remaining_seconds": 0}
    last_status = getattr(bili, "_last_status", None)
    last_status_dict = last_status if isinstance(last_status, dict) else {}
    last_time = getattr(bili, "_last_check_time", None)
    last_time_str = (
        last_time.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(last_time, datetime)
        else ""
    )

    try:
        status_text = bili.status_text()
    except Exception:  # noqa: BLE001
        status_text = ""

    return {
        "available": True,
        "has_cookie": has_cookie,
        "refreshable": refreshable,
        "monitor_running": bool(getattr(bili, "_monitor_running", False)),
        "valid": last_status_dict.get("valid") if last_status_dict else None,
        "username": str(last_status_dict.get("username") or ""),
        "uid": int(last_status_dict.get("uid") or 0),
        "vip": bool(last_status_dict.get("vip", False)),
        "error": str(last_status_dict.get("error") or ""),
        "last_check_time": last_time_str,
        "status_text": status_text,
        "qr": qr_snapshot,
    }


async def _collect_cache_stats(plugin: Any) -> dict[str, Any]:
    """收集磁盘缓存与内存缓存统计信息。"""
    pconfig = get_config()
    cache_dir = getattr(plugin, "cache_dir", None)
    webpage_dir = getattr(plugin, "webpage_dir", None)
    (cache_files, cache_bytes), (webpage_files, webpage_bytes) = await asyncio.gather(
        asyncio.to_thread(_scan_dir_stats, cache_dir),
        asyncio.to_thread(_scan_dir_stats, webpage_dir),
    )
    content_cache = getattr(plugin, "_content_cache", None)
    identity_cache = getattr(plugin, "_identity_cache", None)
    webpage_links = getattr(plugin, "_webpage_links", None)
    return {
        "ttl_hours": pconfig.CACHE_TTL_HOURS,
        "cleanup_interval_minutes": pconfig.CACHE_CLEANUP_INTERVAL_MINUTES,
        "files": cache_files + webpage_files,
        "bytes": cache_bytes + webpage_bytes,
        "cache_files": cache_files,
        "cache_bytes": cache_bytes,
        "webpage_files": webpage_files,
        "webpage_bytes": webpage_bytes,
        "memory_entries": len(content_cache or {}) + len(identity_cache or {}),
        "active_webpage_links": len(webpage_links or {}),
    }


def read_schema_problems() -> list[str]:
    """读取 ``_conf_schema.json`` 并校验它与 :data:`CONFIG_META` 的一致性。"""
    try:
        import json

        path = Path(__file__).resolve().parent.parent / "_conf_schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 自检失败不应影响页面可用
        logger.warning("[link_parser] 无法读取 _conf_schema.json，跳过一致性自检", exc_info=True)
        return []
    problems = verify_schema_alignment(schema)
    for problem in problems:
        logger.warning(f"[link_parser] 配置 schema 不一致：{problem}")
    return problems


def _safe_query_scope() -> str:
    """读取可选 ``scope`` 查询参数；无绑定请求上下文时返回全局空串。"""
    try:
        from astrbot.api.web import request

        return normalize_scope_id(request.query.get("scope"))
    except Exception:
        return ""


async def _collect_group_catalog(plugin: Any, global_cfg: Any) -> list[dict[str, Any]]:
    """汇总已保存的分群配置、近期活跃群与 AstrBot 会话库中的已知群组。"""
    entries: dict[str, dict[str, Any]] = {}

    def _ensure(scope_id: str) -> dict[str, Any]:
        node = entries.get(scope_id)
        if node is not None:
            return node
        parts = scope_id.split(":", 2)
        platform_id = parts[0] if len(parts) == 3 else ""
        gid = parts[2] if len(parts) == 3 else (scope_id.split(":", 1)[1] if scope_id.startswith("group:") else "")
        node = {
            "scope_id": scope_id,
            "label": "",
            "alias_name": "",
            "platform_id": platform_id,
            "group_id": gid,
            "has_override": False,
            "override_keys": [],
            "override_count": 0,
            "updated_at": "",
            "last_seen": 0.0,
        }
        entries[scope_id] = node
        return node

    for prof in global_cfg.groups.list_profiles():
        sid = prof["scope_id"]
        row = _ensure(sid)
        row["has_override"] = prof["override_count"] > 0
        row["override_keys"] = prof["override_keys"]
        row["override_count"] = prof["override_count"]
        row["updated_at"] = prof["updated_at"]
        if prof["label"]:
            row["label"] = prof["label"]

    for seen in global_cfg.groups.list_seen_groups():
        sid = normalize_scope_id(seen.get("umo"))
        if not sid:
            continue
        row = _ensure(sid)
        if seen.get("platform_id") and not row["platform_id"]:
            row["platform_id"] = seen["platform_id"]
        if seen.get("group_id") and not row["group_id"]:
            row["group_id"] = seen["group_id"]
        if seen.get("name") and not row["alias_name"]:
            row["alias_name"] = seen["name"]
        row["last_seen"] = max(row["last_seen"], float(seen.get("last_seen") or 0.0))

    ctx = getattr(plugin, "context", None)
    db_getter = getattr(ctx, "get_db", None)
    if callable(db_getter):
        try:
            db = db_getter()
            if db is not None:
                alias_map: dict[str, str] = {}
                get_aliases = getattr(db, "get_umo_aliases", None)
                if callable(get_aliases):
                    aliases = await get_aliases()
                    for al in aliases or ():
                        umo = str(getattr(al, "umo", "") or "").strip()
                        name = str(
                            getattr(al, "user_alias", "") or getattr(al, "auto_name", "") or ""
                        ).strip()
                        if umo and name:
                            alias_map[umo] = name
                            if ":group:" in umo.lower() or ":groupmessage:" in umo.lower():
                                row = _ensure(umo)
                                row["alias_name"] = name

                get_convs = getattr(db, "get_all_conversations", None)
                if callable(get_convs):
                    convs = await get_convs(page=1, page_size=200)
                    for cv in convs or ():
                        umo = str(getattr(cv, "user_id", "") or "").strip()
                        if umo and (":group:" in umo.lower() or ":groupmessage:" in umo.lower()):
                            row = _ensure(umo)
                            if umo in alias_map and not row["alias_name"]:
                                row["alias_name"] = alias_map[umo]
        except Exception:
            logger.debug("[link_parser] 读取 AstrBot 群会话列表失败，跳过合并", exc_info=True)

    result: list[dict[str, Any]] = []
    for row in entries.values():
        display = row["label"] or row["alias_name"] or (
            f"群 {row['group_id']}" if row["group_id"] else row["scope_id"]
        )
        row["display_name"] = display
        result.append(row)

    result.sort(
        key=lambda item: (
            0 if item["has_override"] else 1,
            -float(item.get("last_seen") or 0),
            item["scope_id"],
        )
    )
    return result


class WebUIApi:
    """插件网页控制面板的接口集合。"""

    def __init__(self, plugin: Any):
        self.plugin = plugin
        self._font_book_cache: dict[str, FontBook] = {}
        self._style_thumb_cache: dict[tuple[Any, ...], str] = {}

    # ==================== 注册 ==================== #

    def register(self) -> None:
        context = self.plugin.context
        routes: tuple[tuple[str, Callable[..., Any], tuple[str, ...], str], ...] = (
            ("/config", self.get_config, ("GET",), "读取全部配置项与元数据"),
            ("/config", self.save_config, ("POST",), "保存配置项并热更新运行时"),
            ("/config/reset", self.reset_config, ("POST",), "恢复默认配置"),
            ("/groups", self.groups_list, ("GET",), "列出已知群组及分群覆写状态"),
            ("/groups", self.groups_manage, ("POST",), "新建、重命名或移除分群配置"),
            ("/overview", self.get_overview, ("GET",), "获取插件运行状态与资源总览"),
            ("/cache/clear", self.clear_cache, ("POST",), "清理插件磁盘与内存缓存"),
            ("/bili/check", self.check_bili_cookie, ("POST",), "立即检测B站Cookie有效性"),
            ("/bili/login", self.bili_qr_login, ("POST",), "生成或取消B站WebUI扫码登录二维码"),
            ("/bili/status", self.bili_status, ("GET",), "查询B站登录态并轮询扫码结果"),
            ("/preview/card", self.preview_card, ("POST",), "实时渲染一张卡片预览图"),
            ("/preview/styles", self.preview_styles, ("GET",), "渲染全部已注册卡片样式缩略图"),
            ("/debug/run", self.debug_run, ("POST",), "对链接执行解析诊断并生成日志"),
            ("/debug/log", self.debug_log, ("GET",), "下载链接解析调试日志"),
        )
        for suffix, handler, methods, desc in routes:
            context.register_web_api(f"/{PLUGIN_NAME}{suffix}", handler, list(methods), desc)

    # ==================== 总览与运维 ==================== #

    async def get_overview(self):
        scope = _safe_query_scope()
        global_cfg = get_global_config()
        _, pconfig = global_cfg.scoped(umo=scope) if scope else ("", global_cfg)
        renderer = (
            self.plugin._renderer_for(pconfig)
            if hasattr(self.plugin, "_renderer_for")
            else getattr(self.plugin, "_renderer", None)
        )
        cf_client = getattr(self.plugin, "_cloudflare_client", None)
        cache_stats = await _collect_cache_stats(self.plugin)
        configured_groups = sum(1 for p in global_cfg.groups.list_profiles() if p["override_count"] > 0)

        return _json_response(
            {
                "version": _plugin_version(),
                "scope": scope,
                "configured_groups": configured_groups,
                "problems": read_schema_problems(),
                "platforms": platform_options(pconfig),
                "styles": _registered_style_cards(),
                "renderer": {
                    "enabled": bool(getattr(renderer, "enabled", pconfig.RENDER_ENABLED)),
                    "style": pconfig.RENDER_STYLE,
                    "theme": pconfig.RENDER_THEME,
                    "width": pconfig.RENDER_WIDTH,
                    "cover_full_size": pconfig.RENDER_COVER_FULL_SIZE,
                    "persona_watermark": pconfig.RENDER_PERSONA_WATERMARK,
                    "brand_name": pconfig.RENDER_BRAND_NAME,
                },
                "fallback": {
                    "cloudflare_enabled": pconfig.CLOUDFLARE_FALLBACK_ENABLED,
                    "cloudflare_configured": bool(
                        cf_client and getattr(cf_client, "is_configured", False)
                    ),
                    "debug_log_enabled": pconfig.DEBUG_LOG_ENABLED,
                    "send_error_messages": pconfig.SEND_ERROR_MESSAGES,
                },
                "webpage_share": {
                    "enabled": pconfig.WEBPAGE_FALLBACK_ENABLED,
                    "tdocs_jump": pconfig.WEBPAGE_TDOCS_JUMP,
                    "public_url_configured": bool(
                        getattr(self.plugin, "_get_callback_base", lambda: "")()
                    ),
                    "active_links": cache_stats["active_webpage_links"],
                },
                "bili": _serialize_bili_status(getattr(self.plugin, "bili", None)),
                "cache": cache_stats,
                "appearance": {
                    "theme": pconfig.WEBUI_THEME,
                    "color_mode": pconfig.WEBUI_COLOR_MODE,
                },
            }
        )

    async def clear_cache(self):
        try:
            cleaned = await self.plugin.clear_all_caches()
            cache_stats = await _collect_cache_stats(self.plugin)
            return _json_response({"cleaned": cleaned, "cache": cache_stats})
        except Exception as exc:  # noqa: BLE001
            logger.exception("[link_parser] WebUI 清理缓存失败")
            return _error(f"清理缓存失败：{str(exc)[:160]}", status_code=500)

    async def check_bili_cookie(self):
        bili = getattr(self.plugin, "bili", None)
        if bili is None:
            return _error("B站账号服务未初始化", status_code=503)

        live_cookie = ""
        getter = getattr(bili, "_parser_cookie", None)
        if callable(getter):
            try:
                live_cookie = getter() or ""
            except Exception:  # noqa: BLE001
                live_cookie = ""
        if live_cookie and not getattr(bili, "_cookie", ""):
            bili._cookie = live_cookie

        if not getattr(bili, "_cookie", ""):
            return _json_response(
                {
                    "checked": False,
                    "message": "尚未配置B站 Cookie，请点击「扫码登录」或填写 BILI_CK",
                    "bili": _serialize_bili_status(bili),
                }
            )

        try:
            result = await bili.check_cookie_valid()
            bili._last_status = result
            bili._last_check_time = datetime.now()
            bili._was_invalid = not bool(result.get("valid"))
            saver = getattr(bili, "_save_last_status", None)
            if callable(saver):
                await saver()
            return _json_response(
                {
                    "checked": True,
                    "result": result,
                    "bili": _serialize_bili_status(bili),
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("[link_parser] WebUI 检测 B站 Cookie 失败")
            return _error(f"检测B站 Cookie 失败：{str(exc)[:160]}", status_code=500)

    async def bili_qr_login(self):
        """生成或取消 B站 WebUI 扫码登录二维码。"""
        from astrbot.api.web import request

        bili = getattr(self.plugin, "bili", None)
        if bili is None:
            return _error("B站账号服务未初始化", status_code=503)

        body = await request.json(default={}) or {}
        action = str(body.get("action") or "start").strip().lower() if isinstance(body, dict) else "start"
        if action == "cancel":
            qr = bili.cancel_web_qr_login()
            return _json_response({"qr": qr, "bili": _serialize_bili_status(bili)})

        try:
            qr = await bili.start_web_qr_login()
            return _json_response({"qr": qr, "bili": _serialize_bili_status(bili)})
        except Exception as exc:  # noqa: BLE001
            logger.exception("[link_parser] WebUI 生成 B站登录二维码失败")
            return _error(f"获取登录二维码失败：{str(exc)[:160]}", status_code=502)

    async def bili_status(self):
        """返回当前 B站登录状态；如传入或存在进行中的扫码会话则轮询一次状态。"""
        from astrbot.api.web import request

        bili = getattr(self.plugin, "bili", None)
        if bili is None:
            return _error("B站账号服务未初始化", status_code=503)

        qrcode_key = str(request.query.get("qrcode_key") or "").strip() or None
        try:
            qr = await bili.poll_web_qr_status(qrcode_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[link_parser] 轮询 B站扫码状态异常", exc_info=True)
            qr = {
                **bili.web_qr_snapshot(),
                "message": f"轮询异常：{str(exc)[:120]}",
            }
        return _json_response({"qr": qr, "bili": _serialize_bili_status(bili)})

    # ==================== 实时卡片预览 ==================== #

    def _get_font_book(self, font_path: str | None) -> FontBook:
        key = str(font_path or "").strip()
        book = self._font_book_cache.get(key)
        if book is None:
            if len(self._font_book_cache) >= 6:
                self._font_book_cache.clear()
            book = FontBook(key or None)
            self._font_book_cache[key] = book
        return book

    def _make_preview_renderer(
        self,
        *,
        style: str,
        theme: str,
        width: int,
        cover_full_size: bool,
        font_path: str | None,
    ) -> ShareCardRenderer:
        cache_dir = Path(getattr(self.plugin, "cache_dir", "."))
        renderer = ShareCardRenderer(
            cache_dir,
            enabled=True,
            width=width,
            theme=theme,
            font_path=font_path or None,
            cover_full_size=cover_full_size,
            style=style,
        )
        renderer._font_book = self._get_font_book(font_path)
        return renderer

    @staticmethod
    def _preview_watermark(
        persona_watermark: bool,
        persona_name: str,
        brand_name: str = DEFAULT_BRAND_NAME,
    ) -> str:
        fallback_brand = str(brand_name or "").strip()[:16] or DEFAULT_BRAND_NAME
        if not persona_watermark:
            return fallback_brand
        return format_brand_name(persona_name or "达妮娅", default=fallback_brand)

    async def preview_card(self):
        """使用当前未保存或已生效参数实时渲染单张卡片预览（内存 PNG → base64）。"""
        from astrbot.api.web import request

        body = await request.json(default={}) or {}
        if not isinstance(body, dict):
            return _error("请求参数格式不正确")

        pconfig = get_config()
        sample_id = str(body.get("sample") or "video").strip().lower()
        style = str(body.get("style") or pconfig.RENDER_STYLE).strip().lower() or pconfig.RENDER_STYLE
        theme = str(body.get("theme") or pconfig.RENDER_THEME).strip().lower()
        if theme not in {"dark", "light"}:
            theme = "dark"
        try:
            width = max(520, min(1080, int(body.get("width", pconfig.RENDER_WIDTH))))
        except (TypeError, ValueError):
            width = pconfig.RENDER_WIDTH
        cover_full_size = bool(body.get("cover_full_size", pconfig.RENDER_COVER_FULL_SIZE))
        font_path = str(body.get("font_path") if "font_path" in body else pconfig.RENDER_FONT_PATH).strip()
        persona_watermark = bool(body.get("persona_watermark", pconfig.RENDER_PERSONA_WATERMARK))
        persona_name = str(body.get("persona_name") or "达妮娅").strip()
        brand_name = str(body.get("brand_name") if "brand_name" in body else pconfig.RENDER_BRAND_NAME).strip()
        watermark = self._preview_watermark(persona_watermark, persona_name, brand_name)

        try:
            started = time.monotonic()
            asset_dir = Path(self.plugin.cache_dir) / "_preview_assets"
            resolved_sample, sample_result = await asyncio.to_thread(
                build_preview_sample, sample_id, asset_dir
            )
            images = await asyncio.to_thread(preview_images_for, resolved_sample, asset_dir)
            renderer = self._make_preview_renderer(
                style=style,
                theme=theme,
                width=width,
                cover_full_size=cover_full_size,
                font_path=font_path,
            )
            png_bytes, used_style = await renderer.render_preview_png(
                sample_result, images, watermark=watermark
            )
            render_ms = round((time.monotonic() - started) * 1000)
            b64 = base64.b64encode(png_bytes).decode("ascii")
            return _json_response(
                {
                    "image": f"data:image/png;base64,{b64}",
                    "sample": resolved_sample,
                    "requested_style": style,
                    "used_style": used_style,
                    "fallback": used_style != style,
                    "theme": theme,
                    "width": renderer.width,
                    "watermark": watermark,
                    "render_ms": render_ms,
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("[link_parser] 实时卡片预览渲染失败")
            return _error(f"卡片预览渲染失败：{str(exc)[:160]}", status_code=500)

    async def preview_styles(self):
        """渲染全部已注册样式的真实样貌缩略图（含后续新增自定义样式）。"""
        from astrbot.api.web import request

        pconfig = get_config()
        theme = str(request.query.get("theme") or pconfig.RENDER_THEME).strip().lower()
        if theme not in {"dark", "light"}:
            theme = "dark"
        persona_raw = str(request.query.get("persona_watermark") or "").strip().lower()
        persona_watermark = (
            persona_raw in {"1", "true", "yes"}
            if persona_raw
            else pconfig.RENDER_PERSONA_WATERMARK
        )
        persona_name = str(request.query.get("persona_name") or "达妮娅").strip()
        brand_name = str(request.query.get("brand_name") or pconfig.RENDER_BRAND_NAME).strip()
        watermark = self._preview_watermark(persona_watermark, persona_name, brand_name)
        font_path = pconfig.RENDER_FONT_PATH

        try:
            asset_dir = Path(self.plugin.cache_dir) / "_preview_assets"
            _, sample_result = await asyncio.to_thread(
                build_preview_sample, "video", asset_dir
            )
            images = await asyncio.to_thread(preview_images_for, "video", asset_dir)

            items: list[dict[str, str]] = []
            for spec in iter_styles():
                cache_key = (spec.name, spec.version, theme, watermark, font_path)
                data_url = self._style_thumb_cache.get(cache_key)
                if data_url is None:
                    renderer = self._make_preview_renderer(
                        style=spec.name,
                        theme=theme,
                        width=560,
                        cover_full_size=False,
                        font_path=font_path,
                    )
                    png_bytes, _ = await renderer.render_preview_png(
                        sample_result, images, watermark=watermark
                    )
                    data_url = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
                    if len(self._style_thumb_cache) >= 48:
                        self._style_thumb_cache.clear()
                    self._style_thumb_cache[cache_key] = data_url
                items.append(
                    {
                        "name": spec.name,
                        "display_name": spec.display_name,
                        "description": spec.description,
                        "image": data_url,
                    }
                )
            return _json_response({"theme": theme, "watermark": watermark, "styles": items})
        except Exception as exc:  # noqa: BLE001
            logger.exception("[link_parser] 生成样式列表预览失败")
            return _error(f"样式预览生成失败：{str(exc)[:160]}", status_code=500)

    # ==================== 配置与分群管理 ==================== #

    async def groups_list(self):
        global_cfg = get_global_config()
        catalog = await _collect_group_catalog(self.plugin, global_cfg)
        return _json_response({"groups": catalog})

    async def groups_manage(self):
        from astrbot.api.web import request

        body = await request.json(default={}) or {}
        action = str(body.get("action") or "").strip().lower()
        scope = normalize_scope_id(body.get("scope") or body.get("scope_id"))
        if not scope:
            return _error("请提供有效的群号或 UMO")

        global_cfg = get_global_config()
        if action == "delete":
            removed = global_cfg.groups.delete_profile(scope)
            catalog = await _collect_group_catalog(self.plugin, global_cfg)
            return _json_response({"removed": removed, "groups": catalog})

        if action in {"create", "upsert", "rename"}:
            label = body.get("label")
            _, errors, _ = global_cfg.groups.upsert_overrides(
                scope,
                {},
                label="" if label is None and action == "create" else str(label or ""),
            )
            if action == "create" and not global_cfg.groups.get_profile(scope)["label"]:
                gid = scope.split(":", 2)[-1] if ":" in scope else scope
                global_cfg.groups.upsert_overrides(scope, {}, label=f"群 {gid}")
            catalog = await _collect_group_catalog(self.plugin, global_cfg)
            return _json_response({"scope": scope, "errors": errors, "groups": catalog})

        return _error(f"不支持的群组操作：{action}")

    async def _build_config_response(self, scope: str) -> dict[str, Any]:
        global_cfg = get_global_config()
        _, effective_cfg = global_cfg.scoped(umo=scope) if scope else ("", global_cfg)
        payload = config_meta_payload()
        payload["scope"] = scope
        payload["global_values"] = global_cfg.current_values()
        payload["values"] = effective_cfg.current_values()
        profile = (
            global_cfg.groups.get_profile(scope)
            if scope
            else {"label": "全局默认", "override_keys": []}
        )
        payload["scope_label"] = profile.get("label") or ("全局默认" if not scope else scope)
        payload["override_keys"] = list(profile.get("override_keys") or [])
        payload["group_profiles"] = await _collect_group_catalog(self.plugin, global_cfg)
        _ensure_current_style(payload, payload["values"].get("RENDER_STYLE"))
        payload["problems"] = read_schema_problems()
        payload["version"] = _plugin_version()
        payload["platforms"] = platform_options(effective_cfg)
        payload["styles"] = _registered_style_cards()
        payload["preview_samples"] = list(PREVIEW_SAMPLE_SPECS)
        return payload

    async def get_config(self):
        scope = _safe_query_scope()
        return _json_response(await self._build_config_response(scope))

    async def _apply_and_respond(
        self,
        pconfig: Any,
        changed: list[str],
        errors: list[str],
        *,
        fail_prefix: str,
        scope: str = "",
    ):
        """同步应用运行时配置并返回标准保存响应。"""
        runtime_ok = True
        runtime: dict[str, Any] = {}
        if changed and not scope:
            try:
                runtime = await self.plugin.apply_runtime_config()
            except Exception as exc:  # noqa: BLE001 - 热更新失败不能吞掉已保存的配置
                runtime_ok = False
                logger.warning("[link_parser] 应用新配置失败", exc_info=True)
                errors.append(f"{fail_prefix}，但运行时热更新失败：{str(exc)[:120]}")
        global_cfg = get_global_config()
        _, effective_cfg = global_cfg.scoped(umo=scope) if scope else ("", pconfig)
        profile = (
            global_cfg.groups.get_profile(scope)
            if scope
            else {"label": "全局默认", "override_keys": []}
        )
        return _json_response(
            {
                "scope": scope,
                "changed": changed,
                "errors": errors,
                "runtime_ok": runtime_ok,
                "runtime": runtime,
                "values": effective_cfg.current_values(),
                "global_values": global_cfg.current_values(),
                "override_keys": list(profile.get("override_keys") or []),
                "scope_label": profile.get("label") or ("全局默认" if not scope else scope),
                "group_profiles": await _collect_group_catalog(self.plugin, global_cfg),
            }
        )

    async def save_config(self):
        from astrbot.api.web import request

        body = await request.json(default={}) or {}
        if not isinstance(body, dict):
            return _error("提交数据格式无效")
        scope = normalize_scope_id(body.get("scope"))
        values = body.get("values") if isinstance(body.get("values"), dict) else {}
        unset = body.get("unset") if isinstance(body.get("unset"), list) else []
        label = body.get("label")

        if scope:
            if not values and not unset and label is None:
                return _error("没有需要保存的分群配置项")
            global_cfg = get_global_config()
            changed, errors, _ = global_cfg.groups.upsert_overrides(
                scope,
                values,
                unset=[str(k) for k in unset],
                label=str(label) if label is not None else None,
            )
            return await self._apply_and_respond(
                global_cfg, changed, errors, fail_prefix="分群配置已保存", scope=scope
            )

        if not values:
            return _error("没有需要保存的配置项")

        pconfig = get_global_config()
        changed, errors = pconfig.apply_updates(values)
        return await self._apply_and_respond(
            pconfig, changed, errors, fail_prefix="配置已保存"
        )

    async def reset_config(self):
        from astrbot.api.web import request

        body = await request.json(default={}) or {}
        scope = normalize_scope_id(body.get("scope") if isinstance(body, dict) else "")
        global_cfg = get_global_config()
        if scope:
            removed = global_cfg.groups.delete_profile(scope)
            return await self._apply_and_respond(
                global_cfg,
                ["__reset_group__"] if removed else [],
                [],
                fail_prefix="已恢复继承全局默认",
                scope=scope,
            )

        changed = global_cfg.reset_to_defaults()
        return await self._apply_and_respond(
            pconfig=global_cfg,
            changed=changed,
            errors=[],
            fail_prefix="已恢复默认",
        )

    # ==================== 链接调试 ==================== #

    async def debug_run(self):
        """对提交的链接跑一遍完整解析流程，返回步骤结果 + 日志正文。"""
        from astrbot.api.web import request

        from .services.debug_probe import run_debug_probe

        body = await request.json(default={}) or {}
        url = str(body.get("url") or "").strip()
        if not url:
            return _error("请填写要测试的链接")
        if len(url) > MAX_URL_LENGTH:
            return _error(f"链接过长（上限 {MAX_URL_LENGTH} 字符）")
        if not url.lower().startswith(("http://", "https://")):
            return _error("链接需要以 http:// 或 https:// 开头")

        download_media = body.get("download_media", True) is not False
        render_card = body.get("render_card", True) is not False
        scope = normalize_scope_id(body.get("scope"))

        try:
            with scoped_config_for(umo=scope):
                report = await run_debug_probe(
                    self.plugin,
                    url,
                    download_media=download_media,
                    render_card=render_card,
                )
        except Exception as exc:  # noqa: BLE001 - 调试接口本身也不能把栈抛给页面
            logger.exception("[link_parser] 调试流程异常")
            return _error(f"调试流程异常：{str(exc)[:200]}", status_code=500)
        payload = report.payload()
        payload["scope"] = scope
        if scope:
            profile = get_global_config().groups.get_profile(scope)
            payload["scope_label"] = profile.get("label") or scope
        else:
            payload["scope_label"] = ""
        return _json_response(payload)

    async def debug_log(self):
        """下载调试日志文本。``token`` 只允许十六进制，防止目录穿越。"""
        from astrbot.api.web import file_response, request

        from .services.debug_probe import debug_dir

        token = str(request.query.get("token") or "").strip().lower()
        if not _DEBUG_TOKEN_RE.fullmatch(token):
            return _error("无效的日志标识")

        directory = debug_dir(self.plugin)
        matches = sorted(directory.glob(f"debug_*_{token}.log"), reverse=True)
        if not matches:
            return _error("日志已不存在（可能已被缓存清理），请重新测试")
        path = matches[0]
        return file_response(
            path,
            filename=f"rika_debug_{token}.log",
            content_type="text/plain; charset=utf-8",
        )
