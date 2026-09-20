"""平台解析适配器注册表。

新增一个平台适配器的最小步骤：

1. 在 ``link_parser/adapters/`` 下新建 ``<name>.py``，继承 :class:`~link_parser.adapters.base.BaseParser`，
   用 ``@handle(keyword, pattern)`` 标注各 URL 形态的处理函数；
2. 在模块末尾调用 :func:`register_adapter` 声明平台名、触发 URL 正则与构建方式；
3. 在 ``link_parser/adapters/__init__.py`` 中 ``import`` 该模块（触发自注册）。

入口文件（``main.py``）只依赖本注册表：事件过滤器的正则、解析器实例化、
平台禁用判断都从注册表读取，因此新增平台无需改动入口的事件注册逻辑。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from ..constants import PlatformEnum

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型标注，避免运行期循环导入
    from ..config import ParserConfig
    from ..services.downloader import StreamDownloader
    from .base import BaseParser


@dataclass(frozen=True, slots=True)
class AdapterBuildContext:
    """构建适配器实例时可用的运行时依赖。"""

    downloader: "StreamDownloader"
    config: "ParserConfig"
    config_dir: Path


@dataclass(frozen=True, slots=True)
class AdapterSpec:
    """单个平台适配器的元信息。"""

    name: str
    url_pattern: re.Pattern[str]
    parser_cls: type["BaseParser"]
    description: str = ""
    build: Callable[[AdapterBuildContext], "BaseParser"] | None = None

    @property
    def display_name(self) -> str:
        """平台展示名（取自解析器的 ``platform`` 声明）。"""
        return self.parser_cls.platform.display_name

    def create(self, context: AdapterBuildContext) -> "BaseParser":
        """按注册的构建方式实例化解析器；未指定时使用默认构造。"""
        if self.build is None:
            return self.parser_cls(context.downloader)
        return self.build(context)


_ADAPTERS: dict[str, AdapterSpec] = {}


def register_adapter(spec: AdapterSpec) -> AdapterSpec:
    """注册（或覆盖注册）一个平台适配器。

    ``name`` 必须是 :class:`~link_parser.constants.PlatformEnum` 中的取值，
    以便平台名、配置项与渲染配色保持一致。
    """
    PlatformEnum(spec.name)
    _ADAPTERS[spec.name] = spec
    return spec


def get_adapter(name: str) -> AdapterSpec | None:
    """按平台名取适配器元信息，不存在时返回 ``None``。"""
    return _ADAPTERS.get(name)


def iter_adapters() -> tuple[AdapterSpec, ...]:
    """按注册顺序返回全部适配器。"""
    return tuple(_ADAPTERS.values())


def adapter_names() -> list[str]:
    """已注册的平台名列表。"""
    return list(_ADAPTERS)


__all__ = [
    "AdapterBuildContext",
    "AdapterSpec",
    "adapter_names",
    "get_adapter",
    "iter_adapters",
    "register_adapter",
]
