# agent.md — 莉卡解析插件 · AI 开发指南

> 本文件面向在本仓库工作的 AI / 开发者：**先读这里再动手**，用于快速定位代码、判断改哪里、改完怎么验证。
> ⚠️ **重要改动后必须同步更新本文件**，规则见最后一节「维护要求」。

---

## 0. 一句话概览

AstrBot 插件：自动识别聊天消息里的分享链接 / JSON 分享卡片 → 抓取解析 → 渲染成分享卡片图，并以下图集 / 视频的形式发送。

| 项 | 值 |
| :--- | :--- |
| 框架 | AstrBot（`requirements.txt` 要求 `astrbot>=3.5.13`），Python 3.10+ |
| 插件注册名 / 展示名 | `@register("链接解析器", ...)` / `metadata.yaml: display_name: 莉卡解析` |
| 插件目录名（= 数据目录名） | `astrbot_plugin_rika_share`（**不要改**） |
| 入口 | `main.py` → 插件类 `ParserPlugin` |
| 实现包 | `link_parser/`（adapters / models / services / output / utils / webui） |
| 配置维护入口 | 插件网页设置页 `pages/rika/`（原生面板只留解析器开关 + Cloudflare 截图开关） |
| 支持平台 | B站、抖音、快手、微博、小红书、Twitter(X)、AcFun、NGA + Cloudflare 网页截图兜底 |
| 上游来源 | 移植自 [nonebot-plugin-parser](https://github.com/fllesser/nonebot-plugin-parser) |

---

## 1. 铁律（改代码前必读）

1. **所有 `@filter.*` Handler 必须写在 `main.py` 里。**
   AstrBot 用 `handler.handler_module_path == 插件模块路径` **精确匹配**来归属 Handler（框架源码 `<AstrBot>/astrbot/core/star/star_handler.py`，不在本仓库）。
   把 Handler 挪到别的模块 → 框架不会注册它，功能静默失效。业务逻辑可以放 `link_parser/`，只有 Handler 壳子必须留在 `main.py`。
   数量基线：**14 个 Handler**；因为 3 个指令额外挂了 `@filter.permission_type`，`grep -c "@filter\." main.py` 会得到 **17**，属正常。
2. **插件类名必须以 `Plugin` 结尾（或名为 `Main`）。**
   框架按 `name.lower().endswith("plugin") or name.lower() == "main"` 找插件类（`star_manager._get_classes`）。现用名 `ParserPlugin`。
3. **不要改插件身份标识**：`metadata.yaml` 的 `name`、目录名、`main.py` 的 `_get_plugin_data_dir()` 中的 `astrbot_plugin_rika_share`、`StarTools.get_data_dir("astrbot_plugin_rika_share")`、`_conf_schema.json` 里的配置键名。
   改了会切断数据目录定位、用户已有配置的读取/迁移。需要改名属于产品决策，先问人。
4. **不要执行 git 远端操作**（`pull` / `push`）。`status` / `diff` / `show` 可以随意用来比对查看；是否提交由人决定。
5. **行为敏感点**：错误文案、日志文案、`extra` 里的键名、输出顺序、消息条数、配置默认值都算「可观察行为」，非必要不要改；必须改时在变更日志里写明。
6. 新增三方依赖要写进 `requirements.txt`；能用可选导入降级的依赖（ffmpeg / Pillow / fontTools / curl_cffi）要保留降级分支。

---

## 2. 目录结构

```text
astrbot_plugin_rika_share/
├── main.py                       # 插件入口：插件类 + 全部 Handler（唯一允许写 Handler 的地方）
├── metadata.yaml                 # 插件元数据（name/display_name/version/repo）
├── _conf_schema.json             # 存储契约：分组项（仅 bool 功能开关可见）+ 旧版扁平项（invisible）
├── requirements.txt
├── agent.md                      # ← 本文件
├── .astrbot-plugin/i18n/         # 网页设置页标题/描述的国际化文案
├── pages/rika/                   # 插件网页设置页（AstrBot 只扫描 pages/<name>/index.html）
│   ├── index.html                #   页面骨架：侧边分组导航 + 内容区 + toast/弹窗容器
│   ├── style.css                 #   设计系统：CSS 变量 + 玻璃拟态卡片 + 明暗两套主题
│   ├── ui.js                     #   零依赖 DOM/表单小工具（h / card / toast / switch …）
│   ├── app.js                    #   框架层：bridge 就绪 → 取配置元数据 → 建导航 → 挂载视图
│   └── views/settings.js         #   设置视图：按分组渲染全部配置项 + 脏值跟踪 + 保存/恢复
├── docs/previews/                # README 用的渲染预览图
├── scripts/                      # 开发辅助脚本（见第 8 节）
│   ├── dev_smoke_test.py         #   独立冒烟测试：B站扫码登录 + 链接解析（自带 astrbot 桩）
│   ├── preview_layouts.py        #   卡片布局回归（4 布局 × 2 主题 × 全尺寸）
│   ├── kaomoji_render_test.py    #   颜文字字体回退回归
│   └── font_coverage_probe.py    #   字体覆盖探测
└── link_parser/                  # 实现主体
    ├── __init__.py               # 分层说明（本文件第 2 节的简短版）
    ├── config.py                 # CONFIG_META（配置项唯一来源）+ ParserConfig + 配置读写/迁移
    │                             #   └─ PLATFORM_SWITCHES：一个平台一个开关，取代 DISABLED_PLATFORMS
    ├── constants.py              # 请求头/超时常量、PlatformEnum、GENERIC_URL_PATTERN
    ├── exceptions.py             # 异常体系（见 5.4）
    ├── webui.py                  # 网页设置页后端接口（config 读取 / 保存 / 恢复默认）
    ├── adapters/                 # 平台解析适配器
    │   ├── __init__.py           # 导入各适配器触发自注册；_ADAPTER_MODULES 是新平台入口清单
    │   ├── registry.py           # AdapterSpec / AdapterBuildContext / register_adapter / iter_adapters
    │   ├── base.py               # BaseParser 基类 + @handle 装饰器 + 解析结果构造工具
    │   └── bilibili.py · douyin.py · kuaishou.py · weibo.py
    │       xiaohongshu.py · twitter.py · nga.py · acfun.py
    ├── models/                   # 数据类型
    │   ├── __init__.py           # 统一导出通用类型
    │   ├── result.py             # ParseResult / Platform / Author / ParseResultKwargs
    │   ├── content.py            # MediaContent / VideoContent / ImageContent / AudioContent
    │   ├── task.py               # PathTask（惰性下载路径包装）
    │   └── platforms/<平台>/     # 各平台接口返回结构（每个平台一个子包，见 5.2）
    ├── services/                 # 有状态服务（一个服务一个模块 / 子系统）
    │   ├── downloader.py         # StreamDownloader：httpx 流式下载，失败回退 curl_cffi；m3u8 分片
    │   ├── card_render/          # 卡片渲染子系统
    │   │   ├── renderer.py       #   ShareCardRenderer + 4 种布局实现
    │   │   ├── theme.py          #   L / THEMES / PLATFORM_COLORS / LAYOUT_NAMES / Pillow 探测
    │   │   ├── fonts.py          #   中文字体探测 + 符号回退字体链（fontTools / fc-list）
    │   │   └── text.py           #   文本清洗、统计行解析、链接与时间格式化
    │   ├── web_screenshot.py     # Cloudflare Browser Rendering 网页截图客户端
    │   ├── live_photo.py         # 实况照片合成（主图 JPEG + XMP 索引 + 尾部 MP4）
    │   └── bilibili_account.py   # B站扫码登录 / Cookie 加密持久化 / 定时监控 / 自动应用
    ├── output/                   # 输出构建
    │   ├── builder.py            # 分平台构建节点内容 + 合并转发 / 纯文本发送 + 媒体单独发送
    │   ├── json_card.py          # JSON 卡片识别、链接提取、EventUrlWrapper
    │   └── replies.py            # error_result（受 SEND_ERROR_MESSAGES 控制）
    └── utils/
        ├── cache.py · media.py（ffmpeg/文件）· formatting.py（文本）· cookie.py
```

**命名与归档约定**（新增文件请遵守）

- 模块名自描述：`web_screenshot.py`、`bilibili_account.py`、`formatting.py`、`replies.py`；不用缩写和代号。
- 一个平台 = `adapters/<平台>.py` + `models/platforms/<平台>/`，两侧一一对应；`adapters/` 里平铺模块，`models/platforms/` 里一个平台一个子包。
- 多模块子系统才用子包（`models/platforms/<平台>/`、`services/card_render/`），单模块保持单文件——不要在同一层里混放文件夹和文件。
- 子包 `__init__.py` 必须显式导出对外接口（`__all__`），调用方只从包根导入。

---

## 3. 运行期数据目录

两个取目录的写法指向同一位置（`<AstrBot>/data/plugin_data/astrbot_plugin_rika_share/`）：

- `main._get_plugin_data_dir()`：`get_astrbot_data_path()/plugin_data/astrbot_plugin_rika_share`
- `StarTools.get_data_dir("astrbot_plugin_rika_share")`：`data/plugin_data/<name>`

| 路径 | 内容 | 由谁写入 |
| :--- | :--- | :--- |
| `cache/` | 下载的图片/视频/音频、渲染卡片 `card_<md5>.png` | `StreamDownloader`、`ShareCardRenderer` |
| `cache/cloudflare_screenshots/` | 网页截图 | `main._do_cloudflare_fallback` |
| `config/bilibili_cookies.json` | B站凭证（`Credential` cookies） | `adapters/bilibili.py` 的 `_save_credential` |
| `bili_cookie_encrypted.json` | Fernet 加密后的 B站 Cookie | `services/bilibili_account.py` |
| `bili_cookie_status.json` | 上次检测状态 / 是否曾失效 | 同上 |
| `.bili_cookie_key` | Fernet 密钥（权限尽量 0600） | 同上 |

缓存清理：`initialize()` 起定时任务（`CACHE_TTL_HOURS` / `CACHE_CLEANUP_INTERVAL_MINUTES`），清理后**同时清空内存缓存** `_content_cache` / `_identity_cache`；`/clear_cache` 做同样的事。**新增任何内存缓存都要挂到这两处清理点。**

内存缓存的另一层失效机制是**按平台声明的 TTL**（`BaseParser.CACHE_TTL_SECONDS`）：磁盘清理是「按小时回收文件」，TTL 是「按秒判断结果是否还准确」，两者互不替代。

---

## 4. 核心数据流（一次解析的完整链路）

```
消息到达
 └─ AstrBot 按 Handler 的 filter 命中（正则 / 指令）
     ├─ 平台正则 Handler（如 bilibili_handler）→ _dispatch(event, "bilibili")
     ├─ json_card_handler      消息含 JSON 卡片组件时（@filter.regex(r".*")）
     └─ cloudflare_fallback_handler  任意 http(s) 链接（@filter.regex(GENERIC_URL_PATTERN)）
         ↓
 _dispatch：若消息含 JSON 卡片组件则直接 return（避免与 json_card_handler 重复解析）
         ↓ 取 self.parsers[平台名]
 _process_url(event, parser)   ← 所有解析流量的唯一主干
   1. parser.cache_identity(url)  → 缓存键「内容标识」（规则见 5.7，
                                    短链会先跟随跳转；结果按原始文本记忆在 _identity_cache）
   2. _content_cache 命中则直接跳到第 4 步（**只写日志、不向对话发消息**）；
      未命中：parser.search_url(url) → (keyword, match) → parser.parse(...) → ParseResult
      （create_* 只提交下载任务，返回 PathTask），再写入 _content_cache[cache_key]
      缓存条目按需过期：超过 parser.CACHE_TTL_SECONDS（见 5.7）则视为未命中重新解析，
      并让卡片代次 +1（新卡片另存文件名，不覆盖可能正在发送的旧图）
   3. build_platform_output(result, platform) → (header, nodes_content)
   4. ShareCardRenderer.render(...)           → 卡片 PNG（失败返回 None）
   5. 有卡片：context.send_message(umo, MessageChain().file_image(...)) 主动发送
        视频：不再发文字摘要；图文/动态：仍发 header + 图集
      无卡片：文本输出，并把 extra["limit_warnings"] 逐条追加为文本
   6. 文本/图集发送：OneBot → send_nodes_batched（按预算拆多条）
                     其他平台 → send_plain_output
   7. try_send_media：单独发视频/音频（图片已在节点里，不重复发）
   8. 异常 → SilentException 静默 / IgnoreException ℹ️ / ParseException ❌
             / DownloadException ⚠️ / 其他 ❌（error_result 受 SEND_ERROR_MESSAGES 控制）
```

**JSON 卡片流程**：`json_card_handler` →（`output/json_card.py`）识别组件、递归提取链接 → 逐个链接试 `parser.search_url`，命中即用 `EventUrlWrapper(event, link)` 把 `message_str` 换成该链接 → 走同一条 `_process_url`。

**Cloudflare 兜底流程**：仅在 `CLOUDFLARE_FALLBACK_ENABLED` 且已配 Account ID / Token 时生效 → 先确认**没有任何适配器**能处理该链接 → 命中 `CLOUDFLARE_BLACKLIST` 则跳过 → 截图成功时 OneBot 发合并转发、其他平台主动发送；失败静默（按 `DEBUG_LOG_ENABLED` 决定是否打日志）。

**输出格式约定**：`header` 形如 `莉卡解析 | 平台名 - 内容类型`（内容类型取 `extra["content_type"]`，抖音会细分 视频/实况/动图/图文）。

---

## 5. 关键接口契约

### 5.1 适配器（新增平台只需 3 步）

1. 新建 `link_parser/adapters/<平台名>.py`：

```python
from ..constants import PlatformEnum
from ..models import Platform
from .base import BaseParser, handle
from .registry import AdapterSpec, register_adapter


class FooParser(BaseParser):
    platform = Platform(name=PlatformEnum.FOO, display_name="Foo")

    @handle("foo.com", r"foo\.com/video/(?P<vid>\d+)")   # 关键词越具体越优先匹配
    async def _parse(self, searched):
        return self.result(title="...", url="...")


ADAPTER = register_adapter(
    AdapterSpec(
        name=PlatformEnum.FOO.value,
        url_pattern=re.compile(r"foo\.com"),     # 给 main.py 的 @filter.regex 用
        parser_cls=FooParser,
        description="视频",
        # 需要额外参数时才写 build：
        # build=lambda ctx: FooParser(ctx.downloader, ck=ctx.config.FOO_CK),
    )
)
```

2. 在 `link_parser/constants.py` 的 `PlatformEnum` 加平台标识（`register_adapter` 会用它校验 `name`）。
3. 在 `link_parser/adapters/__init__.py` 的 `_ADAPTER_MODULES` 里 import 该模块（**顺序 = `iter_adapters()` 顺序 = 解析器构建顺序**）。

自动生效的部分：`main.py` 的过滤正则（`_pattern(name)` 从注册表读）、解析器实例化（`_init_parsers` 遍历注册表）、`/clear_cache`。渲染配色可选加 `card_render/theme.py` 的 `PLATFORM_COLORS`。

**开关要手动补一行**：平台启停读取 `ParserConfig.DISABLED_PLATFORMS`，它由 `config.PLATFORM_SWITCHES`
里的开关推导；新平台不在那张表里时默认启用（不会报错，但用户关不掉），见 5.6。

**注意**：`main.py` 里 8 个平台 Handler 是**静态写死**的（框架要求 Handler 在插件模块内且装饰器在类定义时求值），新增平台时**仍需在 `main.py` 补一个 3 行的 Handler**，只是不需要改过滤正则和实例化逻辑。

### 5.2 平台模型子包约定

- 位置：`models/platforms/<平台>/`，模块名按「接口 / 资源」命名（`video_info.py`、`aweme.py`、`status.py`、`note.py`…）。
- 子包 `__init__.py` **显式导出**响应结构与 `decoder`；多个模块都有 `decoder` 时按语义加前缀：
  `article_decoder` / `status_decoder` / `video_show_decoder` / `explore_decoder` / `discovery_decoder` / `video_info_decoder` / `aweme_decoder` / `init_state_decoder`。
- 适配器**只从子包根导入**（`from ..models.platforms.weibo import status_decoder`），这样调整子包内部拆分不影响适配器。
- 上游没有 JSON 接口、直接解析 HTML 的平台（twitter / nga）没有模型子包，属正常情况。

### 5.3 `ParseResult.extra` 约定键

渲染（`card_render`）与输出（`output/builder.py`）都读它，新增键请同步两处：

| 键 | 含义 | 消费方 |
| :--- | :--- | :--- |
| `content_type` | 内容类型文案（视频/图文/动态/直播/实况/动图/收藏夹…） | header、卡片类型徽章 |
| `stats_line` | 平台统计行（`👍 1.2万 🪙 …`） | 卡片统计徽章 |
| `duration` | 已格式化的时长（`12:34`） | B站输出节点 |
| `online` | 在线人数文案（B站直播/视频） | 输出节点、卡片 |
| `limit_warnings` | 时长超限等警告列表（`list[str]`） | 卡片警告块；无卡片时追加为文本 |
| `info` | B站 AI 总结 | 卡片正文补充 |
| `is_video` | 小红书等「是否视频笔记」 | 输出分支 |

`ParseResult` 的关键属性：`video`（**仅当 `contents` 恰好 1 个且非图片类产物**时才返回）、`img_contents`、`all_grid_images`、`content_type`。
`VideoContent.is_image_like` / `still_path`：动图（Twitter gif）与动态照片（抖音实况）走**图片**通道，不要再当视频发一遍。

### 5.4 异常语义（决定用户看到什么）

| 异常 | 触发场景 | `_process_url` 表现 |
| :--- | :--- | :--- |
| `SilentException` | `search_url` 匹配不到 URL | 完全静默，不回复 |
| `IgnoreException` | 时长超限等「跳过但可解释」 | `ℹ️ <message>`（受 `SEND_ERROR_MESSAGES`） |
| `ParseException` | 接口失败 / 页面结构变化 | `❌ 解析失败: <message>` |
| `DownloadException` | 媒体下载失败 | `⚠️ 下载失败: <message>` |
| 其他异常 | 未预期 | 记 `logger.exception` + `❌ 处理出错: …` |

### 5.5 `PathTask`（惰性下载）

解析阶段只**提交下载任务**，不阻塞；`await path_task.get()` 才真正取路径，`safe_get()` 捕获异常返回 `None`（是否打日志由 `DEBUG_LOG_ENABLED` 控制）。
渲染/输出阶段拿到的一律是 `Path`，失败就跳过该媒体而不是整体失败。改下载相关代码时保持这个语义。

**异常分级**：`safe_get()` 把 `IgnoreException` / `SilentException` 当**控制流**处理——打 DEBUG、不打 traceback。
因为下载任务由 `create_task` 创建，异常只能在这里被取回，早期实现一律 `logger.exception`，
于是「视频时长超限、主动跳过下载」这个**正常分支**也会刷一整段 ERROR + traceback
（`DEBUG_LOG_ENABLED` 默认 True，必现）。新增「按设计跳过」的路径沿用这两个异常即可。

### 5.6 配置读取与网页设置页

- 统一入口：`link_parser.config.get_config()`（未初始化会抛 `RuntimeError`），由 `main.py` 在 `__init__` 里 `init_config(config, cache_dir, config_dir)`。
- **配置项的唯一来源是 `CONFIG_META`**（`config.py`）：一行一个字典，声明 `key/group/label/type/default/hint`
  （`type` 取 `string | text | int | float | bool | select | list`；`secret` 让页面用密码框展示）。
  由它派生 `CONFIG_GROUP_KEYS`、`_LEGACY_DEFAULTS` 与 `config_meta_payload()`，
  即**网页设置页的表单、后端的类型校验、默认值、旧值迁移共用同一份定义**。
- 配置项**同时存在分组键与旧版扁平键**：`_cfg_get()` 先读分组，分组仍是默认值而扁平旧值被改过时优先旧值；启动时 `migrate_grouped_config()` 把旧值搬进分组。
- **新增配置项必须同时改 5 处**：
  1. `link_parser/config.py` 的 `CONFIG_META`（新增条目；要新增分组则同时加 `CONFIG_GROUPS`）
  2. `link_parser/config.py` 的 `ParserConfig`（新增同名 property，供业务代码读取）
  3. `_conf_schema.json` 的分组 `items`（**存储契约**，非开关条目要带 `invisible: true`；
     若该组因此没有任何可见条目，**组对象本身也要加 `invisible: true`**，见下文）
  4. `_conf_schema.json` 底部的旧版扁平条目（`invisible: true`，迁移用；历史上存在的键才需要）
  5. README 配置表
- **维护入口分工**：`_conf_schema.json` 里**只有「解析器开关」组和 `CLOUDFLARE_FALLBACK_ENABLED`
  可见**，其余条目全部 `invisible`（只作存储契约），细节都在插件网页设置页里维护。
  页面保存后由 `main.apply_runtime_config()` 把新值热应用到渲染器 / 解析器 / 截图客户端，
  不需要重载插件；其余配置（时长、Cookie 等）本来就是每次读取时现取，自动生效。
- **组标题必须跟着藏**：AstrBot 渲染插件配置用的是 `AstrBotConfig.vue`，
  它渲染嵌套组的判断是 `!metadata[...].items[key]?.invisible`——**组标题本身只看
  `type === 'object'`，不检查组内还有没有可见条目**。所以「组内条目全被标 invisible」
  时，必须把**组对象**也标上 `invisible: true`，否则原生面板会留下一串只有标题的空卡
  （平台设置 / Twitter 设置 / B站设置 …）。`verify_schema_alignment()` 会校验二者一致。
  `invisible` 只影响渲染：`_config_schema_to_default_config` 与 `check_config_integrity`
  都不读它，所以默认值照旧生成、用户存过的值也不会被剔掉。
- **一致性自检**：`_conf_schema.json` 与 `CONFIG_META` 的键集合、分组归属必须一致
  （AstrBot 会剔除 schema 之外的键，不一致会让用户保存的值在重载时静默丢失）。
  插件启动时 `read_schema_problems()` 自检并逐条打日志；页面顶部也会把问题显示出来。
  `LEGACY_ONLY_KEYS`（当前只有 `DISABLED_PLATFORMS`）是例外：它们只存在于 schema 中供迁移读取，
  不参与键集合比对，但**必须留在 schema 里**（被剔掉就再也读不到老用户的旧值了）。

#### 解析器开关（取代 `DISABLED_PLATFORMS`）

平台启停是**一个平台一个 bool 开关**（`PLATFORM_<NAME>_ENABLED`），不再让用户手填平台名。

| 环节 | 位置 | 说明 |
| :--- | :--- | :--- |
| 开关清单 | `config.PLATFORM_SWITCHES` | `(平台名, 展示名)` 元组，顺序同 `_ADAPTER_MODULES` |
| 键名生成 | `config.platform_switch_key(name)` | `bilibili` → `PLATFORM_BILIBILI_ENABLED` |
| 消费方 | `ParserConfig.DISABLED_PLATFORMS` | 由开关推导，注册表里有开关的新平台默认启用 |
| 旧值迁移 | `config.migrate_platform_switches` | 把旧逗号串搬进开关并**清空旧串**，幂等 |

四条改这块时要注意的：

1. **新增平台适配器要顺手加一个开关**：`PLATFORM_SWITCHES` 加一行 + `_conf_schema.json`
   的「解析器开关」组加同名 bool。漏了不会报错（`_known_platform_names()` 兜底为默认启用），
   但用户就没法在面板/页面里关掉它。
2. **旧串必须清空**。如果只搬不清，用户把开关拨回「启用」时，`_cfg_get` 读到的旧串
   又会把它按回去，表现为「开关拨不动」——迁移函数里同时清了分组与顶层两处。
3. **`DISABLED_PLATFORMS` 不能从 schema 里删**（见 `LEGACY_ONLY_KEYS`）：AstrBot 会剔除
   schema 之外的键，删了就永远读不到老用户的旧值，静默把用户禁用的平台放出来。
4. **开关是唯一真相**，别再加第二条「禁用平台」状态线（比如又保留一份运行时副本）。

### 5.7 缓存键 =「内容标识」（`BaseParser.cache_identity`）

解析结果缓存键**不是原始链接**，而是适配器给出的内容标识，目的是让**同一内容的不同链接共用一条缓存**（不同短链、长短链混用、同一作品的不同分享形态）。

判定阶梯（`cache_identity(text)`，永不抛异常）：

| 级别 | 规则 | 例子 |
| :--- | :--- | :--- |
| 1 | `search_url()` 匹配到的**命名分组**拼接；`page_num=1` 与缺省等价 | `bilibili:bvid=BV1xx411c7mD`、`douyin:aweme_id=7412…`、`nga:tid=456` |
| 2 | 命中 `SHORT_LINK_KEYWORDS` 时先跟随跳转（`resolve_url`，只取 URL 不读响应体），再按 1 / 3 判定 | `b23.tv/aaa` 与 `b23.tv/bbb` → 同一个 `bvid` |
| 3 | 兜底：`utils/url.py::normalize_url` 归一化链接（剔 `TRACKING_PARAMS`、排序 query、去尾斜杠/去 fragment） | 无内容 ID 的分享页 |

适配器的扩展点（都不影响解析逻辑）：

- `SHORT_LINK_KEYWORDS`：本平台短链域名片段（bilibili `b23.tv`、douyin `v.douyin.com`、kuaishou `v.kuaishou.com`、小红书 `xhslink.com`）。
- `IDENTITY_PATTERNS`：`@handle` 正则没有命名分组时的补充规则，形如 `("status", re.compile(r"/status/(?P<id>\d+)"))`（twitter、kuaishou 在用）。
- `identity_from_match(keyword, groups)`：平台特有归一化（微博把 `mid` 转 bid，与 `wid` 形态合并）。
- `short_link_headers()`：个别平台跳转需要移动端 UA / Referer（kuaishou、小红书）。

入口侧（`main.py`）：

- `_identity_cache`：原始文本 → 内容标识，避免同一条链接重复跳转；超过 `_IDENTITY_MEMO_MAX`(2048) 整体清空。
- 内容缓存是 `_content_cache: dict[内容标识, _ContentCacheEntry]`，条目同时持有 `result` / `parsed_at` / `render_path` / `generation`；卡片文件名由 `cache_key` 派生，因此**同一内容稳定复用同一张卡片**（换短链不会重复渲染）。
- 清理点：`initialize()` 的定时清理、`/clear_cache` 都会清空 `_content_cache` / `_identity_cache`。

**已知边界**（有意不统一，改前先想清楚）：

- B站 `BV` 与 `av` 两种编号是不同键（需要 BV↔av 互转才能真正合并）。
- 微博 `video.weibo.com/show?fid=1034:xxx` 与 `weibo.com/{uid}/{bid}` 不合并（fid 与 status id 无法可靠互推）。
- 短链首次出现会多一次跳转请求（仅短链，且被 `_identity_cache` 记忆）。
- 身份里带上内容相关的维度（如 B站 `page_num` 分P）——新增维度时要在 `identity_from_match` 里体现，否则不同内容会串缓存。

### 5.8 缓存有效期（`BaseParser.CACHE_TTL_SECONDS`）

内容标识解决「同一内容 → 同一条缓存」，TTL 解决「**这条缓存还能不能代表现在**」。

- 默认 `None`：进程内长期有效（内容不变的平台不需要设置）。
- B站设 `300`（5 分钟）：它的解析结果带**实时数据**——视频的「🏄 X 人正在观看」、直播间的场次标题/封面。永久缓存会让同一条链接第二次分享时展示过期数字。
- 超时后的行为：重新走完整解析（拿到新数据）→ 卡片 `generation + 1` → **新卡片另存文件名**（不覆盖可能正在被发送的旧图，旧文件由 `CACHE_TTL_HOURS` 回收）。

三个容易踩错的点：

1. **TTL 只在「同一内容被重复分享」时才起作用**。首次分享永远是新解析，所以把 TTL 设小不会明显增加请求量。
2. **必须同时让卡片换代**。`ShareCardRenderer.render` 除了 `existing` 还会检查 `out_path.exists()`，同名文件会让它直接返回旧图——所以重新解析时既要把 `existing` 传 `None`，也要靠 `salt`（代次）改变文件名。
3. **不要把实时字段从 `extra` 里删掉却又依赖它**：`online` 之类的字段由 `builder.py`（文本）和 `card_render/renderer.py`（卡片）共同消费，两边都做了空值守卫。

### 5.9 B站 Cookie 生命周期（单一真相 + 低频校验）

cookie **只由 `BilibiliParser` 持有**：内存 `_credential`，磁盘 `config/bilibili_cookies.json`，构造参数 `_bili_ck`（即配置项 `BILI_CK`，**只读回退**）。
`BiliAccountService` 只做检测与通知，通过 `parser.export_cookie()` 回读、`parser.update_cookie()` 写入。

| 环节 | 行为 |
| :--- | :--- |
| `await parser.credential` | 按 `VALIDATE_INTERVAL`（600s）降频。窗口外：无凭证 → `_init_credential()`；有凭证 → `_revalidate()` |
| `_init_credential()` | **磁盘文件优先，其次配置项**；来源校验失败会被**显式置 None**；成功后调 `_ensure_buvid()` 补齐设备指纹 |
| `_ensure_buvid()` | 补齐 `buvid3` / `buvid4`（扫码登录响应里没有，实测为空）；缺失时 bilibili-api 会**每次请求临时生成**，等于一直换指纹，反而更易被风控 |
| `_credential_cookie_dict()` | 归一化：剔除 `sessdata` / `dedeuserid` / `proxy`（库的**属性名**，不是 cookie 名）与空值，持久化与 `export_cookie()` 共用 |
| `_revalidate()` | 校验不通过 → 重载；`check_refresh()` 为真且 `has_ac_time_value() and has_bili_jct()` → `refresh()` 并落盘；**任何异常只记日志并保留当前凭证** |
| `update_cookie()` | 写文件 + 清空内存凭证 + 重置校验窗口；**刻意不写回 `_bili_ck`** |
| `BiliAccountService.initialize()` | 解析器已有 cookie 就以解析器为准；只有解析器为空才把服务加载到的 cookie **迁移**过去 |
| `check_cookie_valid()` | 检测前先从解析器同步 cookie，保证监控与解析看到同一份 |
| `_refresh_cookie_from_headers()` | **保守合并**：只采纳 `_SESSION_COOKIE_KEYS` 会话字段；`buvid3/buvid4` 仅在原本缺失时补；其余一律不入库 |

**`ac_time_value` 只在扫码登录的响应体里**（`data.refresh_token`），不在 Set-Cookie 中。web 端扫码的凭证分散在
三处，必须由 `_cookies_from_login_payload()` 合并：`data.url` 查询串（SESSDATA / bili_jct / DedeUserID /
DedeUserID__ckMd5）、`data.cookie_info.cookies`（部分渠道）、`Set-Cookie` 头（通常只补 buvid3/buvid4）。
**漏掉 `refresh_token` → `has_ac_time_value()` 恒 False → 日志一直提示「需要刷新」但永远刷新不了。**

排查口径：
- 日志出现「缺少 ac_time_value…无法自动刷新」→ 登录时没拿到续期凭据，重新扫码即可。
- 解析成功但清晰度只有 540P、且日志有「Cookie 已失效，丢弃」→ 凭证确实失效了（不是解析失败，公开接口不需要登录）。
- 改这块时不要引入第二条 cookie 状态线，也不要让配置项的运行时副本被覆盖——历史上正是因为
  `update_cookie` 覆盖了 `_bili_ck`，导致运行期一旦出问题就只能靠重载插件恢复。

### 5.10 网页设置页（`pages/rika` + `link_parser/webui.py`）

AstrBot 只扫描 `pages/<page_name>/index.html`，页面脚本通过 `window.AstrBotPluginPage`
bridge 调后端；后端路由必须带插件名前缀，页面侧写去掉前缀的相对路径。

| 环节 | 位置 | 说明 |
| :--- | :--- | :--- |
| 路由注册 | `link_parser/webui.py::WebUIApi.register` | `GET/POST /astrbot_plugin_rika_share/config`、`POST .../config/reset` |
| 页面挂载 | `main.py::_register_webui` | 老版本 AstrBot 没有 `register_web_api` 时静默跳过，不影响聊天侧功能 |
| 热应用 | `main.py::apply_runtime_config` | 渲染器 / 解析器 / 截图客户端按「构造参数快照」变了才重建 |
| 表单定义 | `config.CONFIG_META` | 页面不硬编码字段，全部由后端下发（改配置只改 `config.py`，页面自适应） |

三条容易踩的约束：

1. **`self.parsers` 必须原地更新**（`clear()` 后重建，不要换新的 dict）。
   `BiliAccountService` 持有的是这个 dict 的引用，换成新对象会让它继续操作已被丢弃的解析器。
2. **页面运行在受限 iframe 里**，拿不到 Dashboard 的 cookie / localStorage，
   所有请求都要走 bridge；相对资源路径由 AstrBot 重写并追加短期 `asset_token`，不要手拼绝对路径。
3. **不要往页面里搬解析/缓存/预览之类的功能**。这页的定位就是「配置维护入口」，
   功能类页面会让配置契约与运行时状态纠缠在一起。

---

## 6. 「我要做 X，改哪里」速查表

| 任务 | 改动位置 | 注意 |
| :--- | :--- | :--- |
| 新增平台解析 | `adapters/<平台>.py` + `constants.PlatformEnum` + `adapters/__init__._ADAPTER_MODULES` + `main.py` 一个 Handler + `config.PLATFORM_SWITCHES` 一个开关 | 见 5.1、5.6；漏了开关只会「默认启用且关不掉」 |
| 改哪些平台被启用 | `config.PLATFORM_SWITCHES` / `PLATFORM_<NAME>_ENABLED` 开关 | 别回头去写 `DISABLED_PLATFORMS` 逗号串，那是被取代的旧写法 |
| 修某平台解析失效 | `adapters/<平台>.py`（+ `models/platforms/<平台>/`） | 先确认是接口变了还是模型字段变了 |
| 调整 URL 触发范围 | 对应适配器 `register_adapter(url_pattern=...)` | `main.py` 的 filter 自动跟随，无需改 |
| 改缓存命中规则 / 加内容标识 | `adapters/base.py` 的 `cache_identity` 阶梯；平台侧声明 `SHORT_LINK_KEYWORDS` / `IDENTITY_PATTERNS` / 覆写 `identity_from_match` | 见 5.7；**别把 token / 时间戳等易变参数带进标识** |
| 改缓存有效期（某平台出现实时数据过期） | 平台适配器声明 `CACHE_TTL_SECONDS` | 见 5.8；改动时确认卡片也跟着换代 |
| 新增 / 修改配置项 | 5 处，见 5.6 | 漏改会导致页面不显示、保存被拒或旧值丢失 |
| 调网页设置页样式 | `pages/rika/style.css`（CSS 变量 / 卡片 / 表单 / 窄屏分段） | 只跟随 `<html data-theme>`，不硬编码浅色底 |
| 调设置页表单与保存逻辑 | `pages/rika/views/settings.js`（+ `ui.js` 的通用控件） | 字段由 `CONFIG_META` 下发，不要在页面里硬编码配置键 |
| 调页面骨架 / 分组导航 | `pages/rika/index.html` + `app.js` | 导航项由后端分组生成，新增分组不用改 HTML |
| 调设置页后端接口 | `link_parser/webui.py` | 只做「取参 → 校验 → 转发 config 读写 → 拼 JSON」 |
| 新增卡片布局 | `card_render/renderer.py`（`_render_<layout>` + `_render_sync` 分发）+ `card_render/theme.py`（`LAYOUT_NAMES`）+ `_conf_schema.json`（`RENDER_LAYOUT.options` 两处）+ README | 无封面场景必须能回退（参考 `_render_immersive`） |
| 新增主题 / 平台配色 | `card_render/theme.py`（`THEMES` / `PLATFORM_COLORS`） | 主题名要同步 schema 的 options 与 `ParserConfig.RENDER_THEME` 白名单 |
| 调字体 / 颜文字回退 | `card_render/fonts.py` | 用 `scripts/kaomoji_render_test.py` 验证 |
| 调文本清洗 / 统计解析 | `card_render/text.py` | 被 renderer 复用，注意别影响 `short_url` 截断 |
| 调「哪个平台发什么」 | `output/builder.py` 的分平台分支 | 保持 header 形如 `莉卡解析 | 平台 - 类型` |
| 调媒体下载 / 重试 / 分片 | `services/downloader.py` | httpx 优先 → 失败回退 curl_cffi；空响应视作失败 |
| 调 ffmpeg（合流 / 抽帧 / 转 GIF） | `utils/media.py` | ffmpeg 缺失要能降级，别让它抛到用户面前 |
| 调实况照片合成 | `services/live_photo.py` | **不要改 XMP 字段名**，相册靠它定位尾部视频 |
| 调 B站 Cookie / 登录 / 监控 | `adapters/bilibili.py`（凭证持有者）+ `services/bilibili_account.py`（检测与通知） | 见 5.9；cookie 只能有一份真相，别新增第二条状态线 |
| 调 Cloudflare 截图参数 | `services/web_screenshot.py` + `_conf_schema.json` | 新增请求体字段要登记到 `CF_KEY_MAP`（snake→camel） |
| 新增指令 | `main.py`（`@filter.command`）+ 逻辑放 `services/*` | Handler 必须在 `main.py`；管理指令加 `@filter.permission_type(ADMIN)` |
| 新增内存缓存 | `main.py` 的 `initialize()` 清理回调 + `/clear_cache` | 两处都要清；能挂进 `_ContentCacheEntry` 的优先挂进去，别新开平行字典 |
| 改 README / 预览图 | `README.md`、`docs/previews/`（图由 `scripts/preview_layouts.py` 产出） | — |

---

## 7. 平台适配器清单

每个平台都有一个独立的启停开关（`PLATFORM_<NAME>_ENABLED`），在原生配置面板与插件网页设置页都能开关，见 5.6。

| 平台 | name | 触发正则（注册表） | 构建参数 | 接口与注意点 |
| :--- | :--- | :--- | :--- | :--- |
| B站 | `bilibili` | `bilibili\.com` / `b23\.tv` / `bili2233\.cn` / `BV…` / `av\d+` | 需 `BILI_CK` + `config_dir` | bilibili_api（优先 curl_cffi）；视频/动态/opus/直播/专栏/收藏夹；-504 与网络超时退避重试 2 次；凭证持久化到 `config/bilibili_cookies.json` |
| 抖音 | `douyin` | `v.douyin.com` / `jx.douyin.com` / `douyin.com` / `iesdouyin.com` / `m.douyin.com` / `jingxuan.douyin.com` | 默认 | aweme detail 接口；`clip_type` 2/None=图、4=动图、5=实况照片，后两者走 `create_live_photo`（受 `DOUYIN_LIVE_PHOTO_ENABLED` 控制） |
| 快手 | `kuaishou` | `v.kuaishou.com` / `kuaishou.com` / `chenzhongtech.com` | 默认 | 先取 Location，把 `/fw/long-video/` 换成 `/fw/photo/`，再解析 `window.INIT_STATE` |
| 微博 | `weibo` | `weibo.com` / `weibo.cn` / `m.weibo.cn` / `video.weibo.com` / `mapp.api.weibo.cn` | 默认 | 三个接口：status（m.weibo.cn）/ video_show（h5.video）/ article（头条文章）；`mid`→`id` 用 base62；403/418 提示风控 |
| 小红书 | `xiaohongshu` | `xhslink.com` / `xhslink.cn` / `xiaohongshu.com` | `XHS_CK`（可选） | 解析页面 `window.__INITIAL_STATE__`（需把 `undefined` 替换成 `null`）；explore 失败自动回退 discovery |
| Twitter/X | `twitter` | `x\.com` | 默认 | 走 `api.vxtwitter.com`；可开自建反代（`TWITTER_MEDIA_PROXY_*`），反代失败自动回退直连；gif 类型走图片通道 |
| NGA | `nga` | `nga.178.com` / `ngabbs.com` / `bbs.nga.cn` | 默认 | 403 且响应含 `guestJs` 时取 Cookie 后带 `rand` 参数重试；解析 `postsubject0` / `postauthor0` / `postdate0` / `postcontent0` |
| AcFun | `acfun` | `acfun.cn` | 默认 | `videoInfo_new` 接口 + `window.videoInfo`；视频走 m3u8 分片下载 |
| 通用网页 | —（非适配器） | `GENERIC_URL_PATTERN` = `https?://…` | — | Cloudflare Browser Rendering 截图兜底，见第 4 节 |

---

## 8. 验证清单（改完必跑）

```bash
# <PY> = 能 `import astrbot` 的 Python 解释器，即 AstrBot 运行环境所使用的解释器
#        （下文命令如需在插件目录下执行，请自行 cd 到插件根目录）

# 1) 静态检查：未定义名 / 未使用导入（需 ruff）
<PY> -m ruff check --select F,E9 --no-cache --exclude __pycache__ .

# 2) 语法编译
<PY> -m compileall -q .

# 3) 渲染回归：4 布局 × 2 主题 × 全尺寸 = 96 张，必须全部成功
<PY> scripts/preview_layouts.py        # 末行应为「共渲染 96 张，全部成功」
<PY> scripts/kaomoji_render_test.py    # 颜文字字体回退

# 4) 导入 + 注册表冒烟（见下方脚本）

# 5) 真机功能冒烟（需要外网；自带 astrbot 桩，不需要 AstrBot 运行环境）
<PY> scripts/dev_smoke_test.py --login <url>       # 扫码登录 + 解析，日志落 scripts/dev_test_out/
<PY> scripts/dev_smoke_test.py --no-download <url> # 只跑解析，不下载媒体
```

> 若当前解释器缺少 `bilibili_api` / `msgspec` / `curl_cffi` / `fontTools`，**不要改动 AstrBot 自身环境的依赖**，
> 用 `pip install --quiet --target <临时目录> …` 安装到临时目录，再以 `PYTHONPATH=<临时目录>` 运行验证脚本即可。
> `scripts/` 下的渲染脚本会自行 stub `astrbot.api.logger`，`dev_smoke_test.py` 还会额外 stub
> `astrbot.api.event` / `astrbot.api.star` / `astrbot.api.message_components`，因此都能脱离 AstrBot 直接跑。

**`scripts/dev_smoke_test.py` 的定位**：唯一能一条命令验证「B站凭证 + 解析 + 下载清晰度」的脚本。
它建一个**与真实插件隔离**的数据目录（`scripts/dev_test_out/`，已 gitignore），
因此不会污染 AstrBot 里的登录态；要复用真实 cookie，把
`<插件数据目录>/config/bilibili_cookies.json` 拷进 `scripts/dev_test_out/config/` 即可。
输出里的「清晰度探测」段落直接列出 B站 给出的 `accept_quality` / `support_formats`，
是判断「凭证到底有没有生效」最直接的证据。

**导入冒烟脚本**（放临时目录，不提交；在 AstrBot 仓库根目录执行）：

```python
# 目的：确认全部模块可导入、8 个适配器已注册、14 个 Handler 已被框架接收
import importlib, pkgutil, sys
sys.path.insert(0, r"<插件父目录>")           # 含 astrbot_plugin_rika_share 目录的那个上级目录

import astrbot_plugin_rika_share as pkg

bad = []
names = [pkg.__name__ + ".main"]
names += [m.name for m in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + ".")]
for n in sorted(set(names)):
    try:
        importlib.import_module(n)
    except Exception as e:                    # noqa: BLE001
        bad.append((n, repr(e)))

from astrbot.core.star.star_handler import star_handlers_registry
from astrbot_plugin_rika_share.link_parser.adapters import adapter_names

handlers = star_handlers_registry.get_handlers_by_module_name(
    "astrbot_plugin_rika_share.main"
)
print("imports_failed :", bad)
print("adapters       :", adapter_names())    # 应为 8 个，顺序固定
print("handlers       :", len(handlers))      # 应为 14
assert not bad and len(handlers) == 14
```

期望基线（2026-09-21 实测）：模块导入 **63/63**（`main.py` + `link_parser/` 下 62 个模块）、适配器 **8 个**（`adapter_names()` 顺序固定）、Handler **14 个**（`grep -c "@filter\." main.py` 为 17，见铁律 1）、配置项 **51 项 / 9 组**（`len(CONFIG_META)`）、原生面板只显示 **2 个分组 / 9 个开关**（「解析器开关」8 个 + 「Cloudflare 基础设置」的 `CLOUDFLARE_FALLBACK_ENABLED`，其余 7 组整组 `invisible`）、渲染 **96 张**全部成功。

**网页设置页**没有随仓库的自动化回归（它跑在受限 iframe 里），改完 `pages/rika/` 后两条路一起走：

1. **真机**：从 WebUI「插件详情 → 莉卡解析」打开页面，确认分组导航、搜索、解析器开关、
   Cookie 遮罩（能显示明文）、保存条、恢复默认与「有改动时刷新要先确认」都正常；
2. **jsdom 冒烟**（能提前抓出「值没写进控件」这类光看代码发现不了的问题，做法见第 9 节最后一条）：
   载入 `index.html` → 挂假 `window.AstrBotPluginPage` → 断言首屏字段数、各控件类型的回填、
   搜索 / 分组导航 / 脏值跟踪 / 保存 / 恢复默认 / 刷新 / 折叠 / 异常路径。

---

## 9. 已知约束与坑

- **Handler 位置**：见铁律 1，这是最容易踩的坑（放进 `link_parser/` 会静默不生效）。
- **`@filter.regex` 不把 match 传进 Handler**：需要 URL 时自己从 `event.message_str` 重新 `search`（`cloudflare_fallback_handler` 就是这么做的）。
- **`json_card_handler` 使用 `@filter.regex(r".*")`**，所有消息都会进它，第一件事就是 `has_json_component` 早退，别在里面加重活。
- **OneBot 才支持合并转发**：`Comp.Nodes` 仅 OneBot v11（`aiocqhttp`）可用；其他平台走 `send_plain_output` + 主动发送（避免 AstrBot「回复时 @」污染图片 markdown）。
- **合并转发的内存风险**：OneBot 会把节点内图片整体 base64，峰值约为原图总量 4 倍 → 用 `FORWARD_MAX_NODES` / `FORWARD_MAX_BATCH_MB` 拆批，不要去掉拆批逻辑。
- **渲染图与文本重复**：视频类内容在卡片成功时不再发文字摘要；图文仍发图集 —— 调整时要保持「不重复、不丢内容」。
- **缓存不区分发送者**：同一内容在同一进程内所有会话共享一条缓存与一张卡片（这是预期行为，别按会话分键）。
- **实时数据必须靠 TTL 兜底，不能靠渲染缓存**：卡片是 `cache_key` 派生的稳定文件，`render()` 见到同名文件会直接复用。任何「会随时间变」的字段（B站 `extra["online"]`、直播间场次标题）都要通过 `CACHE_TTL_SECONDS` 让结果与卡片一起换代，否则会长期展示过期数字，见 5.8。
- **卡片换代不删旧图**：重新解析后新卡片另存文件名（避免覆盖正在发送的旧图），旧文件交给 `CACHE_TTL_HOURS` 回收 —— 因此缓存目录会存在同内容的多代卡片，属正常现象。
- **超时/重发的双发问题**：OneBot 大文件发送可能 retcode 1200（invoke timeout）但实际已发出，回退重发会导致重复 —— 相关判断在 `exceptions.py` 里已删（原 `is_timeout_exception` 未被使用），如需处理请谨慎。
- **可选依赖降级**：Pillow 缺失 → 渲染自动关闭回退文本；fontTools 缺失 → 单字体渲染；ffmpeg 缺失 → 相关媒体处理抛 `RuntimeError`；curl_cffi 缺失 → 下载只用 httpx。
- **页面里给表单控件赋值必须用 DOM 属性、不能用 `setAttribute`**。`<textarea value="…">` 是无效的——
  textarea 的值来自子文本，属性写法在浏览器里恒为空框。`pages/rika/ui.js` 的 `h()` 因此对 `value`
  单独走 `node.value = …`（`option` 的 value 会反射回 attribute，两种元素都正确）。
  踩过一次的实际后果：`CLOUDFLARE_BLACKLIST` / `CLOUDFLARE_EXTRA_HEADERS` / `CLOUDFLARE_COOKIES`
  三个字段在页面上永远显示为空，用户照着空框编辑保存就会把原有内容清掉。
  改 `h()` 或新增 textarea 控件后，务必确认「已有值能回填」。
- **`pages/rika/` 没有随仓库的自动化回归**（它跑在受限 iframe 里）。做过一轮 jsdom 验证：
  用 jsdom 载入 `index.html`，挂一个假的 `window.AstrBotPluginPage`（`ready` / `onContext` /
  `apiGet` / `apiPost`），后端按 `webui.py` 的响应契约实现，即可覆盖首屏渲染、控件类型与回填、
  搜索、分组导航、脏值跟踪、保存 / 恢复默认 / 刷新（含确认框）、折叠、异常路径。
  改页面后建议照这个思路再跑一遍；光看代码很容易漏掉上面那类「值没写进去」的问题。
- **B站凭证会在响应头回传新 Cookie 时自动刷新**并写盘，调试时不要依赖「配置文件里就是当前值」。
- **B站 cookie 有「唯一真相」约束**：权威副本在 `BilibiliParser`（`config/bilibili_cookies.json`）。
  `BiliAccountService` 只回读与转发；`initialize()` 不得无条件覆盖解析器已有的（更新的）cookie。
  另外 `_SESSION_COOKIE_KEYS` / `FILL_ONLY_COOKIE_KEYS` 定义了响应头合并的白名单，
  新增字段前先想清楚「它是不是设备指纹」——把别的设备的指纹混进凭证会被 B站 判为风险会话。
- **B站 `ac_time_value` 只能从扫码登录响应体拿**（`data.refresh_token`），丢了就无法自动续期；
  见 5.9。
- **缓存键是内容标识、不是原始链接**：短链首次出现会多一次跳转请求（一跳优先，失败再跟完整链），之后由 `_identity_cache` 记忆；标识里若混入易变参数（token / 时间戳）会导致同一内容反复重解析，规则见 5.7。

---

## 10. 维护要求（防止本文件过时）

### 10.1 何时必须更新本文件

出现以下任一种「重要改动」时，**在同一次改动里**更新 `agent.md`：

1. 目录 / 文件新增、删除、改名、移动（→ 更新第 2 节结构树 + 第 6 节速查表）
2. 新增 / 删除平台适配器，或改动 `AdapterSpec`、`BaseParser`、`PlatformEnum`（→ 第 5.1、第 7 节、第 2 节 `_ADAPTER_MODULES` 说明）
3. `models/platforms/` 子包结构或导出别名规则变化（→ 第 5.2 节）
4. `ParseResult` / `MediaContent` 字段、`extra` 约定键变化（→ 第 5.3 节）
5. 异常类型增删或其在 `_process_url` 的表现变化（→ 第 5.4 节）
6. 配置项增删改名、默认值变化、分组变化（→ 第 5.6 节 + 第 6 节）
7. Handler / 指令增删或权限变化（→ 第 2 节、第 4 节，并更新第 8 节的 Handler 数量基线）
8. 主流程（`_process_url`、发送顺序、缓存策略、兜底逻辑）变化（→ 第 4 节）
9. 数据目录布局变化（→ 第 3 节）
10. 依赖或运行环境要求变化、新增已知坑（→ 第 8 节、第 9 节）
11. 验证基线数字变化（→ 第 8 节「期望基线」）
12. 缓存键（内容标识）规则变化：阶梯、短链声明、平台特有归一化（→ 第 5.7 节、第 4 节）
13. 缓存有效期（`CACHE_TTL_SECONDS`）或卡片换代机制变化（→ 第 5.8 节、第 4 节、第 9 节）
14. B站凭证生命周期变化：取值来源、校验频率、持有者、响应头合并白名单（→ 第 5.9 节、第 6 节、第 9 节）

### 10.2 更新方式

- 直接改对应小节，**不要只在文末追加**；顺手检查第 6 节速查表是否仍指向存在的文件。
- 在第 10.3 节顶部追加一条变更记录（日期 + 改了什么 + 影响哪些小节）。
- 自检：文中出现的每个路径都存在；命令可复制执行；第 8 节基线数字与实测一致。
- **只写与仓库内容有关的通用信息**：不要记录任何本机绝对路径、用户名、账号、令牌等隐私或环境专属内容。

### 10.3 变更日志（AI 维护，最新在上）

| 日期 | 变更 | 影响小节 |
| :--- | :--- | :--- |
| 2026-09-21 | 网页设置页全量功能验证（jsdom + 假 bridge，114 项断言）并修掉一个**数据丢失级 bug**：`pages/rika/ui.js` 的 `h()` 把 `value` 写成 `setAttribute`，而 `<textarea value="…">` 无效（textarea 的值来自子文本）→ `CLOUDFLARE_BLACKLIST` / `CLOUDFLARE_EXTRA_HEADERS` / `CLOUDFLARE_COOKIES` 在页面上恒为空框，用户照着编辑保存会清掉原内容。改为对 `value` 走 `node.value = …`（`option` 的 value 会反射回 attribute，两种元素都正确） | 9（新增两条坑）、8 |
| 2026-09-21 | 修复原生配置面板残留空分组标题：`_conf_schema.json` 中「组内条目全被标 `invisible`」的分组，把**组对象本身**也标 `invisible: true`（AstrBot 的 `AstrBotConfig.vue` 渲染组标题时不检查组内是否还有可见项）；`verify_schema_alignment()` 新增「分组可见性与组内条目一致性」校验，并同步修订 `main.py` 里 `_register_webui` 的注释；改后原生面板只剩「解析器开关」与「Cloudflare 基础设置」两张卡 | 5.6、8 |
| 2026-09-21 | 平台启停改为**一个平台一个开关**：新增 `config.PLATFORM_SWITCHES` / `platform_switch_key` / `migrate_platform_switches`，`ParserConfig.DISABLED_PLATFORMS` 改为由开关推导；旧版 `DISABLED_PLATFORMS` 逗号串在启动时迁移进开关并清空（列进 `LEGACY_ONLY_KEYS`，继续留在 schema 里供迁移读取）；`_conf_schema.json` 可见项收敛为 **8 个解析器开关 + `CLOUDFLARE_FALLBACK_ENABLED`**；配置项 44 → 51 项、分组 8 → 9 组（新增「解析器开关」） | 0、2、5.1、5.6、6、7、8 |
| 2026-09-21 | 新增插件网页设置页 `pages/rika/`（移植自 astrbot_plugin_denia_share 的界面样式：侧边分组导航 + 玻璃拟态卡片 + 明暗主题），并设置页成为配置的**唯一维护入口**：① `config.py` 新增 `CONFIG_META` 作为配置项唯一来源（派生 `CONFIG_GROUP_KEYS` / `_LEGACY_DEFAULTS` / 页面表单），新增 `config_meta_payload` / `coerce_value` / `verify_schema_alignment` 与 `current_values` / `apply_updates` / `reset_to_defaults` / `save`；② 新增 `link_parser/webui.py`（`config` 读取/保存、`config/reset`），`main.py` 新增 `_register_webui` 与 `apply_runtime_config`（渲染器/解析器/截图客户端按参数快照热重建，`self.parsers` 原地更新）；③ `_conf_schema.json` 只保留 **10 个 bool 功能开关**可见，其余 34 项标 `invisible`；④ 新增 `.astrbot-plugin/i18n/zh-CN.json`。附带修正：`FORWARD_MAX_BATCH_MB` 默认值由 `_LEGACY_DEFAULTS` 里的 12 统一为 schema 的 **30**（此前两者不一致，旧版扁平值永远迁移不进分组） | 0、2、5.6、5.10（新增）、6、8 |
| 2026-09-21 | 发布准备：版本号统一为 **v3.0.0**（`metadata.yaml` / `main.py` 的 `@register` / README 徽章）；新增 `LICENSE`（MIT）；README 补上 Twitter 反代 Worker 的独立仓库地址 | 6 |
| 2026-09-21 | 发布前整理：README 重排（新增目录导航、按 `_conf_schema.json` 的 8 组重写配置表、补全 9 个漏文档的配置项、统一版本号为 `v2.4.0`）；清理仓库内测试产物（含 cookie / 账号信息的 `scripts/dev_test_out/`） | 6、10.1 |
| 2026-09-21 | 真机冒烟发现并修复两处：① `PathTask.safe_get` 把 `IgnoreException`/`SilentException` 当控制流（DEBUG、无 traceback），此前「视频时长超限跳过下载」会刷一整段 ERROR；② B站凭证补齐 `buvid3`/`buvid4`（`_ensure_buvid`）并归一化 cookie 字典（`_credential_cookie_dict` 剔除库属性别名，cookie 串 716→642 字符） | 5.5、5.9 |
| 2026-09-21 | 新增 `scripts/dev_smoke_test.py`：不依赖 AstrBot 的独立冒烟测试（B站扫码登录 + 链接解析 + 下载清晰度探测，日志落 `scripts/dev_test_out/`）；同步 `.gitignore` | 2、8 |
| 2026-09-20 | 修复 B站 Cookie 链路：① 扫码登录改从**响应体**取凭证（`data.url` / `data.cookie_info` / `Set-Cookie` 三处合并），并把 `data.refresh_token` 存为 `ac_time_value`——此前只解析 Set-Cookie，导致自动刷新永远无法执行；② `_init_credential` 校验失败显式置 None（此前会把失效凭证交给解析器，被 B站 当未登录 → 只给 540P）；③ 新增 `VALIDATE_INTERVAL`（600s）给 `check_valid`/`check_refresh` 降频，`refresh` 包异常保护；④ cookie 收敛为「解析器唯一持有」：新增 `export_cookie()`、`update_cookie` 不再覆盖 `_bili_ck`、`initialize` 不再反向覆盖、检测前先同步；⑤ 响应头刷新改为保守合并（会话字段采纳 / buvid3·buvid4 仅补缺）；⑥ `ck2dict` 容忍无 `=` 的脏段 | 5.9（新增）、6、9、10.1 |
| 2026-09-20 | 内容缓存新增**按平台的有效期**：`BaseParser.CACHE_TTL_SECONDS`，B站设 300s（其解析结果带实时在线人数 / 直播间场次信息，永久缓存会展示过期数据）；超时重新解析并让卡片代次 +1 换代；`_result_cache` / `_render_cache` 合并为 `_content_cache: dict[key, _ContentCacheEntry]` | 3、4、5.7、5.8、6、9、10.1 |
| 2026-09-20 | 缓存键由「URL 前 64 字符」改为**内容标识**：优先取 `@handle` 命名分组，短链先跟随跳转（一跳优先、失败再跟完整链，`_identity_cache` 记忆），兜底 URL 归一化；新增 `utils/url.py`、`BaseParser.cache_identity` 及 `SHORT_LINK_KEYWORDS` / `IDENTITY_PATTERNS` / `identity_from_match` / `short_link_headers` 扩展点；微博 mid→bid、快手 photo id、Twitter status id 归一 | 2、3、4、5.7、9、10 |
| 2026-09-20 | 命中解析缓存不再向对话发送「🔄 命中缓存...」，改为写日志（`main._process_url`） | 4 |
| 2026-09-20 | 移除「本机环境备忘」整节（含本机绝对路径等隐私与环境专属信息），`<PY>` 改为通用占位说明，`PYTHONPATH` 补依赖的做法改写为通用提示；小节重新编号（10 已知约束与坑、11→10 维护要求） | 8、9、10 |
| 2026-09-20 | 结构重构：`core/` 按职责拆分为 `adapters` / `models` / `services` / `output` / `utils`；`main.py` 从 1541 行瘦身到 532 行（仅保留插件类与 Handler）；新增适配器注册表；渲染拆分为 `card_render/` 子系统；清理死代码 | 全部 |
| 2026-09-20 | 命名统一：包改名 `rika` → `link_parser`；`models/platform` → `models/platforms` 且每平台一个子包；模块改名 `web_screenshot` / `bilibili_account` / `formatting` / `replies`；日志前缀 `[rika_share]` → `[link_parser]` | 2、4、5.2、7 |
| 2026-09-20 | 新增本文件 `agent.md` | 全部 |
