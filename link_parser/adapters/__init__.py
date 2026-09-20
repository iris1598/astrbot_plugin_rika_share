"""平台解析适配器包。

导入本包即完成全部内置适配器的注册：每个适配器模块都会在末尾调用
:func:`~link_parser.adapters.registry.register_adapter` 声明平台名、触发 URL 正则与构建方式。

新增一个平台适配器：

1. 新增 ``<name>.py``：继承 :class:`~link_parser.adapters.base.BaseParser`，用
   ``@handle(keyword, pattern)`` 标注各 URL 形态的处理函数，并在模块末尾注册；
2. 把该模块加入下方的 ``_ADAPTER_MODULES``（本文件的 ``import`` 语句）。

其余代码（入口的事件过滤器、解析器实例化、平台禁用判断）均从注册表读取，
无需再改动。
"""

from . import (
    bilibili,
    douyin,
    kuaishou,
    weibo,
    xiaohongshu,
    twitter,
    nga,
    acfun,
)
from .base import BaseParser, handle
from .registry import (
    AdapterBuildContext,
    AdapterSpec,
    adapter_names,
    get_adapter,
    iter_adapters,
    register_adapter,
)

#: 内置适配器模块。顺序决定 ``iter_adapters()`` 的返回顺序。
_ADAPTER_MODULES = (
    bilibili,
    douyin,
    kuaishou,
    weibo,
    xiaohongshu,
    twitter,
    nga,
    acfun,
)

__all__ = [
    "AdapterBuildContext",
    "AdapterSpec",
    "BaseParser",
    "adapter_names",
    "get_adapter",
    "handle",
    "iter_adapters",
    "register_adapter",
]
