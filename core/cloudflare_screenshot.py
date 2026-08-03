"""Cloudflare Browser Rendering 截图模块

使用 Cloudflare Browser Rendering API 的 screenshot 端点，
将网页渲染为图片并保存到本地。

实现参考：
- astrbot_plugin_cloudflare_browser_run 的 API 调用模式（key 转换、错误处理、脱敏）
- Cloudflare 官方 /screenshot 文档（screenshotOptions / viewport / gotoOptions 等参数）
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import re
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import aiohttp
from astrbot.api import logger

API_BASE = "https://api.cloudflare.com/client/v4"
SCREENSHOT_ENDPOINT = f"{API_BASE}/accounts/{{account_id}}/browser-rendering/screenshot"

# gotoOptions.waitUntil 可选值（官方文档）
WAIT_UNTIL_VALUES = ("load", "domcontentloaded", "networkidle0", "networkidle2")
# screenshotOptions.type 可选值
SCREENSHOT_TYPES = ("png", "jpeg")

# 设置页分组：Cloudflare 配置项 -> 分组名（与 _conf_schema.json 保持一致）
_CF_KEY_GROUPS: dict[str, str] = {
    "CLOUDFLARE_FALLBACK_ENABLED": "Cloudflare 基础设置",
    "CLOUDFLARE_ACCOUNT_ID": "Cloudflare 基础设置",
    "CLOUDFLARE_API_TOKEN": "Cloudflare 基础设置",
    "CLOUDFLARE_TIMEOUT": "Cloudflare 基础设置",
    "CLOUDFLARE_CACHE_TTL": "Cloudflare 基础设置",
    "CLOUDFLARE_BLACKLIST": "Cloudflare 基础设置",
    "CLOUDFLARE_VIEWPORT_WIDTH": "Cloudflare 截图设置",
    "CLOUDFLARE_VIEWPORT_HEIGHT": "Cloudflare 截图设置",
    "CLOUDFLARE_WAIT_UNTIL": "Cloudflare 截图设置",
    "CLOUDFLARE_GOTO_TIMEOUT": "Cloudflare 截图设置",
    "CLOUDFLARE_FULL_PAGE": "Cloudflare 截图设置",
    "CLOUDFLARE_DEVICE_SCALE_FACTOR": "Cloudflare 截图设置",
    "CLOUDFLARE_SCREENSHOT_TYPE": "Cloudflare 截图设置",
    "CLOUDFLARE_SCREENSHOT_QUALITY": "Cloudflare 截图设置",
    "CLOUDFLARE_OMIT_BACKGROUND": "Cloudflare 截图设置",
    "CLOUDFLARE_SELECTOR": "Cloudflare 截图设置",
    "CLOUDFLARE_WAIT_FOR_SELECTOR": "Cloudflare 截图设置",
    "CLOUDFLARE_WAIT_FOR_TIMEOUT": "Cloudflare 截图设置",
    "CLOUDFLARE_USER_AGENT": "Cloudflare 截图设置",
    "CLOUDFLARE_EXTRA_HEADERS": "Cloudflare 截图设置",
    "CLOUDFLARE_COOKIES": "Cloudflare 截图设置",
}

# 各 Cloudflare 配置项默认值（与 _conf_schema.json 保持一致），用于扁平旧值回退判断
_CF_KEY_DEFAULTS: dict[str, Any] = {
    "CLOUDFLARE_FALLBACK_ENABLED": False,
    "CLOUDFLARE_ACCOUNT_ID": "",
    "CLOUDFLARE_API_TOKEN": "",
    "CLOUDFLARE_TIMEOUT": 60,
    "CLOUDFLARE_CACHE_TTL": 0,
    "CLOUDFLARE_BLACKLIST": [],
    "CLOUDFLARE_VIEWPORT_WIDTH": 1280,
    "CLOUDFLARE_VIEWPORT_HEIGHT": 720,
    "CLOUDFLARE_WAIT_UNTIL": "networkidle0",
    "CLOUDFLARE_GOTO_TIMEOUT": 45000,
    "CLOUDFLARE_FULL_PAGE": False,
    "CLOUDFLARE_DEVICE_SCALE_FACTOR": 1,
    "CLOUDFLARE_SCREENSHOT_TYPE": "png",
    "CLOUDFLARE_SCREENSHOT_QUALITY": 0,
    "CLOUDFLARE_OMIT_BACKGROUND": False,
    "CLOUDFLARE_SELECTOR": "",
    "CLOUDFLARE_WAIT_FOR_SELECTOR": "",
    "CLOUDFLARE_WAIT_FOR_TIMEOUT": 0,
    "CLOUDFLARE_USER_AGENT": "",
    "CLOUDFLARE_EXTRA_HEADERS": "",
    "CLOUDFLARE_COOKIES": "",
}

# Cloudflare API 的 key 映射（snake_case → camelCase）
# 参考 astrbot_plugin_cloudflare_browser_run 的 CF_KEY_MAP
CF_KEY_MAP: dict[str, str] = {
    "action_timeout": "actionTimeout",
    "add_script_tag": "addScriptTag",
    "add_style_tag": "addStyleTag",
    "allow_request_pattern": "allowRequestPattern",
    "allow_resource_types": "allowResourceTypes",
    "best_attempt": "bestAttempt",
    "capture_beyond_viewport": "captureBeyondViewport",
    "device_scale_factor": "deviceScaleFactor",
    "emulate_media_type": "emulateMediaType",
    "full_page": "fullPage",
    "goto_options": "gotoOptions",
    "has_touch": "hasTouch",
    "http_only": "httpOnly",
    "is_landscape": "isLandscape",
    "is_mobile": "isMobile",
    "omit_background": "omitBackground",
    "partition_key": "partitionKey",
    "reject_request_pattern": "rejectRequestPattern",
    "reject_resource_types": "rejectResourceTypes",
    "same_party": "sameParty",
    "same_site": "sameSite",
    "screenshot_options": "screenshotOptions",
    "set_extra_http_headers": "setExtraHTTPHeaders",
    "set_javascript_enabled": "setJavaScriptEnabled",
    "source_port": "sourcePort",
    "source_scheme": "sourceScheme",
    "user_agent": "userAgent",
    "wait_for_selector": "waitForSelector",
    "wait_for_timeout": "waitForTimeout",
    "wait_until": "waitUntil",
}

# 保持蛇形命名、不做转换的 key
KEEP_SNAKE_KEYS: set[str] = set()

# PNG / JPEG 文件头（用于校验返回内容确实是图片）
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"

# 提取 <title> 的正则
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


class CloudflareScreenshotError(Exception):
    """Cloudflare 截图 API 错误"""
    pass


def _is_present(value: Any) -> bool:
    """检查值是否有效（非 None、非空字符串、非空列表、非空字典）"""
    return value is not None and value != "" and value != [] and value != {}


def _cf_key(key: str) -> str:
    """将 snake_case key 转换为 Cloudflare API 可接受的 camelCase"""
    if key in KEEP_SNAKE_KEYS:
        return key
    return CF_KEY_MAP.get(key, key)


def _to_cf_keys(value: Any) -> Any:
    """递归地将 dict 的所有 key 转换为 camelCase，并过滤空值"""
    if isinstance(value, list):
        return [_to_cf_keys(item) for item in value]
    if not isinstance(value, dict):
        return value
    converted: dict[str, Any] = {}
    for key, item in value.items():
        if not _is_present(item) and item is not False and item != 0:
            continue
        converted[_cf_key(str(key))] = _to_cf_keys(item)
    return converted


def _cfg(config: dict, key: str, default=None):
    """从配置字典中按 key 取值（支持点号嵌套）"""
    keys = key.split(".")
    val = config
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k)
        else:
            return default
    if val is None:
        return default
    return val


def _cfg_any(config: dict, key: str, default=None):
    """优先读取分组配置，其次回退扁平旧配置（兼容旧版本保存的设置）"""
    group = _CF_KEY_GROUPS.get(key)
    if group:
        group_cfg = config.get(group)
        if isinstance(group_cfg, dict) and key in group_cfg:
            default_val = _CF_KEY_DEFAULTS.get(key, default)
            flat_val = config.get(key, default_val)
            nested_val = group_cfg[key]
            # 分组仍是默认值而扁平旧值被改过时，优先旧值（兼容迁移前的状态）
            if nested_val == default_val and flat_val != default_val:
                return flat_val
            return nested_val
    return _cfg(config, key, default)


def _to_int(value: Any, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    """安全转 int，并做范围限制"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def _to_float(value: Any, default: float) -> float:
    """安全转 float"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number <= 0:
        number = default
    return number


def _parse_json_value(raw: Any, default: Any) -> Any:
    """解析配置中的 JSON 字符串（字典/列表），失败时返回默认值"""
    if raw is None or raw == "":
        return default
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"Cloudflare 配置 JSON 解析失败，已忽略: {raw[:80]}")
            return default
    return default


def normalize_blacklist(raw: Any) -> list[str]:
    """规范化黑名单配置：支持 list 或逗号/换行分隔的字符串，统一转小写"""
    if raw is None:
        return []
    if isinstance(raw, str):
        items = re.split(r"[,;\n]+", raw)
    elif isinstance(raw, (list, tuple, set)):
        items = raw
    else:
        return []
    entries: list[str] = []
    for item in items:
        text = str(item).strip().lower()
        if text:
            entries.append(text)
    return entries


def is_url_blacklisted(url: str, raw_blacklist: Any) -> bool:
    """判断 URL 是否命中截图黑名单

    支持三种写法（条目间用逗号或换行分隔）：
    - 域名：`example.com` 匹配该域名及其所有子域名
    - 通配符：`*.example.com`、`https://example.com/*`（支持 * 和 ?）
    - 完整 URL/路径前缀：`https://example.com/login` 匹配该前缀开头的地址
    - 不含点的关键词：如 `porn`，URL 中任意位置包含即命中
    """
    entries = normalize_blacklist(raw_blacklist)
    if not entries or not url:
        return False

    url_lower = url.strip().lower()
    try:
        host = (urlparse(url_lower).hostname or "").lower()
    except Exception:
        host = ""

    for entry in entries:
        if "*" in entry or "?" in entry:
            # 通配符：优先匹配完整 URL，其次匹配域名
            if fnmatch.fnmatch(url_lower, entry):
                return True
            if host and fnmatch.fnmatch(host, entry):
                return True
            # *.example.com 同时覆盖 example.com 本身及其子域名
            if host and entry.startswith("*."):
                bare = entry[2:]
                if host == bare or host.endswith("." + bare):
                    return True
            continue
        if entry.startswith(("http://", "https://")) or "/" in entry:
            # 完整 URL / 路径前缀
            if url_lower.startswith(entry):
                return True
            continue
        if host == entry or (host and host.endswith("." + entry)):
            # 精确域名或其子域名
            return True
        if "." not in entry and entry in url_lower:
            # 不含点的条目按关键词匹配
            return True
    return False


async def fetch_page_title(url: str, timeout: int = 10) -> Optional[str]:
    """通过简单的 HTTP GET 请求获取网页 <title>（只下载前 20KB）

    Args:
        url: 目标网页 URL
        timeout: 超时秒数

    Returns:
        页面标题，失败返回 None
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    try:
        timeout_obj = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=timeout_obj) as session:
            async with session.get(url, headers=headers, ssl=False) as resp:
                if resp.status >= 400:
                    return None
                html = await resp.text()
                m = _TITLE_RE.search(html)
                if m:
                    title = m.group(1).strip()
                    # 清理多余空白
                    title = re.sub(r"\s+", " ", title)
                    return title[:200] if title else None
    except Exception:
        logger.debug(f"获取网页标题失败: {url}", exc_info=True)
    return None


class CloudflareScreenshotClient:
    """Cloudflare Browser Rendering 截图客户端

    支持官方 /screenshot 文档中的常用参数：
    - viewport + deviceScaleFactor（提升大视窗截图清晰度）
    - gotoOptions.waitUntil / timeout（JS 重页面等待渲染完成）
    - screenshotOptions（fullPage / omitBackground / type / quality）
    - selector（指定元素截图）、waitForSelector（等待元素出现）
    - userAgent、setExtraHTTPHeaders、cookies（登录/鉴权页面）
    - cacheTTL 查询参数（可复用 Cloudflare 缓存节省额度）
    """

    def __init__(self, config: dict):
        self.account_id = _cfg_any(config, "CLOUDFLARE_ACCOUNT_ID", "") or \
                          _cfg_any(config, "CLOUDFLARE.ACCOUNT_ID", "")
        self.api_token = _cfg_any(config, "CLOUDFLARE_API_TOKEN", "") or \
                         _cfg_any(config, "CLOUDFLARE.API_TOKEN", "")
        self.timeout = _to_int(_cfg_any(config, "CLOUDFLARE_TIMEOUT", 60), 60, 1)
        self.viewport_width = _to_int(
            _cfg_any(config, "CLOUDFLARE_VIEWPORT_WIDTH", 1280), 1280, 1
        )
        self.viewport_height = _to_int(
            _cfg_any(config, "CLOUDFLARE_VIEWPORT_HEIGHT", 720), 720, 1
        )

        # ---- 新增：页面加载与截图选项 ----
        self.wait_until = str(
            _cfg_any(config, "CLOUDFLARE_WAIT_UNTIL", "networkidle0")
        ).strip().lower()
        if self.wait_until not in WAIT_UNTIL_VALUES:
            self.wait_until = "networkidle0"
        self.goto_timeout_ms = _to_int(
            _cfg_any(config, "CLOUDFLARE_GOTO_TIMEOUT", 45000), 45000, 0
        )
        self.full_page = bool(_cfg_any(config, "CLOUDFLARE_FULL_PAGE", False))
        self.device_scale_factor = _to_float(
            _cfg_any(config, "CLOUDFLARE_DEVICE_SCALE_FACTOR", 1), 1.0
        )
        self.omit_background = bool(
            _cfg_any(config, "CLOUDFLARE_OMIT_BACKGROUND", False)
        )

        self.screenshot_type = str(
            _cfg_any(config, "CLOUDFLARE_SCREENSHOT_TYPE", "png")
        ).strip().lower().lstrip(".")
        if self.screenshot_type == "jpg":
            self.screenshot_type = "jpeg"
        if self.screenshot_type not in SCREENSHOT_TYPES:
            self.screenshot_type = "png"
        # quality 仅对 jpeg 有效；0 表示不指定
        self.quality = _to_int(
            _cfg_any(config, "CLOUDFLARE_SCREENSHOT_QUALITY", 0), 0, 0, 100
        )

        self.selector = str(
            _cfg_any(config, "CLOUDFLARE_SELECTOR", "") or ""
        ).strip()
        self.wait_for_selector = str(
            _cfg_any(config, "CLOUDFLARE_WAIT_FOR_SELECTOR", "") or ""
        ).strip()
        self.wait_for_timeout_ms = _to_int(
            _cfg_any(config, "CLOUDFLARE_WAIT_FOR_TIMEOUT", 0), 0, 0
        )

        self.user_agent = str(
            _cfg_any(config, "CLOUDFLARE_USER_AGENT", "") or ""
        ).strip()
        extra_headers = _parse_json_value(
            _cfg_any(config, "CLOUDFLARE_EXTRA_HEADERS", ""), {}
        )
        self.extra_headers = extra_headers if isinstance(extra_headers, dict) else {}
        cookies = _parse_json_value(_cfg_any(config, "CLOUDFLARE_COOKIES", ""), [])
        self.cookies = cookies if isinstance(cookies, list) else []
        self.cache_ttl = _to_int(
            _cfg_any(config, "CLOUDFLARE_CACHE_TTL", 0), 0, 0, 86400
        )

        # 最近一次错误信息，供调用方展示
        self.last_error: Optional[str] = None

    @property
    def is_configured(self) -> bool:
        """检查 API 凭据是否已配置"""
        return bool(self.account_id) and bool(self.api_token)

    def _redact(self, text: str) -> str:
        """对错误信息中的 API Token 等敏感内容做脱敏"""
        if self.api_token and self.api_token in text:
            text = text.replace(self.api_token, "***REDACTED***")
        text = re.sub(
            r"Bearer\s+[A-Za-z0-9._~+/=-]+",
            "Bearer ***REDACTED***",
            text,
            flags=re.IGNORECASE,
        )
        return text

    def _format_error(self, status: int, raw_text: str) -> str:
        """格式化 Cloudflare API 错误响应"""
        raw_text = raw_text[:500]
        try:
            data = json.loads(raw_text) if raw_text else {}
        except json.JSONDecodeError:
            data = {}
        if isinstance(data, dict):
            errors = data.get("errors")
            if errors:
                message = json.dumps(errors, ensure_ascii=False)
            else:
                message = raw_text or str(data)[:300]
        else:
            message = raw_text
        return f"Cloudflare API 错误 (HTTP {status}): {message}"

    def _build_body(
        self,
        url: str = "",
        html: str = "",
        overrides: Optional[dict] = None,
    ) -> dict[str, Any]:
        """按配置构建请求体（snake_case，随后由 _to_cf_keys 转换）"""
        body: dict[str, Any] = {}
        if url:
            body["url"] = url
        if html:
            body["html"] = html

        viewport: dict[str, Any] = {
            "width": self.viewport_width,
            "height": self.viewport_height,
        }
        if self.device_scale_factor != 1.0:
            viewport["device_scale_factor"] = self.device_scale_factor
        body["viewport"] = viewport

        goto_options: dict[str, Any] = {"wait_until": self.wait_until}
        if self.goto_timeout_ms > 0:
            goto_options["timeout"] = self.goto_timeout_ms
        body["goto_options"] = goto_options

        screenshot_options: dict[str, Any] = {"type": self.screenshot_type}
        if self.full_page:
            screenshot_options["full_page"] = True
        if self.omit_background:
            screenshot_options["omit_background"] = True
        # 官方文档：quality 与 png 不兼容，仅 jpeg 时携带
        if self.screenshot_type == "jpeg" and self.quality > 0:
            screenshot_options["quality"] = self.quality
        body["screenshot_options"] = screenshot_options

        if self.selector:
            body["selector"] = self.selector
        if self.user_agent:
            body["user_agent"] = self.user_agent
        if self.extra_headers:
            body["set_extra_http_headers"] = self.extra_headers
        if self.cookies:
            body["cookies"] = self.cookies
        if self.wait_for_selector:
            wait_options: dict[str, Any] = {"selector": self.wait_for_selector}
            if self.wait_for_timeout_ms > 0:
                wait_options["timeout"] = self.wait_for_timeout_ms
            body["wait_for_selector"] = wait_options

        # 单次调用覆盖：嵌套 dict 浅合并，其余直接覆盖
        for key, value in (overrides or {}).items():
            if isinstance(value, dict) and isinstance(body.get(key), dict):
                body[key] = {**body[key], **value}
            else:
                body[key] = value
        return body

    def _is_image_data(self, data: bytes) -> bool:
        """校验返回字节流是否为请求格式的图片（PNG/JPEG 文件头）"""
        if self.screenshot_type == "jpeg":
            return data.startswith(_JPEG_MAGIC)
        return data.startswith(_PNG_MAGIC)

    async def screenshot(
        self,
        url: str,
        save_dir: Path,
        *,
        html: str = "",
        **overrides,
    ) -> Optional[Path]:
        """对指定 URL（或 HTML）截图并保存到本地

        Args:
            url: 目标网页 URL（与 html 二选一）
            save_dir: 截图文件保存目录
            html: 原始 HTML 内容（提供时优先于 url）
            **overrides: 单次调用参数覆盖（如 full_page=True、selector="#main"）

        Returns:
            截图文件的 Path；失败返回 None，可通过 self.last_error 获取原因
        """
        self.last_error = None
        if not self.is_configured:
            self.last_error = "未配置 Cloudflare Account ID / API Token"
            logger.warning("Cloudflare 截图未配置，跳过")
            return None

        body_raw = self._build_body(url, html, overrides)
        if "url" not in body_raw and "html" not in body_raw:
            self.last_error = "必须提供 url 或 html"
            logger.warning("Cloudflare 截图：必须提供 url 或 html")
            return None

        body = _to_cf_keys(body_raw)
        logger.debug(f"Cloudflare 截图请求 body: {body}")

        endpoint = SCREENSHOT_ENDPOINT.format(account_id=self.account_id)
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }
        params = {"cacheTTL": str(self.cache_ttl)} if self.cache_ttl > 0 else None
        extension = ".jpg" if self.screenshot_type == "jpeg" else ".png"
        save_path: Optional[Path] = None

        try:
            save_dir.mkdir(parents=True, exist_ok=True)
            filename = f"cf_screenshot_{uuid.uuid4().hex[:12]}{extension}"
            save_path = save_dir / filename
            timeout_obj = aiohttp.ClientTimeout(total=self.timeout)

            async with aiohttp.ClientSession(timeout=timeout_obj) as session:
                async with session.post(
                    endpoint, headers=headers, params=params, json=body
                ) as resp:
                    content_type = resp.headers.get("Content-Type", "")
                    if resp.status >= 400:
                        text = await resp.text()
                        raise CloudflareScreenshotError(
                            self._format_error(resp.status, text)
                        )
                    # 200 但返回 JSON/文本说明是错误响应而非图片
                    if "application/json" in content_type or "text/" in content_type:
                        text = await resp.text()
                        raise CloudflareScreenshotError(
                            self._format_error(resp.status, text)
                        )
                    data = await resp.read()

            if not data:
                raise CloudflareScreenshotError("Cloudflare API 返回了空内容")
            if not self._is_image_data(data):
                raise CloudflareScreenshotError(
                    "Cloudflare API 返回的内容不是有效的图片数据"
                )

            save_path.write_bytes(data)
            logger.info(f"Cloudflare 网页截图已保存: {save_path}")
            return save_path

        except asyncio.TimeoutError:
            self.last_error = f"请求超时（{self.timeout}s）"
            logger.error(f"Cloudflare 截图超时 ({self.timeout}s): {url}")
            return None
        except aiohttp.ClientError as e:
            self.last_error = f"网络错误: {e}"
            logger.error(f"Cloudflare 截图网络错误: {e}")
            return None
        except CloudflareScreenshotError as e:
            self.last_error = self._redact(str(e))
            logger.error(f"Cloudflare 截图失败: {self.last_error}")
            return None
        except Exception as e:
            self.last_error = f"未知错误: {e}"
            logger.exception(f"Cloudflare 截图未知错误: {e}")
            return None
