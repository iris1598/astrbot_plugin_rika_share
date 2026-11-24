"""运行时配置访问与持久化封装。"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterator

from .groups import GroupConfigManager
from .nodes import normalize_node_rules
from .schema import (
    CONFIG_META,
    _ITEM_BY_KEY,
    _KEY_GROUP_MAP,
    coerce_value,
    registered_styles,
)

_config: "ParserConfig | None" = None
_active_config_var: ContextVar["ParserConfig | None"] = ContextVar(
    "link_parser_active_config",
    default=None,
)


class ParserConfig:
    """解析器运行时配置访问器（支持分群稀疏覆写视图）。"""

    def __init__(
        self,
        astrbot_config: Any,
        cache_dir: Path,
        config_dir: Path,
        *,
        overrides: dict[str, Any] | None = None,
        group_manager: GroupConfigManager | None = None,
    ):
        self._cfg = astrbot_config
        self.cache_dir = cache_dir
        self.config_dir = config_dir
        self._overrides: dict[str, Any] | None = dict(overrides) if overrides else None
        self.groups: GroupConfigManager = (
            group_manager if group_manager is not None else GroupConfigManager(config_dir)
        )

    def scoped(
        self,
        umo: str | None = None,
        group_id: str | None = None,
    ) -> tuple[str | None, "ParserConfig"]:
        """返回合入指定群组覆写后的配置视图；无覆写时复用自身。"""
        matched_scope, overrides = self.groups.resolve_overrides(umo, group_id)
        if not overrides:
            return matched_scope, self
        return matched_scope, ParserConfig(
            self._cfg,
            self.cache_dir,
            self.config_dir,
            overrides=overrides,
            group_manager=self.groups,
        )

    # ---------------- WebUI 读写 ---------------- #

    def current_values(self) -> dict[str, Any]:
        """返回全部配置项的当前生效值（键 → 值）。"""
        return {
            item["key"]: self._cfg_get(item["key"], item["default"])
            for item in CONFIG_META
        }

    def apply_updates(self, payload: Any) -> tuple[list[str], list[str]]:
        """按白名单把 WebUI 提交的值校验并写回配置。"""
        if not isinstance(payload, dict):
            return [], ["提交内容不是对象"]

        changed: list[str] = []
        errors: list[str] = []

        for key, raw in payload.items():
            item = _ITEM_BY_KEY.get(key)
            if item is None:
                errors.append(f"未知配置项：{key}")
                continue
            value, error = coerce_value(item, raw)
            if error is not None:
                errors.append(error)
                continue
            if self._cfg_get(key, item["default"]) == value:
                continue
            group = _KEY_GROUP_MAP[key]
            group_cfg = self._cfg.get(group)
            if not isinstance(group_cfg, dict):
                group_cfg = {}
                self._cfg[group] = group_cfg
            group_cfg[key] = value
            changed.append(key)

        if changed and not self.save():
            errors.append(
                "配置已生效但没能写入磁盘，重载插件后会回滚；"
                "请检查配置目录是否可写、磁盘是否已满"
            )
        return changed, errors

    def reset_to_defaults(self) -> list[str]:
        """把全部配置恢复为默认值，返回实际发生改动的键列表。"""
        changed, _ = self.apply_updates(
            {item["key"]: item["default"] for item in CONFIG_META}
        )
        return changed

    def save(self) -> bool:
        """调用 AstrBotConfig.save_config 写盘。"""
        save = getattr(self._cfg, "save_config", None)
        if not callable(save):
            from astrbot.api import logger

            logger.warning(
                "[link_parser] 配置对象没有 save_config，本次修改仅保存在内存中"
            )
            return False
        try:
            save()
            return True
        except Exception:
            from astrbot.api import logger

            logger.exception("[link_parser] 配置写入磁盘失败")
            return False

    # ---------------- 字段读取 ---------------- #

    def _cfg_get(self, key: str, default: Any = None) -> Any:
        if self._overrides is not None and key in self._overrides:
            return self._overrides[key]
        group = _KEY_GROUP_MAP.get(key)
        if group is not None:
            group_cfg = self._cfg.get(group)
            if isinstance(group_cfg, dict) and key in group_cfg:
                return group_cfg[key]
        return self._cfg.get(key, default)

    @property
    def DISABLED_PLATFORMS(self) -> list[str]:
        raw = self._cfg_get("DISABLED_PLATFORMS", "")
        if not raw:
            return []
        return [p.strip().lower() for p in str(raw).split(",") if p.strip()]

    @property
    def VIDEO_DURATION_MAXIMUM(self) -> int:
        return int(self._cfg_get("VIDEO_DURATION_MAXIMUM", 480))

    @property
    def DOUYIN_LIVE_PHOTO_ENABLED(self) -> bool:
        return bool(self._cfg_get("DOUYIN_LIVE_PHOTO_ENABLED", True))

    @property
    def XHS_CK(self) -> str | None:
        return self._cfg_get("XHS_CK", None)

    @property
    def FORWARD_MAX_NODES(self) -> int:
        return max(1, min(50, int(self._cfg_get("FORWARD_MAX_NODES", 10))))

    @property
    def FORWARD_MAX_BATCH_MB(self) -> int:
        return max(1, min(64, int(self._cfg_get("FORWARD_MAX_BATCH_MB", 30))))

    @property
    def TWITTER_MEDIA_PROXY_ENABLED(self) -> bool:
        return bool(self._cfg_get("TWITTER_MEDIA_PROXY_ENABLED", False))

    @property
    def TWITTER_MEDIA_PROXY_BASE(self) -> str:
        return str(self._cfg_get("TWITTER_MEDIA_PROXY_BASE", "") or "").strip().rstrip("/")

    @property
    def BILI_CK(self) -> str | None:
        return self._cfg_get("BILI_CK", None)

    @property
    def BILI_QUALITY(self) -> str:
        return str(self._cfg_get("BILI_QUALITY", "1080P"))

    @property
    def BILI_CODEC(self) -> str:
        val = (
            str(self._cfg_get("BILI_CODEC", "H264")).strip().upper().replace(".", "")
        )
        if val == "AVC":
            val = "H264"
        elif val == "HEVC":
            val = "H265"
        return val if val in {"H264", "H265", "AV1"} else "H264"

    @property
    def BILI_COOKIE_MONITOR_ENABLED(self) -> bool:
        return bool(self._cfg_get("BILI_COOKIE_MONITOR_ENABLED", True))

    @property
    def BILI_COOKIE_CHECK_INTERVAL(self) -> int:
        return max(60, int(self._cfg_get("BILI_COOKIE_CHECK_INTERVAL", 3600)))

    @property
    def CACHE_TTL_HOURS(self) -> int:
        return int(self._cfg_get("CACHE_TTL_HOURS", 24))

    @property
    def CACHE_CLEANUP_INTERVAL_MINUTES(self) -> int:
        return int(self._cfg_get("CACHE_CLEANUP_INTERVAL_MINUTES", 60))

    @property
    def RENDER_ENABLED(self) -> bool:
        return bool(self._cfg_get("RENDER_ENABLED", True))

    @property
    def RENDER_THEME(self) -> str:
        val = str(self._cfg_get("RENDER_THEME", "dark")).strip().lower()
        return val if val in {"dark", "light"} else "dark"

    @property
    def RENDER_STYLE(self) -> str:
        names = {name for name, _ in registered_styles()}
        val = str(self._cfg_get("RENDER_STYLE", "standard")).strip().lower()
        if val and val in names:
            return val
        if "standard" in names:
            return "standard"
        return next(iter(names)) if names else "standard"

    @property
    def RENDER_WIDTH(self) -> int:
        return max(520, min(1080, int(self._cfg_get("RENDER_WIDTH", 800))))

    @property
    def RENDER_FONT_PATH(self) -> str:
        return str(self._cfg_get("RENDER_FONT_PATH", "") or "").strip()

    @property
    def RENDER_COVER_FULL_SIZE(self) -> bool:
        return bool(self._cfg_get("RENDER_COVER_FULL_SIZE", False))

    @property
    def RENDER_PERSONA_WATERMARK(self) -> bool:
        return bool(self._cfg_get("RENDER_PERSONA_WATERMARK", False))

    @property
    def RENDER_BRAND_NAME(self) -> str:
        val = str(self._cfg_get("RENDER_BRAND_NAME", "莉卡解析") or "").strip()
        return val[:16] if val else "莉卡解析"

    @property
    def NODE_RULES(self) -> dict[str, list[dict[str, Any]]]:
        return normalize_node_rules(self._cfg_get("NODE_RULES", ""))

    @property
    def WEBPAGE_FALLBACK_ENABLED(self) -> bool:
        return bool(self._cfg_get("WEBPAGE_FALLBACK_ENABLED", True))

    @property
    def WEBPAGE_TDOCS_JUMP(self) -> bool:
        return bool(self._cfg_get("WEBPAGE_TDOCS_JUMP", True))

    @property
    def CLOUDFLARE_FALLBACK_ENABLED(self) -> bool:
        return bool(self._cfg_get("CLOUDFLARE_FALLBACK_ENABLED", False))

    @property
    def CLOUDFLARE_ACCOUNT_ID(self) -> str:
        return str(self._cfg_get("CLOUDFLARE_ACCOUNT_ID", ""))

    @property
    def CLOUDFLARE_API_TOKEN(self) -> str:
        return str(self._cfg_get("CLOUDFLARE_API_TOKEN", ""))

    @property
    def CLOUDFLARE_TIMEOUT(self) -> int:
        return int(self._cfg_get("CLOUDFLARE_TIMEOUT", 60))

    @property
    def CLOUDFLARE_VIEWPORT_WIDTH(self) -> int:
        return int(self._cfg_get("CLOUDFLARE_VIEWPORT_WIDTH", 1280))

    @property
    def CLOUDFLARE_VIEWPORT_HEIGHT(self) -> int:
        return int(self._cfg_get("CLOUDFLARE_VIEWPORT_HEIGHT", 720))

    @property
    def CLOUDFLARE_WAIT_UNTIL(self) -> str:
        val = str(self._cfg_get("CLOUDFLARE_WAIT_UNTIL", "networkidle0")).strip().lower()
        return val if val in {"load", "domcontentloaded", "networkidle0", "networkidle2"} else "networkidle0"

    @property
    def CLOUDFLARE_GOTO_TIMEOUT(self) -> int:
        return max(0, int(self._cfg_get("CLOUDFLARE_GOTO_TIMEOUT", 45000)))

    @property
    def CLOUDFLARE_FULL_PAGE(self) -> bool:
        return bool(self._cfg_get("CLOUDFLARE_FULL_PAGE", False))

    @property
    def CLOUDFLARE_DEVICE_SCALE_FACTOR(self) -> float:
        try:
            val = float(self._cfg_get("CLOUDFLARE_DEVICE_SCALE_FACTOR", 1))
        except (TypeError, ValueError):
            val = 1.0
        return val if val > 0 else 1.0

    @property
    def CLOUDFLARE_OMIT_BACKGROUND(self) -> bool:
        return bool(self._cfg_get("CLOUDFLARE_OMIT_BACKGROUND", False))

    @property
    def CLOUDFLARE_SCREENSHOT_TYPE(self) -> str:
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
        return max(0, min(100, int(self._cfg_get("CLOUDFLARE_SCREENSHOT_QUALITY", 0))))

    @property
    def CLOUDFLARE_SELECTOR(self) -> str:
        return str(self._cfg_get("CLOUDFLARE_SELECTOR", "") or "").strip()

    @property
    def CLOUDFLARE_WAIT_FOR_SELECTOR(self) -> str:
        return str(self._cfg_get("CLOUDFLARE_WAIT_FOR_SELECTOR", "") or "").strip()

    @property
    def CLOUDFLARE_WAIT_FOR_TIMEOUT(self) -> int:
        return max(0, int(self._cfg_get("CLOUDFLARE_WAIT_FOR_TIMEOUT", 0)))

    @property
    def CLOUDFLARE_USER_AGENT(self) -> str:
        return str(self._cfg_get("CLOUDFLARE_USER_AGENT", "") or "").strip()

    @property
    def CLOUDFLARE_EXTRA_HEADERS(self) -> str:
        return str(self._cfg_get("CLOUDFLARE_EXTRA_HEADERS", "") or "")

    @property
    def CLOUDFLARE_COOKIES(self) -> str:
        return str(self._cfg_get("CLOUDFLARE_COOKIES", "") or "")

    @property
    def CLOUDFLARE_CACHE_TTL(self) -> int:
        return max(0, min(86400, int(self._cfg_get("CLOUDFLARE_CACHE_TTL", 0))))

    @property
    def CLOUDFLARE_BLACKLIST(self) -> list[str]:
        from ..services.web_screenshot import normalize_blacklist

        return normalize_blacklist(self._cfg_get("CLOUDFLARE_BLACKLIST", []))

    @property
    def DEBUG_LOG_ENABLED(self) -> bool:
        return bool(self._cfg_get("DEBUG_LOG_ENABLED", True))

    @property
    def SEND_ERROR_MESSAGES(self) -> bool:
        return bool(self._cfg_get("SEND_ERROR_MESSAGES", False))

    @property
    def WEBUI_THEME(self) -> str:
        val = str(self._cfg_get("WEBUI_THEME", "studio") or "studio").strip().lower()
        return val or "studio"

    @property
    def WEBUI_COLOR_MODE(self) -> str:
        val = str(self._cfg_get("WEBUI_COLOR_MODE", "auto") or "auto").strip().lower()
        return val if val in {"auto", "light", "dark"} else "auto"


def init_config(astrbot_config: Any, cache_dir: Path, config_dir: Path) -> ParserConfig:
    global _config
    _config = ParserConfig(astrbot_config, cache_dir, config_dir)
    return _config


def get_global_config() -> ParserConfig:
    """获取插件全局基础配置（忽略当前协程的分群覆写上下文）。"""
    if _config is None:
        raise RuntimeError("ParserConfig not initialized yet")
    return _config


def get_config() -> ParserConfig:
    """获取当前上下文生效的配置（优先返回分群作用域覆写视图）。"""
    scoped = _active_config_var.get()
    if scoped is not None:
        return scoped
    return get_global_config()


@contextmanager
def scoped_config_for(
    umo: str | None = None,
    group_id: str | None = None,
) -> Iterator[ParserConfig]:
    """为当前协程及其派生子任务绑定指定群组的配置作用域。"""
    base = get_global_config()
    _, scoped = base.scoped(umo=umo, group_id=group_id)
    token = _active_config_var.set(scoped)
    try:
        yield scoped
    finally:
        _active_config_var.reset(token)


__all__ = [
    "ParserConfig",
    "get_config",
    "get_global_config",
    "init_config",
    "scoped_config_for",
]
