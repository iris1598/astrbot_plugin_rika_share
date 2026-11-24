"""配置子包统一导出。"""

from .runtime import ParserConfig, get_config, init_config
from .schema import (
    CONFIG_GROUPS,
    CONFIG_GROUP_KEYS,
    CONFIG_META,
    CONTROL_PLATFORMS,
    CONTROL_THEME,
    coerce_value,
    config_meta_payload,
    platform_options,
    registered_platforms,
    registered_styles,
    verify_schema_alignment,
)

__all__ = [
    "CONFIG_GROUPS",
    "CONFIG_GROUP_KEYS",
    "CONFIG_META",
    "CONTROL_PLATFORMS",
    "CONTROL_THEME",
    "ParserConfig",
    "coerce_value",
    "config_meta_payload",
    "get_config",
    "init_config",
    "platform_options",
    "registered_platforms",
    "registered_styles",
    "verify_schema_alignment",
]
