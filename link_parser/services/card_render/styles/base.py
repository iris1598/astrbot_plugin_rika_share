"""卡片样式基类。

一个样式 = 一个 :class:`CardStyle` 子类 + 模块末尾的
:func:`~link_parser.services.card_render.styles.registry.register_style` 调用。
样式通过继承 :class:`~link_parser.services.card_render.toolkit.DrawingKit`
获得全部绘图工具与本次渲染的上下文（宽度、配色、平台色、解析结果、图片路径）。
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from ..toolkit import DrawingKit


class CardStyle(DrawingKit):
    """一张卡片的完整版式。每个样式一个子类、一个模块。"""

    #: 小写标识符：注册表键名，也是配置项 ``RENDER_STYLE`` 的取值
    name: ClassVar[str] = ""
    #: 设置页展示名
    display_name: ClassVar[str] = ""
    #: 设置页一句话说明
    description: ClassVar[str] = ""
    #: 视觉版本：改动版式时 +1，卡片文件名摘要随之变化
    version: ClassVar[int] = 1
    #: 排序权重；内置样式占 10-40，新样式默认 100 排在末尾
    priority: ClassVar[int] = 100
    #: ``can_render()`` 为假时回退到哪个样式
    fallback: ClassVar[str | None] = None
    #: 支持的配色轴；``None`` 表示 dark / light 都支持，``()`` 表示固定配色
    palettes: ClassVar[tuple[str, ...] | None] = None
    #: 是否支持「无水印底卡 + 动态叠印署名」跨人格共享缓存
    supports_dynamic_footer: ClassVar[bool] = True

    def can_render(self) -> bool:
        """当前内容是否适用本样式；默认适用。"""
        return True

    def render(self) -> Path:
        """同步绘制、保存 PNG 到 ``self.out_path`` 并返回该路径。"""
        raise NotImplementedError
