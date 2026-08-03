"""配置管理模块"""

from pathlib import Path
from typing import Any

_config = None


class ParserConfig:
    """解析器配置 - 由 main.py 初始化"""
    def __init__(self, astrbot_config: Any, cache_dir: Path, config_dir: Path):
        self._cfg = astrbot_config
        self.cache_dir = cache_dir
        self.config_dir = config_dir

    @property
    def BILI_CK(self) -> str | None:
        return self._cfg.get("BILI_CK", None)

    @property
    def YTB_CK(self) -> str | None:
        return self._cfg.get("YTB_CK", None)

    @property
    def XHS_CK(self) -> str | None:
        return self._cfg.get("XHS_CK", None)

    @property
    def VIDEO_DURATION_MAXIMUM(self) -> int:
        return int(self._cfg.get("VIDEO_DURATION_MAXIMUM", 480))

    @property
    def APPEND_URL(self) -> bool:
        return bool(self._cfg.get("APPEND_URL", False))

    @property
    def RENDER_TYPE(self) -> str:
        return self._cfg.get("RENDER_TYPE", "common")

    @property
    def DISABLED_PLATFORMS(self) -> list[str]:
        raw = self._cfg.get("DISABLED_PLATFORMS", "")
        if not raw:
            return []
        return [p.strip().lower() for p in raw.split(",") if p.strip()]

    @property
    def NEED_FORWARD_CONTENTS(self) -> bool:
        return bool(self._cfg.get("NEED_FORWARD_CONTENTS", True))

    @property
    def CACHE_TTL_HOURS(self) -> int:
        return int(self._cfg.get("CACHE_TTL_HOURS", 24))

    @property
    def CACHE_CLEANUP_INTERVAL_MINUTES(self) -> int:
        return int(self._cfg.get("CACHE_CLEANUP_INTERVAL_MINUTES", 60))

    @property
    def BILI_QUALITY(self) -> str:
        return str(self._cfg.get("BILI_QUALITY", "1080P"))

    @property
    def BILI_COOKIE_MONITOR_ENABLED(self) -> bool:
        return bool(self._cfg.get("BILI_COOKIE_MONITOR_ENABLED", True))

    @property
    def BILI_COOKIE_CHECK_INTERVAL(self) -> int:
        val = int(self._cfg.get("BILI_COOKIE_CHECK_INTERVAL", 3600))
        return max(60, val)

    @property
    def BILI_NOTIFY_USER_ID(self) -> str:
        return str(self._cfg.get("BILI_NOTIFY_USER_ID", ""))

    # ==================== Cloudflare 截图 Fallback ====================

    @property
    def CLOUDFLARE_FALLBACK_ENABLED(self) -> bool:
        """是否启用 Cloudflare 截图 fallback"""
        return bool(self._cfg.get("CLOUDFLARE_FALLBACK_ENABLED", False))

    @property
    def CLOUDFLARE_ACCOUNT_ID(self) -> str:
        """Cloudflare 账号 ID"""
        return str(self._cfg.get("CLOUDFLARE_ACCOUNT_ID", ""))

    @property
    def CLOUDFLARE_API_TOKEN(self) -> str:
        """Cloudflare API Token（需要 Browser Rendering - Edit 权限）"""
        return str(self._cfg.get("CLOUDFLARE_API_TOKEN", ""))

    @property
    def CLOUDFLARE_TIMEOUT(self) -> int:
        """截图 API 超时时间（秒）"""
        return int(self._cfg.get("CLOUDFLARE_TIMEOUT", 60))

    @property
    def CLOUDFLARE_VIEWPORT_WIDTH(self) -> int:
        """截图视窗宽度"""
        return int(self._cfg.get("CLOUDFLARE_VIEWPORT_WIDTH", 1280))

    @property
    def CLOUDFLARE_VIEWPORT_HEIGHT(self) -> int:
        """截图视窗高度"""
        return int(self._cfg.get("CLOUDFLARE_VIEWPORT_HEIGHT", 720))

    @property
    def CLOUDFLARE_WAIT_UNTIL(self) -> str:
        """页面加载等待策略"""
        val = str(self._cfg.get("CLOUDFLARE_WAIT_UNTIL", "networkidle0")).strip().lower()
        if val not in {"load", "domcontentloaded", "networkidle0", "networkidle2"}:
            return "networkidle0"
        return val

    @property
    def CLOUDFLARE_GOTO_TIMEOUT(self) -> int:
        """页面加载超时（毫秒）"""
        return max(0, int(self._cfg.get("CLOUDFLARE_GOTO_TIMEOUT", 45000)))

    @property
    def CLOUDFLARE_FULL_PAGE(self) -> bool:
        """是否整页截图"""
        return bool(self._cfg.get("CLOUDFLARE_FULL_PAGE", False))

    @property
    def CLOUDFLARE_DEVICE_SCALE_FACTOR(self) -> float:
        """截图清晰度（deviceScaleFactor）"""
        try:
            val = float(self._cfg.get("CLOUDFLARE_DEVICE_SCALE_FACTOR", 1))
        except (TypeError, ValueError):
            val = 1.0
        return val if val > 0 else 1.0

    @property
    def CLOUDFLARE_OMIT_BACKGROUND(self) -> bool:
        """是否隐藏默认白色背景（仅 png 有效）"""
        return bool(self._cfg.get("CLOUDFLARE_OMIT_BACKGROUND", False))

    @property
    def CLOUDFLARE_SCREENSHOT_TYPE(self) -> str:
        """截图格式（png/jpeg）"""
        val = str(self._cfg.get("CLOUDFLARE_SCREENSHOT_TYPE", "png")).strip().lower().lstrip(".")
        if val == "jpg":
            val = "jpeg"
        return val if val in {"png", "jpeg"} else "png"

    @property
    def CLOUDFLARE_SCREENSHOT_QUALITY(self) -> int:
        """截图质量（仅 jpeg 有效，0 表示不指定）"""
        return max(0, min(100, int(self._cfg.get("CLOUDFLARE_SCREENSHOT_QUALITY", 0))))

    @property
    def CLOUDFLARE_SELECTOR(self) -> str:
        """指定元素截图 CSS 选择器"""
        return str(self._cfg.get("CLOUDFLARE_SELECTOR", "") or "").strip()

    @property
    def CLOUDFLARE_WAIT_FOR_SELECTOR(self) -> str:
        """等待元素出现的 CSS 选择器"""
        return str(self._cfg.get("CLOUDFLARE_WAIT_FOR_SELECTOR", "") or "").strip()

    @property
    def CLOUDFLARE_WAIT_FOR_TIMEOUT(self) -> int:
        """等待元素超时（毫秒），0 表示不指定"""
        return max(0, int(self._cfg.get("CLOUDFLARE_WAIT_FOR_TIMEOUT", 0)))

    @property
    def CLOUDFLARE_USER_AGENT(self) -> str:
        """自定义 User-Agent"""
        return str(self._cfg.get("CLOUDFLARE_USER_AGENT", "") or "").strip()

    @property
    def CLOUDFLARE_EXTRA_HEADERS(self) -> str:
        """附加请求头（JSON 字符串）"""
        return str(self._cfg.get("CLOUDFLARE_EXTRA_HEADERS", "") or "")

    @property
    def CLOUDFLARE_COOKIES(self) -> str:
        """附加 Cookie（JSON 字符串）"""
        return str(self._cfg.get("CLOUDFLARE_COOKIES", "") or "")

    @property
    def CLOUDFLARE_CACHE_TTL(self) -> int:
        """截图缓存时间（秒），0 表示不缓存"""
        return max(0, min(86400, int(self._cfg.get("CLOUDFLARE_CACHE_TTL", 0))))

    @property
    def CLOUDFLARE_BLACKLIST(self) -> list[str]:
        """Cloudflare 截图黑名单（域名/通配符/关键词，逗号或换行分隔）"""
        from .cloudflare_screenshot import normalize_blacklist

        return normalize_blacklist(self._cfg.get("CLOUDFLARE_BLACKLIST", []))

    @property
    def DEBUG_LOG_ENABLED(self) -> bool:
        """是否启用详细错误日志"""
        return bool(self._cfg.get("DEBUG_LOG_ENABLED", True))


def init_config(astrbot_config: Any, cache_dir: Path, config_dir: Path) -> ParserConfig:
    global _config
    _config = ParserConfig(astrbot_config, cache_dir, config_dir)
    return _config


def get_config() -> ParserConfig:
    global _config
    if _config is None:
        raise RuntimeError("ParserConfig not initialized yet")
    return _config
