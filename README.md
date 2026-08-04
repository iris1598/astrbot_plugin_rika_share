# 莉卡解析

AstrBot 链接分享自动解析插件。移植自 [nonebot-plugin-parser](https://github.com/fllesser/nonebot-plugin-parser)。

## 支持平台

| 平台 | 解析内容 | 下载 |
|------|---------|------|
| 哔哩哔哩 | 视频/动态/直播/专栏/收藏夹 | 视频（需 Cookie） |
| 抖音 | 视频/图文 | 视频/图片 |
| 快手 | 视频/图文 | 视频/图片 |
| 微博 | 动态/文章/视频 | 视频/图片 |
| 小红书 | 图文/视频 | 图片/视频（需 Cookie） |
| Twitter/X | 推文/媒体 | 视频/图片 |
| AcFun | 视频 | 视频 |
| NGA | 帖子 | — |

## 输出格式

默认开启**精美解析卡片渲染**：解析结果会渲染成一张分享卡片图片**直接发送**
（不经过合并转发，任何平台一致）。有封面/图集时顶部为**全宽横幅**
（标题白色浮层 + 悬浮平台徽标），无图时使用纯文本卡片头部，下方依次为
作者、正文简介、统计徽章、图集网格与链接页脚。

渲染模式下：

- **图文 / 图集帖**：卡片发送后保留文字部分与图集图片，按平台规则发送
  （OneBot 走合并转发，其他平台直接发送）；
- **视频帖**：卡片已承载全部信息，不再重复发送文字摘要，视频文件仍单独发送；
- 渲染失败时自动回退为文本输出。

关闭渲染后的文本输出格式（合并转发）：

```
（合并转发）
  消息1：莉卡解析 | 平台 - 类型
  消息2：标题 / 链接 / 封面
  消息3：时长 / 统计 / 简介
（单独发送）视频/图片文件
```

各平台格式可自定义适配。

## 解析图片渲染

使用 Pillow 将解析结果渲染为卡片图片，无需浏览器。卡片包含：

- 平台徽标 + 内容类型 + 发布时间
- 顶部横幅：视频封面 / 图集首图全宽展示，标题浮层 + 视频播放按钮
- 圆形作者头像、昵称与签名
- 正文简介
- 数据统计徽章（点赞 / 投币 / 收藏 / 播放等）
- 图集网格（超过 6 张显示 +N）
- 转发内容引用卡片、底部链接与「莉卡解析」水印

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `RENDER_ENABLED` | bool | true | 启用解析图片渲染，失败自动回退文本 |
| `RENDER_THEME` | string | `dark` | 卡片主题：`dark` / `light` |
| `RENDER_WIDTH` | int | 800 | 卡片宽度（520-1080px） |
| `RENDER_FONT_PATH` | string | — | 自定义字体文件/目录，留空自动探测系统中文字体 |

Linux 服务器建议安装中文字体（如 `fonts-noto-cjk`），否则卡片文字会显示为方块；
也可以在 `RENDER_FONT_PATH` 中直接指定字体文件。

## 安装

1. 将 `astrbot_plugin_rika_share` 放入 `data/plugins/` 目录
2. 安装依赖：

```bash
pip install -r requirements.txt
```

3. 重启 AstrBot，在 WebUI 插件管理中启用

## 配置

WebUI 设置页按「平台 / B站 / 缓存 / 解析图片渲染 / Cloudflare 基础 / Cloudflare 截图 / 调试」分组展示，以下为全部配置项：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `BILI_CK` | string | — | B站 Cookie (SESSDATA)，获取 AI 总结和高清下载 |
| `XHS_CK` | string | — | 小红书 Cookie，获取图片/视频下载 |
| `VIDEO_DURATION_MAXIMUM` | int | 480 | 视频最大时长（秒），超时不会下载 |
| `DISABLED_PLATFORMS` | string | — | 禁用的平台（逗号分隔，如 `acfun,nga`） |

## Cloudflare 网页截图

链接不匹配任何已适配平台时，可自动用 Cloudflare Browser Rendering 渲染网页并截图发送。

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `CLOUDFLARE_FALLBACK_ENABLED` | bool | false | 启用网页截图兜底 |
| `CLOUDFLARE_ACCOUNT_ID` | string | — | Cloudflare 账号 ID（需开通 Browser Rendering） |
| `CLOUDFLARE_API_TOKEN` | string | — | API Token（需 Browser Rendering - Edit 权限） |
| `CLOUDFLARE_TIMEOUT` | int | 60 | 截图 API 超时（秒） |
| `CLOUDFLARE_VIEWPORT_WIDTH` / `HEIGHT` | int | 1280 / 720 | 渲染视窗尺寸 |
| `CLOUDFLARE_WAIT_UNTIL` | string | `networkidle0` | 页面加载策略：`load` / `domcontentloaded` / `networkidle0` / `networkidle2` |
| `CLOUDFLARE_GOTO_TIMEOUT` | int | 45000 | 页面导航超时（毫秒） |
| `CLOUDFLARE_FULL_PAGE` | bool | false | 整页截图（含滚动区域） |
| `CLOUDFLARE_DEVICE_SCALE_FACTOR` | float | 1 | 截图清晰度，增大可避免大视窗截图模糊（1-3） |
| `CLOUDFLARE_SCREENSHOT_TYPE` | string | `png` | 截图格式：`png` / `jpeg` |
| `CLOUDFLARE_SCREENSHOT_QUALITY` | int | 0 | JPEG 质量 0-100（png 下自动忽略） |
| `CLOUDFLARE_OMIT_BACKGROUND` | bool | false | 透明背景（仅 png 有效） |
| `CLOUDFLARE_SELECTOR` | string | — | CSS 选择器，只截取指定元素 |
| `CLOUDFLARE_WAIT_FOR_SELECTOR` | string | — | 等待该元素出现后再截图（JS 动态页面） |
| `CLOUDFLARE_USER_AGENT` | string | — | 自定义 User-Agent |
| `CLOUDFLARE_EXTRA_HEADERS` | text(JSON) | — | 附加请求头，如 `{"Authorization":"Bearer xxx"}` |
| `CLOUDFLARE_COOKIES` | text(JSON) | — | 附加 Cookie 数组，如 `[{"name":"session","value":"xxx","domain":"example.com","path":"/"}]` |
| `CLOUDFLARE_CACHE_TTL` | int | 0 | 截图缓存秒数，0 表示不缓存 |
| `CLOUDFLARE_BLACKLIST` | list | — | 截图黑名单：域名（`example.com` 含子域名）、通配符（`*.example.com`）、路径前缀（`https://example.com/login`）或不含点的关键词 |

## 获取 Cookie

### B站 SESSDATA
1. 浏览器登录 bilibili.com
2. F12 → 控制台 → 输入 `document.cookie`
3. 找到 `SESSDATA=xxx;`，复制 `xxx` 填入配置

### 小红书 Cookie
1. 浏览器登录 xiaohongshu.com
2. F12 → 控制台 → 输入 `document.cookie`
3. 复制整个 Cookie 字符串填入配置

## 文件结构

```
astrbot_plugin_rika_share/
├── main.py              # 插件入口
├── metadata.yaml        # 插件元数据
├── _conf_schema.json    # 配置定义
├── requirements.txt     # 依赖
├── core/
│   ├── config.py        # 配置管理
│   ├── constants.py     # 常量和枚举
│   ├── exception.py     # 异常类
│   ├── utils.py         # 工具函数
│   ├── utils_parser.py  # 解析工具
│   ├── task.py          # 异步路径包装
│   ├── data.py          # 数据模型
│   ├── cookie.py        # Cookie 工具
│   ├── download.py      # 下载器
│   ├── render.py        # 精美解析卡片渲染（Pillow）
│   ├── base_parser.py   # 解析器基类
│   ├── parsers/         # 各平台解析器
│   │   ├── bilibili.py
│   │   ├── douyin.py
│   │   ├── kuaishou.py
│   │   ├── weibo.py
│   │   ├── xiaohongshu.py
│   │   ├── twitter.py
│   │   ├── nga.py
│   │   └── acfun.py
│   └── bili_models/     # B站数据模型
│       ├── video.py
│       ├── dynamic.py
│       ├── opus.py
│       ├── live.py
│       └── favlist.py
```

## 致谢

- [nonebot-plugin-parser](https://github.com/fllesser/nonebot-plugin-parser) — 原版插件
