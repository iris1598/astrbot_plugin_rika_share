"""卡片样式注册表。

**新增一个卡片样式只需要写一个文件**：在 ``styles/`` 下新建 ``<name>.py``，
继承 :class:`~link_parser.services.card_render.styles.base.CardStyle`，
实现 ``render()``，并在模块末尾调用 :func:`register_style`。
本包的 ``__init__`` 会自动发现并导入它，其余环节全部自动生效：

- 配置项 ``RENDER_STYLE`` 的下拉选项（``config.registered_styles()``）；
- 卡片渲染器的样式分发与回退（``renderer._render_sync``）；
- ``scripts/preview_layouts.py`` 的回归遍历。

样式名同时是注册表键名与 ``RENDER_STYLE`` 的取值，必须是小写字母开头的标识符。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型标注，避免运行期循环导入
    from .base import CardStyle

#: 样式名的合法形态：同时用作注册表键名与 ``RENDER_STYLE`` 的取值
_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

#: 未显式声明 ``priority`` 的样式排在全部内置样式之后（内置占 10-40）。
#: 顺序即设置页下拉顺序，也决定 ``preview_layouts.py`` 的遍历顺序。
DEFAULT_PRIORITY: int = 100

#: 注册表为空或配置值不可用时的兜底样式
DEFAULT_STYLE: str = "standard"


@dataclass(frozen=True, slots=True)
class StyleSpec:
    """单个卡片样式的元信息（展示字段直接取自样式类）。"""

    style_cls: type["CardStyle"]
    priority: int = DEFAULT_PRIORITY

    @property
    def name(self) -> str:
        return self.style_cls.name

    @property
    def display_name(self) -> str:
        return self.style_cls.display_name or self.style_cls.name

    @property
    def description(self) -> str:
        return self.style_cls.description

    @property
    def version(self) -> int:
        return self.style_cls.version

    @property
    def label(self) -> str:
        """设置页选项文案：``name · 展示名（说明）``。"""
        base = f"{self.name} · {self.display_name}"
        if self.description:
            return f"{base}（{self.description}）"
        return base

    def create(self, *args, **kwargs) -> "CardStyle":
        """按注册的样式类实例化（参数原样透传给 ``CardStyle.__init__``）。"""
        return self.style_cls(*args, **kwargs)


_STYLES: dict[str, StyleSpec] = {}


def register_style(spec: StyleSpec) -> StyleSpec:
    """注册（或覆盖注册）一个卡片样式。

    ``name`` 必须是小写标识符；样式类必须是 ``CardStyle`` 子类且声明了
    ``display_name``。同键覆盖便于开发期热重载。
    """
    from .base import CardStyle

    cls = spec.style_cls
    name = getattr(cls, "name", "")
    if not _NAME_PATTERN.match(name or ""):
        raise ValueError(
            f"样式名不合法：{name!r}（要求小写字母开头，"
            "后接小写字母 / 数字 / 下划线）"
        )
    if not isinstance(cls, type) or not issubclass(cls, CardStyle):
        raise TypeError(f"样式 {name} 必须继承 CardStyle")
    if not getattr(cls, "display_name", ""):
        raise ValueError(f"样式 {name} 缺少 display_name")
    _STYLES[name] = spec
    return spec


def get_style(name: str) -> StyleSpec | None:
    """按样式名取元信息，不存在时返回 ``None``。"""
    return _STYLES.get(name)


def iter_styles() -> tuple[StyleSpec, ...]:
    """按 ``priority`` 升序返回全部样式（同值保持注册先后）。"""
    return tuple(sorted(_STYLES.values(), key=lambda spec: spec.priority))


def style_names() -> list[str]:
    """已注册的样式名列表（顺序同 :func:`iter_styles`）。"""
    return [spec.name for spec in iter_styles()]


__all__ = [
    "DEFAULT_PRIORITY",
    "DEFAULT_STYLE",
    "StyleSpec",
    "get_style",
    "iter_styles",
    "register_style",
    "style_names",
]
