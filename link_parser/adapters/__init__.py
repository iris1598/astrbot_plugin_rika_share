"""平台解析适配器包（自动发现）。

导入本包即完成全部适配器的注册：本目录下每个模块都会被自动导入，模块末尾的
:class:`~link_parser.adapters.registry.register_adapter` 调用即完成自注册。

**新增一个平台只需新建一个模块** ``<name>.py``：

1. 继承 :class:`~link_parser.adapters.base.BaseParser`，用
   ``@handle(keyword, pattern)`` 标注各 URL 形态的处理函数；
2. 在模块末尾 ``register_adapter(AdapterSpec(name=..., url_pattern=..., parser_cls=...))``。

不需要 import 它，也不需要改 ``main.py``、配置清单或枚举——入口的事件过滤器正则与
Handler、解析器实例化、平台禁用判断、网页设置页的解析器开关全部从注册表读取。
平台之间的先后由 ``AdapterSpec.priority`` 显式决定（见 :func:`iter_adapters`），
与文件名无关。

单个适配器模块导入失败（缺依赖、语法错误）只会跳过该平台并记日志，
不会连带整个插件加载失败。
"""

from __future__ import annotations

import importlib
import pkgutil

from astrbot.api import logger

from .base import BaseParser, handle
from .registry import (
    DEFAULT_PRIORITY,
    AdapterBuildContext,
    AdapterSpec,
    adapter_names,
    get_adapter,
    iter_adapters,
    register_adapter,
)

#: 注册表基础设施模块，不是平台适配器，不参与自动导入。
_NON_ADAPTER_MODULES = frozenset({"base", "registry"})


def _discover_adapters() -> None:
    """导入本包下全部适配器模块，触发各自的 ``register_adapter``。"""
    module_names = sorted(
        info.name
        for info in pkgutil.iter_modules(__path__)
        if not info.name.startswith("_")
        and info.name not in _NON_ADAPTER_MODULES
    )
    for module_name in module_names:
        try:
            importlib.import_module(f"{__name__}.{module_name}")
        except Exception as exc:  # noqa: BLE001 - 一个坏适配器不该拖垮整个插件
            logger.error(
                f"[link_parser] 适配器模块 {module_name} 导入失败，已跳过该平台: {exc}",
                exc_info=True,
            )


_discover_adapters()

__all__ = [
    "DEFAULT_PRIORITY",
    "AdapterBuildContext",
    "AdapterSpec",
    "BaseParser",
    "adapter_names",
    "get_adapter",
    "handle",
    "iter_adapters",
    "register_adapter",
]
