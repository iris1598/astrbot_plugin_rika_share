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
    def PROXY(self) -> str | None:
        return self._cfg.get("PROXY", None)

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
        return int(self._cfg.get("CLOUDFLARE_TIMEOUT", 30))

    @property
    def CLOUDFLARE_VIEWPORT_WIDTH(self) -> int:
        """截图视窗宽度"""
        return int(self._cfg.get("CLOUDFLARE_VIEWPORT_WIDTH", 1280))

    @property
    def CLOUDFLARE_VIEWPORT_HEIGHT(self) -> int:
        """截图视窗高度"""
        return int(self._cfg.get("CLOUDFLARE_VIEWPORT_HEIGHT", 720))


def init_config(astrbot_config: Any, cache_dir: Path, config_dir: Path) -> ParserConfig:
    global _config
    _config = ParserConfig(astrbot_config, cache_dir, config_dir)
    return _config


def get_config() -> ParserConfig:
    global _config
    if _config is None:
        raise RuntimeError("ParserConfig not initialized yet")
    return _config
