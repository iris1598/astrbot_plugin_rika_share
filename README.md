# 莉卡解析 · astrbot_plugin_rika_share

![AstrBot Plugin](https://img.shields.io/badge/AstrBot-Plugin-blue?style=flat-square)
![Version](https://img.shields.io/badge/Version-v3.0.0-brightgreen?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square)
![Render](https://img.shields.io/badge/Render-Pillow-orange?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)

**莉卡解析** 是为 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 打造的链接自动解析与媒体下载插件。
自动识别聊天中的链接与 JSON 分享卡片，提取标题、正文、作者、数据统计、图集与无水印视频，
并可渲染为精美的分享卡片图片单独发送。

移植自 [nonebot-plugin-parser](https://github.com/fllesser/nonebot-plugin-parser)，并针对 AstrBot 架构做了分层重构与功能增强。

---

## 📖 目录

| | |
| :--- | :--- |
| [✨ 特性速览](#-特性速览) | [🌐 支持平台](#-支持平台) |
| [📦 安装与部署](#-安装与部署) | [🛠️ 指令说明](#️-指令说明) |
| [⚙️ 配置说明](#️-配置说明) | [🎨 解析卡片渲染](#-解析卡片渲染) |
| [🔐 Cookie 获取指南](#-cookie-获取指南) | [📁 项目结构](#-项目结构) |
| [🧩 扩展：新增一个平台](#-扩展新增一个平台) | [🧑‍💻 开发与验证](#-开发与验证) |
| [🙏 致谢](#-致谢) | [📄 开源许可](#-开源许可) |

---

## ✨ 特性速览

### 🚀 多平台自动解析

自动识别文本链接与 JSON 分享卡片，一次提取标题、正文、作者、数据统计、图集与无水印视频。
短链会自动跟随跳转，因此 `b23.tv` / `v.douyin.com` / `xhslink.com` 等分享链接可直接使用。

### 🔑 B站扫码登录与 Cookie 自动化

- **无需抓包**：聊天框直接发送 `/bili_login` 生成二维码，扫码确认即完成登录。
- **加密持久化**：Cookie 使用 Fernet 加密落盘，重启不丢失。
- **凭据自动续期**：登录时一并保存 `refresh_token`，凭证临近过期时自动刷新。
- **健康度监控**：后台定时检测 Cookie 有效性，失效 / 恢复时通知指定管理员。
- **无缝生效**：登录成功后立即注入解析引擎，无需重载插件或修改配置。

### 🎨 Pillow 纯 Headless 卡片渲染

不依赖浏览器，毫秒级输出。提供 4 种卡片布局与深 / 浅两套主题，支持全尺寸封面、
品牌光晕与毛玻璃徽章；渲染失败时自动回退为文本输出。

### ⚡ 跨平台发送适配

- **OneBot v11**：自动构建节点合并转发（`Nodes`），避免消息刷屏，并按节点数 / 图片体积自动拆批。
- **QQ Official / Telegram 等**：自动拆分消息并采用主动发送，避免被「回复时引用」格式干扰。

### 🛰️ Twitter/X 反代

推文解析接口与图片、视频、封面、头像均可改走自建反代，解决 X 在国内无法直连的问题。

> 反代 Worker 已独立为单独项目：[**iris1598/cloudflare-worker**](https://github.com/iris1598/cloudflare-worker)。
> 部署后把地址填入 `TWITTER_MEDIA_PROXY_BASE` 即可；未配置或反代不可用时会自动回退直连。

### 🌐 Cloudflare 网页截图兜底

未匹配到任何已适配平台的普通网页链接，可调用 Cloudflare Browser Rendering API 渲染网页截图发送。
支持自定义视窗、清晰度倍率、CSS 元素截取、Cookie / Header 注入与黑名单过滤。

### 🐞 链接调试

插件页面里还有一个「链接调试」视图：粘一条链接进去，插件会把解析主流程
（识别平台 → 缓存标识 → 解析接口 → 媒体下载 → 卡片渲染 → 输出构建 → Cloudflare 兜底判断）
逐步跑一遍，每步给出状态、耗时与失败原因，并把过程记成**可直接贴出的报告**
（含逐项失败原因的堆栈；Cookie / Token 自动打码）。

排查「这条链接为什么不解析」「视频为什么发不出去」时，看 `[失败]` 的那一步即可；
`[跳过]` 是**按设计不做**（如视频时长超过上限、媒体本身为空），不是故障——
媒体那一行会写清是哪个文件、为什么跳过，例如：
`#1 视频: [跳过] 视频时长(12:34)超过限制(08:00)，跳过下载`。

### 🖥️ 网页设置页

插件自带一个 Dashboard 页面（插件详情页里打开），把 51 项配置按 9 个分组收在一处：

- 左侧分组导航 + 顶部搜索，长配置表不再靠滚动找；
- Cookie / Token 默认遮罩，可一键显示核对；
- 底部保存条实时显示「已修改 N 项」，支持放弃更改、恢复默认与批量保存；
- 保存后即时生效，卡片渲染、解析器开关、截图凭据都会自动热更新。

全部 44 项配置都在页面里维护，原生插件配置面板不再展示配置项；
页面顶部的「解析器开关」按适配器注册表动态生成，**新增平台会自动多出一个开关**，
不用改配置也不用改代码。

---

## 🌐 支持平台

| 平台 | 覆盖类型 | 可下载内容 | 备注 |
| :--- | :--- | :--- | :--- |
| **哔哩哔哩** | 视频 / 动态 / 图文(Opus) / 直播 / 专栏 / 收藏夹 | 高清视频、封面、图集 | 支持扫码登录、Cookie 监控与自动续期 |
| **抖音** | 视频 / 图文动态 | 无水印视频、高清图集 | 支持短链解析与实况照片重建 |
| **快手** | 视频 / 图文 | 无水印视频、高清图片 | 支持短链与网页链接 |
| **微博** | 动态 / 文章 / 视频 | 原图图集、无水印视频 | 支持多图网格与转发引用结构 |
| **小红书** | 图文笔记 / 视频笔记 | 原图无水印图集、视频 | 支持 `XHS_CK` 鉴权 |
| **Twitter / X** | 推文 / 媒体 | 高清图片、视频 | 解析接口与媒体均可走自建反代 |
| **AcFun** | 视频 | 视频文件 | 基础视频解析 |
| **NGA** | 帖子内容 / 主题 | 正文与图集 | 论坛内容快速展示 |
| **通用网页** | 任意 HTTP/HTTPS 页面 | 网页高清截图 | 需开通 Cloudflare Browser Rendering |

---

## 📦 安装与部署

1. **放入插件目录**

   将 `astrbot_plugin_rika_share` 文件夹放进 AstrBot 的 `data/plugins/` 目录。

2. **安装依赖**

   ```bash
   pip install -r requirements.txt
   ```

   主要依赖：`httpx`、`aiohttp`、`bilibili-api-python`、`msgspec`、`curl-cffi`、
   `beautifulsoup4`、`qrcode[pil]`、`cryptography`、`Pillow`、`fonttools`、`aiofiles`。

3. **启用插件**

   重启 AstrBot，在管理面板 WebUI 中启用「莉卡解析」。

> 💡 **Linux 字体提示**：卡片渲染需要中文字体，建议 `apt install fonts-noto-cjk fonts-noto-core`，
> 或在 `RENDER_FONT_PATH` 中指定 `.ttf/.otf` 路径，否则文字会显示为方块。

---

## 🛠️ 指令说明

| 指令 | 权限 | 功能 |
| :--- | :--- | :--- |
| `/bili_login` | **ADMIN** | 启动 B站扫码登录：发送二维码图片，扫码确认后自动加密保存并启用 Cookie |
| `/bili_check` | ADMIN | 手动检测当前 Cookie 有效性，显示昵称、UID 与会员状态 |
| `/bili_status` | ADMIN | 查看 Cookie 状态与后台监控任务的运行情况 |
| `/clear_cache`<br>`/清理缓存` | **ADMIN** | 清空下载文件、渲染图片、网页截图等缓存，并同步清空内存缓存 |

---

## ⚙️ 配置说明

配置按逻辑划分为 **8 个分组**，共 44 项，**全部在插件网页设置页里维护**：
WebUI 侧边栏「插件」→ 莉卡解析 → 插件详情页 → 打开页面。
页面支持搜索、分组折叠、Cookie 遮罩、批量保存与恢复默认，
另外带一个「链接调试」视图用于排查解析问题。

> AstrBot 原生的插件配置面板**不再展示任何配置项**（`_conf_schema.json` 里全部标了
> `invisible`）。它只作为配置的存储契约存在——AstrBot 加载插件时会按 schema 保留这些键，
> 页面保存的值才能落盘。
>
> 顶部的「解析器开关」由适配器注册表实时生成：**新写一个平台适配器，页面上就自动多出一个
> 开关**，不需要改任何配置或代码。

在网页设置页里保存后立即生效：卡片渲染、解析器开关、Cloudflare 截图凭据会自动热更新，
**不需要重载插件**。原生面板里改开关后需要按 AstrBot 的常规流程重载插件。

### 解析器开关（不在配置分组内）

在网页设置页顶部的「解析器开关」里，一个平台一块，点一下即开关。
**平台清单由适配器注册表实时生成**，支持哪些平台就列出哪些，新增平台会自动出现。

| 平台 | 说明 |
| :--- | :--- |
| 哔哩哔哩 / 抖音 / 快手 / 微博 / 小红书 / 小蓝鸟 / NGA / 猴山 | 关闭后不再解析对应平台的链接，其余平台不受影响 |

关闭的平台以 `DISABLED_PLATFORMS`（逗号分隔的平台名）存在插件配置里；
旧版本手写 `DISABLED_PLATFORMS=acfun,nga` 的写法依然有效，两者是同一个键。

### 1. 平台设置

| 配置项 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `VIDEO_DURATION_MAXIMUM` | int | `480` | 视频 / 音频最大时长（秒），超出则不下载媒体文件 |
| `DOUYIN_LIVE_PHOTO_ENABLED` | bool | `true` | 将抖音实况照片与普通动图重建为单文件动态照片 |
| `XHS_CK` | string | `""` | 小红书 Cookie（可选，填入后可解析高清视频与图集） |
| `FORWARD_MAX_NODES` | int | `10` | 单条合并转发的最大节点数（超出则拆成多条） |
| `FORWARD_MAX_BATCH_MB` | int | `30` | 单条合并转发的图片体积上限（MB），调小更省内存但消息更多 |

### 2. Twitter 设置

| 配置项 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `TWITTER_MEDIA_PROXY_ENABLED` | bool | `false` | 媒体与解析接口是否改走自定义反代 |
| `TWITTER_MEDIA_PROXY_BASE` | string | `""` | 自建反代根地址，如 `https://xxx.workers.dev`（结尾不要带斜杠）<br>Worker 见 [cloudflare-worker](https://github.com/iris1598/cloudflare-worker) |

### 3. B站设置

| 配置项 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `BILI_CK` | string | `""` | B站 Cookie（SESSDATA）。*建议直接用 `/bili_login` 扫码登录* |
| `BILI_QUALITY` | string | `"1080P"` | 下载清晰度：`360P` / `480P` / `720P` / `1080P` / `1080P+` / `4K` / `8K`（更高档位需账号权限） |
| `BILI_COOKIE_MONITOR_ENABLED` | bool | `true` | 是否启用 Cookie 定时监控 |
| `BILI_COOKIE_CHECK_INTERVAL` | int | `3600` | 检测间隔（秒，最小 60） |
| `BILI_NOTIFY_USER_ID` | string | `""` | Cookie 失效 / 恢复时接收通知的 QQ 号或 UserID（留空仅记日志） |

### 4. 缓存设置

| 配置项 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `CACHE_TTL_HOURS` | int | `24` | 缓存文件过期时间（小时），设为 `0` 禁用自动清理 |
| `CACHE_CLEANUP_INTERVAL_MINUTES` | int | `60` | 清理检查间隔（分钟） |

### 5. 解析图片渲染

| 配置项 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `RENDER_ENABLED` | bool | `true` | 是否启用卡片渲染（失败自动回退文本） |
| `RENDER_THEME` | string | `"dark"` | 主题：`dark` / `light` |
| `RENDER_LAYOUT` | string | `"standard"` | 布局：`standard` / `magazine` / `immersive` / `feed` |
| `RENDER_WIDTH` | int | `800` | 卡片宽度（px，范围 520–1080） |
| `RENDER_COVER_FULL_SIZE` | bool | `false` | 封面按原始宽高比完整展示，不做中心裁剪 |
| `RENDER_FONT_PATH` | string | `""` | 自定义字体文件或目录（`.ttf/.ttc/.otf`），留空自动探测系统字体 |

### 6. Cloudflare 基础设置

| 配置项 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `CLOUDFLARE_FALLBACK_ENABLED` | bool | `false` | 启用通用链接截图兜底（未匹配已知适配器时触发） |
| `CLOUDFLARE_ACCOUNT_ID` | string | `""` | Cloudflare 账号 ID（需开通 Browser Rendering） |
| `CLOUDFLARE_API_TOKEN` | string | `""` | API Token（需具备 Browser Rendering - Edit 权限） |
| `CLOUDFLARE_TIMEOUT` | int | `60` | 截图 API 请求超时（秒） |
| `CLOUDFLARE_CACHE_TTL` | int | `0` | 截图缓存时长（秒），`0` 表示不缓存、每次重新渲染 |
| `CLOUDFLARE_BLACKLIST` | list | `[]` | 截图黑名单，支持完整域名、`*.example.com` 通配符、路径前缀或无点关键词 |

### 7. Cloudflare 截图设置

| 配置项 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `CLOUDFLARE_VIEWPORT_WIDTH` | int | `1280` | 浏览器视窗宽度（px） |
| `CLOUDFLARE_VIEWPORT_HEIGHT` | int | `720` | 浏览器视窗高度（px） |
| `CLOUDFLARE_WAIT_UNTIL` | string | `"networkidle0"` | 加载等待策略：`load` / `domcontentloaded` / `networkidle0` / `networkidle2` |
| `CLOUDFLARE_GOTO_TIMEOUT` | int | `45000` | 页面导航超时（毫秒） |
| `CLOUDFLARE_FULL_PAGE` | bool | `false` | 截取完整长图（含滚动区域） |
| `CLOUDFLARE_DEVICE_SCALE_FACTOR` | float | `1.0` | 清晰度倍率，建议 1–3（大视窗下可消除模糊） |
| `CLOUDFLARE_SCREENSHOT_TYPE` | string | `"png"` | 截图格式：`png` / `jpeg` |
| `CLOUDFLARE_SCREENSHOT_QUALITY` | int | `0` | 截图质量（仅 `jpeg` 有效，0–100，`0` 为默认） |
| `CLOUDFLARE_OMIT_BACKGROUND` | bool | `false` | 隐藏默认白底，适合 `png` 透明图 |
| `CLOUDFLARE_SELECTOR` | string | `""` | 只截取指定 CSS 选择器区域，留空截整页 |
| `CLOUDFLARE_WAIT_FOR_SELECTOR` | string | `""` | 等待该选择器出现后再截图（适合 SPA） |
| `CLOUDFLARE_WAIT_FOR_TIMEOUT` | int | `0` | 等待元素超时（毫秒），`0` 为默认 |
| `CLOUDFLARE_USER_AGENT` | string | `""` | 自定义 User-Agent，留空使用默认 |
| `CLOUDFLARE_EXTRA_HEADERS` | text | `""` | 加载页面时附加的 HTTP 头（JSON），如 `{"Authorization":"..."}` |
| `CLOUDFLARE_COOKIES` | text | `""` | 页面附加 Cookie（JSON 数组），如 `[{"name":"session","value":"..."}]` |

### 8. 调试设置

| 配置项 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `DEBUG_LOG_ENABLED` | bool | `true` | 是否打印详细错误堆栈 |
| `SEND_ERROR_MESSAGES` | bool | `false` | 出错时是否向对话发送提示（关闭则仅记日志） |

---

## 🎨 解析卡片渲染

开启 `RENDER_ENABLED` 后，解析结果会渲染为现代视觉风格的分享卡片并单独发送。

### 布局总览

![渲染样式总览](docs/previews/overview-layouts.png)

| 布局 (`RENDER_LAYOUT`) | 特点与适用场景 |
| :--- | :--- |
| **`standard`** 标准横幅 *(默认)* | 顶部全宽封面 + 纵向信息流，大气平衡，适合绝大多数视频与动态 |
| **`magazine`** 双栏杂志 | 封面左置、标题作者右置，适合长文本与文章 |
| **`immersive`** 沉浸全屏 | 封面高斯模糊铺满整卡，文字浮于渐变遮罩上（无图时自动回退 `standard`） |
| **`feed`** 社交动态 | 头像与作者信息行置顶，媒体内嵌为圆角多图，原生 App 社交流风格 |

### 主题

支持 **深色 (`dark`)** 与 **浅色 (`light`)** 两套配色：

![浅色主题示例](docs/previews/layout-standard-light.png)

### 字体与颜文字

> 颜文字（如 `᳐⦁⩊੭ᯠᯄᐠ⸝⌯`）在主字体缺字形时会自动回退到系统符号字体
> （Windows：Segoe UI Symbol / Segoe UI / Leelawadee UI / Gadugi / SansSerifCollection 等；
> Linux：Noto Sans Symbols / Math / Sundanese 等），无需手动配置。
> 预设链未覆盖的字符还会通过 `fc-list :charset=XXX` 动态查找系统字体兜底。
> Linux 建议一并安装 `fonts-noto-cjk` 与 `fonts-noto-core`。

---

## 🔐 Cookie 获取指南

### B站：扫码登录（推荐）

1. 用管理员账号向机器人发送 `/bili_login`。
2. 机器人返回一张登录二维码图片。
3. 打开手机 **B站 App** 扫描二维码，并点击 **确认登录**。
4. 机器人提示登录成功，Cookie 会**加密保存并立即生效**，无需重启。

登录时会一并保存续期凭据（`refresh_token`），凭证临近过期可自动刷新，
无需反复重新扫码。

### 其他平台

在插件配置中填入对应 Cookie 即可（`XHS_CK` 等），格式为浏览器中复制的
`name=value; name=value` 字符串。

---

## 📁 项目结构

> 面向贡献者与 AI 的架构契约、常见改动位置与验证清单，见 [`agent.md`](agent.md)。

```text
astrbot_plugin_rika_share/
├── main.py                       # 插件入口：插件类 + 全部事件 Handler（AstrBot 要求写在此处）
├── metadata.yaml                 # 插件元数据定义
├── _conf_schema.json             # 配置存储契约（条目全部 invisible，原生面板不展示）
├── requirements.txt              # Python 依赖清单
├── README.md                     # 本文件
├── LICENSE                       # MIT 许可证
├── agent.md                      # AI 开发指南（结构契约 / 改哪里 / 验证清单 / 维护要求）
├── CHANGELOG.md                  # 变更日志（最新在上）
├── .astrbot-plugin/i18n/         # 插件页面标题 / 描述的国际化文案
├── pages/rika/                   # 插件网页设置页（设置 + 链接调试两个视图）
│   ├── index.html                #   页面骨架：侧边导航 + 内容区
│   ├── style.css                 #   设计系统：CSS 变量 + 明暗两套主题
│   ├── ui.js                     #   零依赖 DOM / 表单小工具
│   ├── app.js                    #   框架层：bridge 就绪 → 建导航 → 切换视图
│   └── views/                    #   settings.js（设置）· debug.js（链接调试）
├── docs/previews/                # 卡片渲染与布局预览图
├── scripts/                      # 开发辅助脚本
│   ├── dev_smoke_test.py         #   独立冒烟测试：扫码登录 + 链接解析（自带 astrbot 桩）
│   ├── preview_layouts.py        #   卡片布局回归（4 布局 × 2 主题 × 全尺寸）
│   ├── kaomoji_render_test.py    #   颜文字字体回退回归
│   └── font_coverage_probe.py    #   字体覆盖探测
└── link_parser/                  # 插件实现（按职责分层）
    ├── adapters/                 # 平台解析适配器（每个平台一个模块，自注册）
    │   ├── base.py               #   BaseParser 基类 + @handle 装饰器
    │   ├── registry.py           #   适配器注册表（URL 触发正则 / 构建方式）
    │   └── bilibili.py · douyin.py · kuaishou.py · weibo.py
    │       xiaohongshu.py · twitter.py · nga.py · acfun.py
    ├── models/                   # 数据类型
    │   ├── content.py            #   媒体内容（图片 / 视频 / 音频）
    │   ├── result.py             #   ParseResult / Platform / Author
    │   ├── task.py               #   惰性下载路径包装 PathTask
    │   └── platforms/            #   各平台接口返回结构（一个平台一个子包）
    │       ├── acfun/            #     video_info.py
    │       ├── bilibili/         #     author.py · video_info.py · dynamic.py
    │       │                     #     opus.py · live_room.py · favorite_list.py
    │       ├── douyin/           #     aweme.py
    │       ├── kuaishou/         #     init_state.py
    │       ├── weibo/            #     status.py · video_show.py · article.py
    │       └── xiaohongshu/      #     note.py · explore_page.py · discovery_page.py
    ├── services/                 # 有状态服务（一个服务一个模块）
    │   ├── downloader.py         #   异步流式媒体下载
    │   ├── card_render/          #   卡片渲染子系统（theme / fonts / text / renderer）
    │   ├── debug_probe.py        #   链接调试探针（逐步跑主流程 + 打码出报告）
    │   ├── web_screenshot.py     #   Cloudflare Browser Rendering 网页截图
    │   ├── live_photo.py         #   实况照片（主图 + 短视频）单文件合成
    │   └── bilibili_account.py   #   B站扫码登录 / Cookie 监控与自动应用
    ├── output/                   # 输出构建
    │   ├── builder.py            #   解析结果 → 合并转发 / 纯文本消息链
    │   ├── json_card.py          #   JSON 分享卡片识别与链接提取
    │   └── replies.py            #   统一的回复构造（错误提示等）
    ├── utils/                    # 无状态工具（cache / media / formatting / cookie / url）
    ├── config.py                 # CONFIG_META（配置项唯一来源）+ 配置读写 / 迁移
    ├── constants.py              # 请求头、超时、平台枚举、通用 URL 正则
    ├── webui.py                  # 插件页面的后端接口（配置读写 + 链接调试）
    └── exceptions.py             # 异常体系
```

**命名与归档约定**

- 模块名一律自描述：`web_screenshot.py`（网页截图）、`bilibili_account.py`（B站账号）、
  `formatting.py`（文本格式化）、`replies.py`（回复构造），不使用缩写或代号。
- 一个平台 = `adapters/<平台>.py` + `models/platforms/<平台>/`，两侧一一对应。
- 多模块子系统才用子包（`models/platforms/<平台>/`、`services/card_render/`），
  单模块一律保持单文件，避免「同一层里既有文件夹又有文件」的歧义。
- 子包的 `__init__.py` 显式导出对外接口，调用方只从包根导入，
  这样调整子包内部拆分不会影响调用方。

---

## 🧩 扩展：新增一个平台

适配器层已做自注册，新增平台**无需改动入口的事件注册逻辑**。

**1.** 在 `link_parser/adapters/` 下新建 `<平台名>.py`：

```python
import re
from typing import ClassVar

from ..constants import PlatformEnum
from ..models import Platform
from .base import BaseParser, handle
from .registry import AdapterSpec, register_adapter


class FooParser(BaseParser):
    platform: ClassVar[Platform] = Platform(name=PlatformEnum.FOO, display_name="Foo")

    @handle("foo.com", r"foo\.com/video/(?P<vid>\d+)")
    async def _parse(self, searched: re.Match[str]):
        return self.result(title="...", url="...", extra={"content_type": "视频"})


ADAPTER = register_adapter(
    AdapterSpec(
        name=PlatformEnum.FOO.value,
        url_pattern=re.compile(r"foo\.com"),
        parser_cls=FooParser,
        description="视频",
    )
)
```

**2.** 在 `link_parser/constants.py` 的 `PlatformEnum` 中加入平台标识。

**3.** 在 `link_parser/adapters/__init__.py` 的 `_ADAPTER_MODULES` 中 import 该模块。

若平台返回结构较复杂，在 `link_parser/models/platforms/<平台名>/` 下新建子包：
模块名按接口命名（如 `video_info.py`、`status.py`），并在子包 `__init__.py` 中导出
响应结构与 `decoder`（多个模块都有 `decoder` 时按语义加前缀，如 `status_decoder`），
适配器只从子包根导入（`from ..models.platforms.<平台> import ...`）。

其余部分自动生效：入口的 URL 过滤器正则、解析器实例化、`DISABLED_PLATFORMS` 开关、
渲染配色（`link_parser/services/card_render/theme.py` 的 `PLATFORM_COLORS`，可选）。

若该平台的解析结果带**会随时间变化的实时数据**（如在线人数、直播场次信息），
在适配器上声明 `CACHE_TTL_SECONDS`（秒），让结果缓存按时过期，避免长期展示过期数据。

---

## 🧑‍💻 开发与验证

`scripts/` 下的脚本都自带 `astrbot` 桩，可脱离 AstrBot 运行环境直接执行。

```bash
# 静态检查（未定义名 / 未使用导入）
python -m ruff check --select F,E9 --no-cache --exclude __pycache__ .

# 卡片布局回归：4 布局 × 2 主题 × 全尺寸 = 96 张，末行应为「共渲染 96 张，全部成功」
python scripts/preview_layouts.py

# 颜文字字体回退回归
python scripts/kaomoji_render_test.py

# 独立功能冒烟：扫码登录 + 链接解析（日志落在 scripts/dev_test_out/）
python scripts/dev_smoke_test.py --login https://www.bilibili.com/video/BV1xx411c7mD
```

`dev_smoke_test.py` 使用**独立的数据目录**（`scripts/dev_test_out/`，已 gitignore），
不会影响 AstrBot 里的真实登录态；输出中的「清晰度探测」段落会直接列出
B站 给出的可用清晰度，是判断登录态是否生效最直接的证据。

---

## 🙏 致谢

- [nonebot-plugin-parser](https://github.com/fllesser/nonebot-plugin-parser) —— 原 NoneBot2 插件的优秀思路与解析逻辑。
- [bilibili-api-python](https://github.com/Nemo2011/bilibili-api) —— B站接口封装与扫码登录实现。
- [AstrBot](https://github.com/AstrBotDevs/AstrBot) —— 强大的多平台机器人框架。

---

## 📄 开源许可

本项目遵循 MIT 许可证。
