r"""外部解析器 SDK —— 把「其它插件注入链接解析」做成一个可复用的方法。

**给外部插件作者看的唯一入口。** 外部插件不需要 import 本插件的任何内部模块
（插件在 AstrBot 里的模块根是 ``data.plugins.<目录名>``，写死路径很容易失效），
只要在自己的目录下放一个桥接模块（默认名 ``rikashare_bridge.py``），暴露
``register(api)``，就能把解析器注入本插件的适配器注册表：

```python
# <其它插件>/rikashare_bridge.py

def register(api):
    parser = api.parser(
        name="foo",                       # 小写标识符：注册表键名 / 设置页开关 / Handler 名
        display_name="Foo 视频",           # 设置页展示名
        url_pattern=r"foo\.com",          # 事件过滤器正则
        description="视频（联动 astrbot_plugin_foo）",
    )

    @parser.handle("foo.com", r"foo\.com/video/(?P<vid>\d+)")
    async def _parse_video(ctx):
        vid = ctx.group("vid")
        return ctx.result(
            title=f"视频 {vid}",
            url=ctx.matched,
            graphics=[ctx.image(f"https://foo.com/cover/{vid}.jpg")],
            extra={"content_type": "视频"},
        )

    parser.register()                     # 完成注册
```

生效的环节与内置适配器完全一致（无需再改本插件任何文件）：
事件过滤器与 Handler、解析器实例化、设置页「解析器开关」、卡片渲染、文本输出。
注册时机由本插件控制——它在 ``main.py`` 生成平台 Handler **之前**主动拉取桥接模块
（见 ``adapters/_external.py``），因此不存在「外部插件加载太晚、错过 Handler 生成」的问题。

本模块只做「把能力递到外部插件手里」：``ParserAPI`` 是注入给 ``register(api)`` 的句柄，
``ExternalParserBuilder`` 负责把处理函数包装成 ``BaseParser`` 子类并注册进注册表。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from re import Match, Pattern
from typing import Any, Awaitable, Callable, Sequence

from .adapters.base import BaseParser, handle
from .adapters.registry import DEFAULT_PRIORITY, AdapterSpec, register_adapter
from .exceptions import IgnoreException, ParseException, SilentException
from .models import (
    AudioContent,
    Author,
    ImageContent,
    ParseResult,
    VideoContent,
)
from .models import Platform as _Platform

#: 外部处理函数签名：收到解析上下文，返回 ``ParseResult``。
Handler = Callable[["ParseContext"], Awaitable[ParseResult]]


@dataclass(slots=True)
class ParseContext:
    """一次匹配的解析上下文（外部处理函数的入参）。

    是对 ``BaseParser`` 与 ``re.Match`` 的薄封装：既能读到匹配结果，也能用
    ``result()`` / ``image()`` / ``audio()`` / ``author()`` 这些构造器拼出结果，
    后者会把下载任务惰性提交给本插件的下载器（解析阶段不阻塞）。
    """

    parser: BaseParser
    match: Match[str]

    @property
    def platform(self) -> _Platform:
        """本解析器的平台标识（``name`` / ``display_name``）。"""
        return self.parser.platform

    @property
    def text(self) -> str:
        """触发解析的原始文本（消息全文，短链展开后会变成跳转后的 URL）。"""
        return self.match.string

    @property
    def matched(self) -> str:
        """正则实际匹配到的片段（``match.group(0)``）。"""
        return self.match.group(0)

    @property
    def groups(self) -> dict[str, str | None]:
        """正则的命名分组字典（供 ``cache_identity`` 生成内容标识）。"""
        return self.match.groupdict()

    def group(self, name_or_index: str | int, default: Any = None) -> Any:
        """安全地取分组：取不到时返回 ``default`` 而不是抛异常。"""
        try:
            return self.match.group(name_or_index)
        except (IndexError, KeyError):
            return default

    # ---------------- 结果构造（转发到 BaseParser） ----------------

    def result(self, **kwargs: Any) -> ParseResult:
        """构造 ``ParseResult``（``title`` / ``text`` / ``url`` / ``graphics`` …）。"""
        return self.parser.result(**kwargs)

    def author(
        self,
        name: str,
        avatar_url: str | None = None,
        description: str | None = None,
    ) -> Author:
        """构造作者信息（头像会惰性下载）。"""
        return self.parser.create_author(name, avatar_url, description)

    def image(self, url: str, alt: str | None = None) -> ImageContent:
        """构造一张图片（惰性下载）。"""
        return self.parser.create_image(url, alt)

    def images(self, urls: Sequence[str]) -> list[ImageContent]:
        """批量构造图片。"""
        return self.parser.create_images(list(urls))

    def audio(self, url: str, duration: float = 0.0) -> AudioContent:
        """构造一段音频（惰性下载）。"""
        return self.parser.create_audio(url, duration)

    def video(
        self,
        url: str,
        cover_url: str | None = None,
        duration: float | None = None,
        is_gif: bool = False,
    ) -> VideoContent:
        """构造一段视频（惰性下载；``duration`` 会参与时长上限判断）。"""
        return self.parser.create_video(url, cover_url, duration, is_gif)

    async def parse_redirect(self, url: str) -> ParseResult:
        """先跟随跳转、再用跳转后的 URL 重新匹配并解析（短链处理用）。"""
        return await self.parser.parse_with_redirect(url)


def _handler_method(
    keyword: str, pattern: str, fn: Handler, index: int
) -> Callable[[BaseParser, Match[str]], Awaitable[ParseResult]]:
    """把外部处理函数包装成 ``BaseParser`` 认识的处理方法。"""

    async def _dispatch(self: BaseParser, searched: Match[str]) -> ParseResult:
        result = await fn(ParseContext(self, searched))
        if not isinstance(result, ParseResult):
            raise ParseException(
                f"外部解析器 {self.platform.name} 的「{keyword}」处理函数"
                f"必须返回 ParseResult，实际返回 {type(result).__name__}"
            )
        return result

    _dispatch.__name__ = f"_external_handler_{index}"
    _dispatch.__qualname__ = _dispatch.__name__
    _dispatch.__doc__ = f"外部处理函数：{keyword}"
    return handle(keyword, pattern)(_dispatch)


def _camel(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_")) or "External"


class ExternalParserBuilder:
    """外部解析器构建器：收集 URL 处理函数，最后一次性注册成平台适配器。

    由 :meth:`ParserAPI.parser` 创建，**不要在外部插件里直接实例化**。
    """

    def __init__(
        self,
        *,
        name: str,
        display_name: str,
        url_pattern: str | Pattern[str],
        description: str = "",
        priority: int = DEFAULT_PRIORITY,
        short_link_keywords: Sequence[str] = (),
        cache_ttl_seconds: int | None = None,
    ) -> None:
        self.name = name
        self.display_name = display_name
        self.description = description
        self.priority = priority
        self.short_link_keywords = tuple(short_link_keywords)
        self.cache_ttl_seconds = cache_ttl_seconds
        self.url_pattern = (
            url_pattern.pattern
            if isinstance(url_pattern, re.Pattern)
            else str(url_pattern)
        )
        if not self.url_pattern:
            raise ValueError("url_pattern 不能为空（它是事件过滤器正则）")
        self._handlers: list[tuple[str, str, Handler]] = []

    def handle(self, keyword: str, pattern: str):
        """声明「URL 关键词 + 正则 → 处理函数」。

        与内置适配器的 ``@handle`` 语义一致：关键词先按长度优先匹配，命中后由正则
        捕获分组；**命名分组会自动成为解析缓存的内容标识**（同一内容的不同链接共用缓存）。
        """

        def decorator(fn: Handler) -> Handler:
            self._handlers.append((keyword, pattern, fn))
            return fn

        return decorator

    def _build_parser_class(self) -> type[BaseParser]:
        namespace: dict[str, Any] = {
            "__doc__": f"{self.display_name} 解析器（外部插件注入）",
            "__module__": __name__,
            "platform": _Platform(name=self.name, display_name=self.display_name),
            "SHORT_LINK_KEYWORDS": self.short_link_keywords,
            "CACHE_TTL_SECONDS": self.cache_ttl_seconds,
        }
        for index, (keyword, pattern, fn) in enumerate(self._handlers):
            namespace[f"_external_handler_{index}"] = _handler_method(
                keyword, pattern, fn, index
            )
        return type(f"{_camel(self.name)}Parser", (BaseParser,), namespace)

    def register(self) -> AdapterSpec:
        """把收集到的处理函数注册成一个平台适配器（可重复调用，同键覆盖）。"""
        if not self._handlers:
            raise ValueError(
                f"外部解析器 {self.name} 没有声明任何处理函数，"
                "请先用 @parser.handle(keyword, pattern) 注册"
            )
        spec = register_adapter(
            AdapterSpec(
                name=self.name,
                url_pattern=re.compile(self.url_pattern),
                parser_cls=self._build_parser_class(),
                description=self.description,
                priority=self.priority,
            )
        )
        return spec


class ParserAPI:
    """注入给外部插件 ``register(api)`` 的 SDK 句柄。

    外部插件只依赖这个对象，**不需要 import 本插件的内部模块**：

    - 数据类型 / 异常：直接取属性（``api.ParseResult`` / ``api.SilentException`` …）；
    - 构造解析器：``api.parser(...)`` 返回 :class:`ExternalParserBuilder`。
    """

    Platform = _Platform
    ParseResult = ParseResult
    Author = Author
    ImageContent = ImageContent
    AudioContent = AudioContent
    VideoContent = VideoContent
    ParseContext = ParseContext
    ParseException = ParseException
    IgnoreException = IgnoreException
    SilentException = SilentException
    DEFAULT_PRIORITY = DEFAULT_PRIORITY

    def parser(
        self,
        *,
        name: str,
        display_name: str,
        url_pattern: str | Pattern[str],
        description: str = "",
        priority: int = DEFAULT_PRIORITY,
        short_link_keywords: Sequence[str] = (),
        cache_ttl_seconds: int | None = None,
    ) -> ExternalParserBuilder:
        """声明一个外部解析器。

        Args:
            name: 平台名（小写标识符）。同时是注册表键名、``DISABLED_PLATFORMS``
                的取值与动态 Handler 的方法名。
            display_name: 设置页「解析器开关」与卡片上展示的平台名。
            url_pattern: 事件过滤器正则（字符串或已编译的正则）。
            description: 设置页里的一句话说明。
            priority: 解析器先后顺序（内置平台占 10-80，默认 ``100`` 排末尾）。
            short_link_keywords: 本平台短链域名片段；命中时缓存键会先跟随跳转再判定。
            cache_ttl_seconds: 解析结果缓存有效期；内容含实时数据时才需要设置。
        """
        return ExternalParserBuilder(
            name=name,
            display_name=display_name,
            url_pattern=url_pattern,
            description=description,
            priority=priority,
            short_link_keywords=short_link_keywords,
            cache_ttl_seconds=cache_ttl_seconds,
        )


#: 模块级单例：``adapters/_external.py`` 把它作为 ``register(api)`` 的实参注入。
API = ParserAPI()

__all__ = [
    "API",
    "ExternalParserBuilder",
    "Handler",
    "ParseContext",
    "ParserAPI",
]
