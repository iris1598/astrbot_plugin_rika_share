"""平台解析适配器注册表。

**新增一个平台只需要写一个文件**：在 ``link_parser/adapters/`` 下新建 ``<name>.py``，
继承 :class:`~link_parser.adapters.base.BaseParser`，用 ``@handle(keyword, pattern)``
标注各 URL 形态的处理函数，并在模块末尾调用 :func:`register_adapter`。
本包的 ``__init__`` 会自动发现并导入它，其余环节全部自动生效：

- 入口的事件过滤器正则与 Handler（``main.py`` 按注册表生成，见 ``iter_adapters``）；
- 解析器实例化与平台禁用判断（``main._init_parsers``）；
- 网页设置页的「解析器开关」（``config.registered_platforms``）。

平台名不再要求在 ``PlatformEnum`` 里登记（那只是内置平台的历史常量），
但必须是小写字母开头的标识符样式，因为它同时是注册表键名与 ``DISABLED_PLATFORMS`` 的取值。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型标注，避免运行期循环导入
    from ..config import ParserConfig
    from ..services.downloader import StreamDownloader
    from .base import BaseParser

#: 平台名的合法形态：同时用作注册表键名、``DISABLED_PLATFORMS`` 逗号串取值、
#: 动态 Handler 的方法名，因此限制为小写标识符。
_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

#: 未显式声明 ``priority`` 的平台排在全部内置平台之后（内置平台声明 10-80）。
#: 顺序即解析器构建顺序，也决定网页设置页开关的排列与 ``DISABLED_PLATFORMS`` 拼串顺序。
DEFAULT_PRIORITY: int = 100


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
    priority: int = DEFAULT_PRIORITY

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

    ``name`` 只要求是小写标识符（见 ``_NAME_PATTERN``）：它同时是注册表键名、
    ``DISABLED_PLATFORMS`` 的取值与动态 Handler 的方法名。渲染配色
    （``card_render.theme.PLATFORM_COLORS``）按平台名取色，缺省自动回退默认色，
    因此新平台**不需要**在任何清单里登记。
    """
    if not _NAME_PATTERN.match(spec.name):
        raise ValueError(
            f"适配器平台名不合法：{spec.name!r}（要求小写字母开头，"
            f"后接小写字母 / 数字 / 下划线）"
        )
    _ADAPTERS[spec.name] = spec
    return spec


def get_adapter(name: str) -> AdapterSpec | None:
    """按平台名取适配器元信息，不存在时返回 ``None``。"""
    return _ADAPTERS.get(name)


def iter_adapters() -> tuple[AdapterSpec, ...]:
    """按 ``priority`` 升序返回全部适配器（同值保持注册先后）。

    注册顺序**不依赖导入顺序**——自动发现按文件名字母序导入，而这里的顺序决定
    解析器构建顺序、JSON 卡片里「哪个平台先认领链接」、设置页开关排列与
    ``DISABLED_PLATFORMS`` 拼串顺序，所以必须显式声明。
    """
    return tuple(sorted(_ADAPTERS.values(), key=lambda spec: spec.priority))


def adapter_names() -> list[str]:
    """已注册的平台名列表（顺序同 :func:`iter_adapters`）。"""
    return [spec.name for spec in iter_adapters()]


__all__ = [
    "AdapterBuildContext",
    "AdapterSpec",
    "adapter_names",
    "get_adapter",
    "iter_adapters",
    "register_adapter",
]
