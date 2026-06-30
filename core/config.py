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


def init_config(astrbot_config: Any, cache_dir: Path, config_dir: Path) -> ParserConfig:
    global _config
    _config = ParserConfig(astrbot_config, cache_dir, config_dir)
    return _config


def get_config() -> ParserConfig:
    global _config
    if _config is None:
        raise RuntimeError("ParserConfig not initialized yet")
    return _config
