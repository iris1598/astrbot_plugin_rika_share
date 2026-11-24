# 解析器（平台适配器）开发指南

本文档面向插件维护者与第三方扩展开发者，说明如何为 `astrbot_plugin_rika_share` 编写新的平台解析器（Parser Adapter）。

本插件同时支持两种扩展模式：

| 扩展方式 | 适用场景 | 放置位置 | 注册入口 |
| :--- | :--- | :--- | :--- |
| **内置适配器** | 向本插件新增原生平台支持 | `link_parser/adapters/<name>.py` | `register_adapter(AdapterSpec(...))` |
| **外部插件桥接** | 在其他独立 AstrBot 插件中向本插件注册解析能力 | `<其它插件>/rikashare_bridge.py` | 导出 `register(api)`，调用 `api.parser(...)` |

---

## 一、命名与发现机制

### 1.1 内置适配器自动发现

`link_parser/adapters/__init__.py` 中的 `_discover_adapters()` 会通过 `pkgutil.iter_modules` 自动扫描 `link_parser/adapters/` 下的模块：

- 自动跳过 `_NON_ADAPTER_MODULES`（`base`、`registry`）以及以下划线 `_` 开头的模块（例如 `_external.py`）。
- 单个适配器模块导入失败时，仅记录 `ERROR` 日志并继续加载其余模块，不会拖垮整个插件。
- 模块内只需在顶层调用 `register_adapter(AdapterSpec(...))`（通常赋值给模块常量 `ADAPTER`），系统即可完成发现与装配。

### 1.2 命名规范与优先级

`link_parser/adapters/registry.py` 对注册名和优先级有以下约定：

- `name` 必须匹配正则 `^[a-z][a-z0-9_]*$`（小写字母开头，仅含小写字母、数字和下划线）。
- `DEFAULT_PRIORITY = 100`。内置适配器通常分布在 `10`–`80` 之间；数值越小越优先参与 URL 匹配。
- 注册查询与遍历 API：`register_adapter`、`get_adapter`、`iter_adapters`、`adapter_names`。

---

## 二、方式 A：编写内置适配器

### 2.1 目录与骨架

在 [link_parser/adapters/](../link_parser/adapters) 下新建 `<name>.py`（可参考极简模板 [github.py](../link_parser/adapters/github.py)）。最小结构如下：

```python
import re
from typing import ClassVar

from astrbot.api import logger

from ..models import Platform
from .base import BaseParser, handle
from .registry import AdapterBuildContext, AdapterSpec, register_adapter


class ExampleParser(BaseParser):
    platform: ClassVar[Platform] = Platform(name="example", display_name="示例平台")

    # 可选：声明短链域名关键字，供前置短链识别与缓存逻辑使用
    SHORT_LINK_KEYWORDS: ClassVar[tuple[str, ...]] = ("ex.mp",)

    # 可选：内容去重/缓存 TTL（秒）；未设置时遵循全局默认值
    CACHE_TTL_SECONDS: ClassVar[int | None] = None

    @handle("ex.mp", r"https?://ex\.mp/(?P<short_id>[A-Za-z0-9]+)")
    async def _handle_short(self, text: str):
        return await self.parse_with_redirect(text)

    @handle("example.com/post/", r"https?://(?:www\.)?example\.com/post/(?P<post_id>\d+)")
    async def _handle_post(self, text: str):
        # 在此处通过 self.downloader / 异步客户端拉取详情
        author = self.create_author("作者名", avatar_url=None, description=None)
        return self.result(
            url=text,
            title="示例标题",
            text="正文摘要",
            author=author,
            contents=self.create_images(["https://example.com/cover.jpg"]),
            extra={"content_type": "动态"},
        )


def _build_example(ctx: AdapterBuildContext) -> ExampleParser:
    # ctx 提供 .downloader (StreamDownloader), .config (ParserConfig), .config_dir (Path)
    return ExampleParser(ctx.downloader)


ADAPTER = register_adapter(
    AdapterSpec(
        name="example",
        url_pattern=re.compile(r"https?://(?:(?:www\.)?example\.com/post/\d+|ex\.mp/[A-Za-z0-9]+)"),
        parser_cls=ExampleParser,
        description="示例平台解析器",
        build=_build_example,
        priority=100,
    )
)
```

> [!NOTE]
> `AdapterBuildContext` 包含 `.downloader`（`StreamDownloader`）、`.config`（`ParserConfig`）与 `.config_dir`（`Path`）。若无需自定义构造参数，可省略 `build`，由默认工厂直接传入 `ctx.downloader` 实例化 `parser_cls`。

### 2.2 `@handle` 路由与匹配顺序

`BaseParser.__init_subclass__` 会对当前类声明的 `_key_patterns` 按 `-len(keyword)` 降序排序：

- **更长/更具体的 `keyword` 优先匹配**，避免短关键词截胡长路径规则。
- 常见方法分工：
  - `@handle(keyword, pattern)`：绑定触发关键词与正则规则。
  - `search_url(url)` / `parse(...)`：执行 URL 查找与分发解析。
  - `parse_with_redirect(url, headers=None)` / `short_link_headers()`：先跟随短链重定向，再重新走解析流程。

### 2.3 短链重定向与缓存去重键

`BaseParser` 内置了重定向解析与防抖去重身份提取工具（定义于 [base.py](../link_parser/adapters/base.py)）：

| 成员 / 方法 | 用途说明 |
| :--- | :--- |
| `SHORT_LINK_KEYWORDS` | 声明短链关键词元组，配合 `is_short_link`、`short_link_headers()` 处理短链预解析 |
| `IDENTITY_PATTERNS` | `(name, Pattern)` 元组，用于从 URL 中提取标准内容唯一键 |
| `CACHE_TTL_SECONDS` | 覆盖平台级缓存有效期（秒） |
| `get_redirect_url` / `get_final_url` / `resolve_url` | 获取短链跳转目标或最终真实 URL |
| `identity_from_match(keyword, groups)` | 基于正则命名分组生成缓存键 |
| `identity_from_patterns(url)` / `identity_from_text` | 按 `IDENTITY_PATTERNS` 或文本特征提取身份键 |
| `url_fallback_identity(text)` | 无结构化 ID 时的 URL 兜底身份键 |
| `cache_identity` | 将提取到的身份键与当前解析流程绑定 |

---

## 三、构造 `ParseResult` 与媒体辅助方法

所有解析结果统一返回 `ParseResult`（模型定义位于 [result.py](../link_parser/models/result.py)）。

### 3.1 `ParseResult` 核心字段

- `platform`：`Platform` 对象（含平台标识与展示名；主题配色会自动读取卡片主题中的 `PLATFORM_COLORS`，未收录的平台会自动回退到默认紫色 `#8B7CF6`）。
- `author`：`Author` 对象，推荐用 `create_author(name, avatar_url=None, description=None)` 构建。
- `title` / `text` / `timestamp` / `url`：基础文本元数据与规范链接。
- `contents: list[MediaContent]`：主媒体内容（视频、音频、图集等）。
- `graphics: list[str | ImageContent]`：图文混排或附加图片资源。
- `extra: dict[str, Any]`：扩展元信息字典，用于驱动卡片文案、媒体形态标记与统计条。
- `repost: ParseResult | None`：转发/引用原帖的嵌套 `ParseResult`（卡片与节点分发会自动识别 `repost`）。

### 3.2 `BaseParser` 媒体工厂与辅助方法

优先复用基类方法，可自动接入限流提示、异步下载任务与体积校验：

- `result(**kwargs)`：生成标准化 `ParseResult`。
- `create_author(name, avatar_url=None, description=None)`：构造作者对象。
- `create_image(url_or_task, alt=None)` / `create_images(image_urls)`：构建单张或多张图片媒体。
- `create_video(url_or_task, cover_url=None, duration=None, is_gif=False)`：构建视频或动图媒体。
- `create_live_photo(image_url, video_url, cover_url=None, duration=None, is_live_photo=True)`：构建实况照片。
- `create_audio(url_or_task, duration=0.0)`：构建音频媒体。
- `_add_limit_warning(result, duration)`：在触发时长/大小限制时向结果附加警告提示。

### 3.3 `extra` 常用约定键与节点模式联动

插件在后处理渲染（卡片生成 + 3 模式分节点发送，定义见 [nodes.py](../link_parser/config/nodes.py)）时会读取以下常见 `extra` 键：

| `extra` 键 | 作用说明 |
| :--- | :--- |
| `content_type` | 内容类型徽章文案（如 `"视频"`、`"图文"`、`"动态"`、`"仓库"`） |
| `duration` | 媒体时长展示值 |
| `stats_line` | 统计指标行文本（如点赞、播放、Star 数等） |
| `repo_line` | 仓库/来源附加摘要行（如 GitHub 仓库标识） |
| `online` | 在线人数 / 直播状态提示 |
| `limit_warnings` | 超限提示文本列表 |
| `is_video` | 显式标记是否为视频内容（参与 `video` / `gallery` / `dynamic` 模式判定） |
| `suppress_text_output` | 为真时抑制纯文本消息输出，仅走卡片或媒体节点 |
| `music_card` | 音乐卡片渲染参数（对应发送节点 `music_card`） |
| `audio_as_file` | 是否强制以群文件/文件消息形式发送音频 |

当前插件的发送节点支持 `NODE_MODES`（`video` / `gallery` / `dynamic`）和 `NODE_CATALOG`（`card`、`header`、`author`、`title_url`、`cover`、`text`、`meta`、`images`、`repost`、`video`、`audio`、`music_card`），合理填充 `ParseResult` 字段和 `extra` 键即可无缝复用全部节点编排与分群配置能力。

---

## 四、方式 B：外部插件桥接（`rikashare_bridge.py`）

如果你希望在另一个独立 AstrBot 插件里扩展解析器，无需修改本插件源码。

### 4.1 发现条件

`link_parser/adapters/_external.py` 会扫描所有安装插件目录：

- 目标文件路径：`data/plugins/<plugin_dir>/rikashare_bridge.py`（也会探测 `astrbot.builtin_stars` 等根路径）。
- 目录内必须存在 `metadata.yaml`。
- 自动忽略以 `.` 或 `_` 开头的目录，以及本插件自身（`_SELF_PLUGIN = "astrbot_plugin_rika_share"`）。
- 加载后所有外部适配器汇总在 `EXTERNAL_ADAPTERS` 中。

### 4.2 最小外部桥接示例

在 `<其它插件>/rikashare_bridge.py` 中导出 `register(api)` 函数即可（SDK 完整定义见 [external.py](../link_parser/external.py)）：

```python
from astrbot.api import logger


def register(api):
    parser = api.parser(
        name="my_site",
        display_name="我的站点",
        url_pattern=r"https?://mysite\.example/item/\d+",
        description="通过外部插件注册的示例解析器",
        priority=api.DEFAULT_PRIORITY,
        short_link_keywords=(),
        cache_ttl_seconds=None,
    )

    @parser.handle("mysite.example/item/", r"https?://mysite\.example/item/(?P<item_id>\d+)")
    async def parse_item(ctx):
        item_id = ctx.group("item_id")
        logger.info(f"解析外部站点条目: {item_id}")
        author = ctx.author("示例作者")
        return ctx.result(
            url=ctx.text,
            title=f"条目 #{item_id}",
            text="由外部桥接插件解析",
            author=author,
            contents=ctx.images(["https://mysite.example/preview.jpg"]),
        )

    parser.register()
```

### 4.3 `ParserAPI` 与 `ParseContext` 可用能力

- `ParserAPI`（别名 `API`）暴露的核心属性与异常：
  - 模型与异常：`Platform`、`ParseResult`、`Author`、`ImageContent`、`AudioContent`、`VideoContent`、`ParseContext`、`ParseException`、`IgnoreException`、`SilentException`、`DEFAULT_PRIORITY`。
  - 构建器：`api.parser(name=..., display_name=..., url_pattern=..., description="", priority=DEFAULT_PRIORITY, short_link_keywords=(), cache_ttl_seconds=None)` 返回 `ExternalParserBuilder`，支持 `@parser.handle(keyword, pattern)` 与 `parser.register()`。
- `ParseContext`（handler 参数 `ctx`）提供的属性与方法：
  - `.platform`、`.text`、`.matched`、`.groups`、`.group(name_or_index, default=None)`
  - `.result(...)`、`.author(...)`、`.image(...)`、`.images(...)`、`.audio(...)`、`.video(...)`
  - `.parse_redirect(url)`

---

## 五、工程规范与调试建议

1. **日志规范**：统一使用 `from astrbot.api import logger`，禁止使用 Python 标准库 `logging` 或 `print()`。
2. **网络规范**：禁止使用同步阻塞的 `requests` 库；请使用通过 `AdapterBuildContext` 注入的 `downloader` 或基于 `httpx` / `aiohttp` 的异步请求。
3. **桥接加载规范**：外部 `rikashare_bridge.py` 请仅通过 `register(api)` 注册解析器，**不要在模块顶层自注册**，以免重复加载或循环导入。
4. **语法与静态检查**：新增适配器后建议运行：

```powershell
ruff check link_parser/
```
