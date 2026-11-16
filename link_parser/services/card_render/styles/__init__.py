"""卡片样式包（自动发现）。

导入本包即完成全部内置样式的注册：本目录下每个模块都会被自动导入，模块末尾的
:func:`~link_parser.services.card_render.styles.registry.register_style` 调用即完成自注册。

**新增一个样式只需新建一个模块** ``styles/<name>.py``：

1. 继承 :class:`~link_parser.services.card_render.styles.base.CardStyle`；
2. 实现 ``render()``（返回 ``self.save(canvas)``）；
3. 在模块末尾 ``register_style(StyleSpec(style_cls=YourStyle))``。

不需要改 ``renderer.py``、配置清单或页面——配置下拉、渲染分发与回归脚本
全部从本注册表读取。单个样式模块导入失败（缺依赖、语法错误）只会跳过该
样式并记日志，不会连带整个插件加载失败。
"""

from __future__ import annotations

import importlib
import pkgutil

from astrbot.api import logger

from .base import CardStyle
from .registry import (
    DEFAULT_PRIORITY,
    DEFAULT_STYLE,
    StyleSpec,
    get_style,
    iter_styles,
    register_style,
    style_names,
)

#: 注册表基础设施模块，不是卡片样式，不参与自动导入。
_NON_STYLE_MODULES = frozenset({"base", "registry"})


def _discover_styles() -> None:
    """导入本包下全部样式模块，触发各自的 ``register_style``。"""
    module_names = sorted(
        info.name
        for info in pkgutil.iter_modules(__path__)
        if not info.name.startswith("_") and info.name not in _NON_STYLE_MODULES
    )
    for module_name in module_names:
        try:
            importlib.import_module(f"{__name__}.{module_name}")
        except Exception as exc:  # noqa: BLE001 - 一个坏样式不该拖垮整个插件
            logger.error(
                f"[link_parser] 卡片样式模块 {module_name} 导入失败，"
                f"已跳过该样式: {exc}",
                exc_info=True,
            )


_discover_styles()

#: 导入完成后冻结的样式名快照，供旧脚本与兼容导出使用
STYLE_NAMES: tuple[str, ...] = tuple(style_names())

__all__ = [
    "DEFAULT_PRIORITY",
    "DEFAULT_STYLE",
    "STYLE_NAMES",
    "CardStyle",
    "StyleSpec",
    "get_style",
    "iter_styles",
    "register_style",
    "style_names",
]
