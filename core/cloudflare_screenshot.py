"""Cloudflare Browser Rendering 截图模块

使用 Cloudflare Browser Rendering API 的 screenshot 端点，
将网页渲染为图片并保存到本地。
参考 astrbot_plugin_cloudflare_browser_run 的 API 调用模式。
"""

import asyncio
import re
import uuid
from pathlib import Path
from typing import Any, Optional

import aiohttp
from astrbot.api import logger

API_BASE = "https://api.cloudflare.com/client/v4"

# Cloudflare API 的 key 映射（snake_case → camelCase）
# 参考 astrbot_plugin_cloudflare_browser_run 的 CF_KEY_MAP
CF_KEY_MAP: dict[str, str] = {
    "goto_options": "gotoOptions",
    "wait_until": "waitUntil",
    "action_timeout": "actionTimeout",
}

# 保留蛇形命名，不转换的 key
KEEP_SNAKE_KEYS: set[str] = set()

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
    """从配置字典中按 key 取值"""
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
    """Cloudflare Browser Rendering 截图客户端"""

    def __init__(self, config: dict):
        self.account_id = _cfg(config, "CLOUDFLARE_ACCOUNT_ID", "") or \
                          _cfg(config, "CLOUDFLARE.ACCOUNT_ID", "")
        self.api_token = _cfg(config, "CLOUDFLARE_API_TOKEN", "") or \
                         _cfg(config, "CLOUDFLARE.API_TOKEN", "")
        self.timeout = int(_cfg(config, "CLOUDFLARE_TIMEOUT", 60))
        self.viewport_width = int(_cfg(config, "CLOUDFLARE_VIEWPORT_WIDTH", 1280))
        self.viewport_height = int(_cfg(config, "CLOUDFLARE_VIEWPORT_HEIGHT", 720))

    @property
    def is_configured(self) -> bool:
        """检查 API 凭据是否已配置"""
        return bool(self.account_id) and bool(self.api_token)

    async def screenshot(self, url: str, save_dir: Path) -> Optional[Path]:
        """对指定 URL 截图并保存到本地

        添加 gotoOptions.waitUntil = "networkidle0" 确保页面加载完再截图。

        Args:
            url: 目标网页 URL
            save_dir: 截图文件保存目录

        Returns:
            截图文件的 Path，失败返回 None
        """
        if not self.is_configured:
            logger.warning("Cloudflare 截图未配置，跳过")
            return None

        endpoint = f"{API_BASE}/accounts/{self.account_id}/browser-rendering/screenshot"

        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

        # 参考原插件 _page_body：goto_options + wait_until 是浏览器级参数，
        # 所有 browser-rendering 端点都应支持
        body_raw: dict[str, Any] = {
            "url": url,
            "viewport": {
                "width": self.viewport_width,
                "height": self.viewport_height,
            },
            "goto_options": {
                "wait_until": "load",
            },
        }

        body = _to_cf_keys(body_raw)
        logger.debug(f"Cloudflare 截图请求 body: {body}")

        timeout_obj = aiohttp.ClientTimeout(total=self.timeout)

        try:
            save_dir.mkdir(parents=True, exist_ok=True)
            filename = f"cf_screenshot_{uuid.uuid4().hex[:12]}.png"
            save_path = save_dir / filename

            async with aiohttp.ClientSession(timeout=timeout_obj) as session:
                async with session.post(endpoint, headers=headers, json=body) as resp:
                    if resp.status >= 400:
                        text = (await resp.text())[:500]
                        raise CloudflareScreenshotError(
                            f"Cloudflare API 错误 ({resp.status}): {text}"
                        )

                    # 检查是否返回了 JSON 错误（非二进制图片）
                    content_type = resp.headers.get("Content-Type", "")
                    if "application/json" in content_type or "text/" in content_type:
                        resp_text = await resp.text()
                        try:
                            data = __import__("json").loads(resp_text)
                        except Exception:
                            raise CloudflareScreenshotError(
                                f"Cloudflare API 返回非图片数据: {resp_text[:300]}"
                            )
                        if isinstance(data, dict) and data.get("success") is False:
                            raise CloudflareScreenshotError(
                                f"Cloudflare API 返回错误: {data.get('errors', data)}"
                            )
                        raise CloudflareScreenshotError(
                            f"Cloudflare API 返回非图片内容: {resp_text[:200]}"
                        )

                    with open(save_path, "wb") as f:
                        f.write(await resp.read())

            if save_path.stat().st_size == 0:
                save_path.unlink(missing_ok=True)
                raise CloudflareScreenshotError("截图文件为空")

            logger.info(f"Cloudflare 网页截图已保存: {save_path}")
            return save_path

        except asyncio.TimeoutError:
            logger.error(f"Cloudflare 截图超时 ({self.timeout}s): {url}")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"Cloudflare 截图网络错误: {e}")
            return None
        except CloudflareScreenshotError as e:
            logger.error(str(e))
            return None
        except Exception as e:
            logger.exception(f"Cloudflare 截图未知错误: {e}")
            return None
