"""配置管理模块

设置页在 WebUI 中按分组展示（平台 / B站 / 缓存 / Cloudflare / 调试）。
为保证旧版本已保存的扁平配置不丢失，读取时优先使用分组值，
分组值为默认值时回退到扁平旧值；插件启动时会将旧值迁移到分组中。
"""

from pathlib import Path
from typing import Any

_config = None

# 分组名 -> 组内配置项
CONFIG_GROUP_KEYS: dict[str, tuple[str, ...]] = {
    "平台设置": (
        "DISABLED_PLATFORMS",
        "VIDEO_DURATION_MAXIMUM",
        "YTB_CK",
        "XHS_CK",
    ),
    "B站设置": (
        "BILI_CK",
        "BILI_QUALITY",
        "BILI_COOKIE_MONITOR_ENABLED",
        "BILI_COOKIE_CHECK_INTERVAL",
        "BILI_NOTIFY_USER_ID",
    ),
    "缓存设置": (
        "CACHE_TTL_HOURS",
        "CACHE_CLEANUP_INTERVAL_MINUTES",
    ),
    "Cloudflare 基础设置": (
        "CLOUDFLARE_FALLBACK_ENABLED",
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_TIMEOUT",
        "CLOUDFLARE_CACHE_TTL",
        "CLOUDFLARE_BLACKLIST",
    ),
    "Cloudflare 截图设置": (
        "CLOUDFLARE_VIEWPORT_WIDTH",
        "CLOUDFLARE_VIEWPORT_HEIGHT",
        "CLOUDFLARE_WAIT_UNTIL",
        "CLOUDFLARE_GOTO_TIMEOUT",
        "CLOUDFLARE_FULL_PAGE",
        "CLOUDFLARE_DEVICE_SCALE_FACTOR",
        "CLOUDFLARE_SCREENSHOT_TYPE",
        "CLOUDFLARE_SCREENSHOT_QUALITY",
        "CLOUDFLARE_OMIT_BACKGROUND",
        "CLOUDFLARE_SELECTOR",
        "CLOUDFLARE_WAIT_FOR_SELECTOR",
        "CLOUDFLARE_WAIT_FOR_TIMEOUT",
        "CLOUDFLARE_USER_AGENT",
        "CLOUDFLARE_EXTRA_HEADERS",
        "CLOUDFLARE_COOKIES",
    ),
    "调试设置": ("DEBUG_LOG_ENABLED",),
}

_KEY_GROUP_MAP: dict[str, str] = {
    key: group for group, keys in CONFIG_GROUP_KEYS.items() for key in keys
}

# 各配置项的默认值（与 _conf_schema.json 保持一致），用于旧配置迁移判断
_LEGACY_DEFAULTS: dict[str, Any] = {
    "DISABLED_PLATFORMS": "",
    "VIDEO_DURATION_MAXIMUM": 480,
    "YTB_CK": "",
    "XHS_CK": "",
    "BILI_CK": "",
    "BILI_QUALITY": "1080P",
    "BILI_COOKIE_MONITOR_ENABLED": True,
    "BILI_COOKIE_CHECK_INTERVAL": 3600,
    "BILI_NOTIFY_USER_ID": "",
    "CACHE_TTL_HOURS": 24,
    "CACHE_CLEANUP_INTERVAL_MINUTES": 60,
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
    "DEBUG_LOG_ENABLED": True,
}


def migrate_grouped_config(config: Any) -> bool:
    """将旧版扁平配置迁移到分组配置，返回是否发生变更

    仅当分组值仍为默认值、而扁平旧值被用户改过时才迁移，
    因此重复调用是幂等的。
    """
    changed = False
    for group, keys in CONFIG_GROUP_KEYS.items():
        group_cfg = config.get(group)
        if not isinstance(group_cfg, dict):
            group_cfg = {}
            config[group] = group_cfg
        for key in keys:
            default = _LEGACY_DEFAULTS.get(key)
            flat_val = config.get(key, default)
            nested_val = group_cfg.get(key, default)
            if nested_val == default and flat_val != default:
                group_cfg[key] = flat_val
                config[key] = default
                changed = True
    return changed


class ParserConfig:
    """解析器配置 - 由 main.py 初始化"""

    def __init__(self, astrbot_config: Any, cache_dir: Path, config_dir: Path):
        self._cfg = astrbot_config
        self.cache_dir = cache_dir
        self.config_dir = config_dir

    def _cfg_get(self, key: str, default: Any = None) -> Any:
        """优先读取分组配置，其次回退到扁平旧配置"""
        group = _KEY_GROUP_MAP.get(key)
        if group is not None:
            group_cfg = self._cfg.get(group)
            if isinstance(group_cfg, dict) and key in group_cfg:
                default_val = _LEGACY_DEFAULTS.get(key, default)
                flat_val = self._cfg.get(key, default_val)
                nested_val = group_cfg[key]
                # 分组仍是默认值而扁平旧值被改过时，优先旧值（兼容迁移前的状态）
                if nested_val == default_val and flat_val != default_val:
                    return flat_val
                return nested_val
        return self._cfg.get(key, default)

    @property
    def BILI_CK(self) -> str | None:
        return self._cfg_get("BILI_CK", None)

    @property
    def YTB_CK(self) -> str | None:
        return self._cfg_get("YTB_CK", None)

    @property
    def XHS_CK(self) -> str | None:
        return self._cfg_get("XHS_CK", None)

    @property
    def VIDEO_DURATION_MAXIMUM(self) -> int:
        return int(self._cfg_get("VIDEO_DURATION_MAXIMUM", 480))

    @property
    def APPEND_URL(self) -> bool:
        return bool(self._cfg_get("APPEND_URL", False))

    @property
    def RENDER_TYPE(self) -> str:
        return self._cfg_get("RENDER_TYPE", "common")

    @property
    def DISABLED_PLATFORMS(self) -> list[str]:
        raw = self._cfg_get("DISABLED_PLATFORMS", "")
        if not raw:
            return []
        return [p.strip().lower() for p in raw.split(",") if p.strip()]

    @property
    def NEED_FORWARD_CONTENTS(self) -> bool:
        return bool(self._cfg_get("NEED_FORWARD_CONTENTS", True))

    @property
    def CACHE_TTL_HOURS(self) -> int:
        return int(self._cfg_get("CACHE_TTL_HOURS", 24))

    @property
    def CACHE_CLEANUP_INTERVAL_MINUTES(self) -> int:
        return int(self._cfg_get("CACHE_CLEANUP_INTERVAL_MINUTES", 60))

    @property
    def BILI_QUALITY(self) -> str:
        return str(self._cfg_get("BILI_QUALITY", "1080P"))

    @property
    def BILI_COOKIE_MONITOR_ENABLED(self) -> bool:
        return bool(self._cfg_get("BILI_COOKIE_MONITOR_ENABLED", True))

    @property
    def BILI_COOKIE_CHECK_INTERVAL(self) -> int:
        val = int(self._cfg_get("BILI_COOKIE_CHECK_INTERVAL", 3600))
        return max(60, val)

    @property
    def BILI_NOTIFY_USER_ID(self) -> str:
        return str(self._cfg_get("BILI_NOTIFY_USER_ID", ""))

    # ==================== Cloudflare 截图 Fallback ====================

    @property
    def CLOUDFLARE_FALLBACK_ENABLED(self) -> bool:
        """是否启用 Cloudflare 截图 fallback"""
        return bool(self._cfg_get("CLOUDFLARE_FALLBACK_ENABLED", False))

    @property
    def CLOUDFLARE_ACCOUNT_ID(self) -> str:
        """Cloudflare 账号 ID"""
        return str(self._cfg_get("CLOUDFLARE_ACCOUNT_ID", ""))

    @property
    def CLOUDFLARE_API_TOKEN(self) -> str:
        """Cloudflare API Token（需要 Browser Rendering - Edit 权限）"""
        return str(self._cfg_get("CLOUDFLARE_API_TOKEN", ""))

    @property
    def CLOUDFLARE_TIMEOUT(self) -> int:
        """截图 API 超时时间（秒）"""
        return int(self._cfg_get("CLOUDFLARE_TIMEOUT", 60))

    @property
    def CLOUDFLARE_VIEWPORT_WIDTH(self) -> int:
        """截图视窗宽度"""
        return int(self._cfg_get("CLOUDFLARE_VIEWPORT_WIDTH", 1280))

    @property
    def CLOUDFLARE_VIEWPORT_HEIGHT(self) -> int:
        """截图视窗高度"""
        return int(self._cfg_get("CLOUDFLARE_VIEWPORT_HEIGHT", 720))

    @property
    def CLOUDFLARE_WAIT_UNTIL(self) -> str:
        """页面加载等待策略"""
        val = str(self._cfg_get("CLOUDFLARE_WAIT_UNTIL", "networkidle0")).strip().lower()
        if val not in {"load", "domcontentloaded", "networkidle0", "networkidle2"}:
            return "networkidle0"
        return val

    @property
    def CLOUDFLARE_GOTO_TIMEOUT(self) -> int:
        """页面加载超时（毫秒）"""
        return max(0, int(self._cfg_get("CLOUDFLARE_GOTO_TIMEOUT", 45000)))

    @property
    def CLOUDFLARE_FULL_PAGE(self) -> bool:
        """是否整页截图"""
        return bool(self._cfg_get("CLOUDFLARE_FULL_PAGE", False))

    @property
    def CLOUDFLARE_DEVICE_SCALE_FACTOR(self) -> float:
        """截图清晰度（deviceScaleFactor）"""
        try:
            val = float(self._cfg_get("CLOUDFLARE_DEVICE_SCALE_FACTOR", 1))
        except (TypeError, ValueError):
            val = 1.0
        return val if val > 0 else 1.0

    @property
    def CLOUDFLARE_OMIT_BACKGROUND(self) -> bool:
        """是否隐藏默认白色背景（仅 png 有效）"""
        return bool(self._cfg_get("CLOUDFLARE_OMIT_BACKGROUND", False))

    @property
    def CLOUDFLARE_SCREENSHOT_TYPE(self) -> str:
        """截图格式（png/jpeg）"""
        val = (
            str(self._cfg_get("CLOUDFLARE_SCREENSHOT_TYPE", "png"))
            .strip()
            .lower()
            .lstrip(".")
        )
        if val == "jpg":
            val = "jpeg"
        return val if val in {"png", "jpeg"} else "png"

    @property
    def CLOUDFLARE_SCREENSHOT_QUALITY(self) -> int:
        """截图质量（仅 jpeg 有效，0 表示不指定）"""
        return max(
            0, min(100, int(self._cfg_get("CLOUDFLARE_SCREENSHOT_QUALITY", 0)))
        )

    @property
    def CLOUDFLARE_SELECTOR(self) -> str:
        """指定元素截图 CSS 选择器"""
        return str(self._cfg_get("CLOUDFLARE_SELECTOR", "") or "").strip()

    @property
    def CLOUDFLARE_WAIT_FOR_SELECTOR(self) -> str:
        """等待元素出现的 CSS 选择器"""
        return str(self._cfg_get("CLOUDFLARE_WAIT_FOR_SELECTOR", "") or "").strip()

    @property
    def CLOUDFLARE_WAIT_FOR_TIMEOUT(self) -> int:
        """等待元素超时（毫秒），0 表示不指定"""
        return max(0, int(self._cfg_get("CLOUDFLARE_WAIT_FOR_TIMEOUT", 0)))

    @property
    def CLOUDFLARE_USER_AGENT(self) -> str:
        """自定义 User-Agent"""
        return str(self._cfg_get("CLOUDFLARE_USER_AGENT", "") or "").strip()

    @property
    def CLOUDFLARE_EXTRA_HEADERS(self) -> str:
        """附加请求头（JSON 字符串）"""
        return str(self._cfg_get("CLOUDFLARE_EXTRA_HEADERS", "") or "")

    @property
    def CLOUDFLARE_COOKIES(self) -> str:
        """附加 Cookie（JSON 字符串）"""
        return str(self._cfg_get("CLOUDFLARE_COOKIES", "") or "")

    @property
    def CLOUDFLARE_CACHE_TTL(self) -> int:
        """截图缓存时间（秒），0 表示不缓存"""
        return max(0, min(86400, int(self._cfg_get("CLOUDFLARE_CACHE_TTL", 0))))

    @property
    def CLOUDFLARE_BLACKLIST(self) -> list[str]:
        """Cloudflare 截图黑名单（域名/通配符/关键词，逗号或换行分隔）"""
        from .cloudflare_screenshot import normalize_blacklist

        return normalize_blacklist(self._cfg_get("CLOUDFLARE_BLACKLIST", []))

    @property
    def DEBUG_LOG_ENABLED(self) -> bool:
        """是否启用详细错误日志"""
        return bool(self._cfg_get("DEBUG_LOG_ENABLED", True))


def init_config(astrbot_config: Any, cache_dir: Path, config_dir: Path) -> ParserConfig:
    global _config
    _config = ParserConfig(astrbot_config, cache_dir, config_dir)
    return _config


def get_config() -> ParserConfig:
    global _config
    if _config is None:
        raise RuntimeError("ParserConfig not initialized yet")
    return _config
