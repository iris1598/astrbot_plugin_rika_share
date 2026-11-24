# 莉卡解析（astrbot_plugin_rika_share）架构与开发备忘

> 本文面向维护者与 AI，集中记录不可轻易违背的架构契约、时序依赖与历史踩坑，**重要改动后请同步更新本文与 `CHANGELOG.md`**。

---

## 1. 开发红线与核心约束

1. **Handler 归属（AstrBot 机制）**
   - AstrBot 通过 `handler.handler_module_path == 插件主模块路径` 精确归属事件处理器。所有 `@filter.*` Handler（包括由适配器注册表动态生成的平台 Handler）必须归属于 `main.py` 模块（动态生成函数须显式改写 `__module__ = __name__`），且平台 Handler 的生成循环必须在 `ParserPlugin` 类定义之前执行、末尾再由 `_attach_platform_handlers()` 挂载，以保证与声明式 Handler 的注册顺序一致。
2. **插件类与身份标识**
   - 主插件类 `ParserPlugin` 继承 `astrbot.api.star.Star`（AstrBot 4.x 通过 `Star.__init_subclass__` + `metadata.yaml` 自动识别注册，不使用已废弃的 `@register`）。
   - 插件目录名 / `metadata.yaml` 的 `name`（`astrbot_plugin_rika_share`）与 `author`（`iris1598`）不可随意变更，二者直接决定 `plugin_id` 与插件数据目录定位。
3. **日志与网络规范（审核红线）**
   - 日志器**必须且只能**从 `astrbot.api` 导入（`from astrbot.api import logger`）；**严禁**引入 Python 内置 `logging` 模块或篡改框架 logger 级别/handler，**严禁**在插件业务代码中使用 `requests` 或 `print()`。
   - 调试报告的「流程日志」由 `link_parser/services/debug_probe.py` 内的 `EventLog` 独立采集并打码输出。
4. **异常处理顺序与可观察行为**
   - `IgnoreException` / `DownloadException` 均为 `ParseException` 子类，`_process_url` 中 `except` 分支顺序必须**先子类后父类**：`SilentException` → `IgnoreException` → `DownloadException` → `ParseException`。
   - `PathTask.safe_get()` 会吞掉 `IgnoreException` / `SilentException` 与真实失败并统一返回 `None`；需区分「按设计跳过」与「真正失败」时（如链接调试探针），必须传 `on_error` 回调接回异常并判别。
5. **非 OneBot 网页分享（`link_parser/output/webpage.py`）边界**
   - 页面设计参考 qbob（AGPL-3.0），但实现已完全独立重写以符合本仓库 MIT 协议，切勿引入 copyleft 代码。
   - 聊天分享链接依赖 AstrBot `/api/file/{token}` 免鉴权文件服务（内存态 token，重启失效；链接有效期与缓存共用 `CACHE_TTL_HOURS`）；不可改走带 Dashboard 鉴权的 `register_web_api` 路由。
   - QQ 官方图文卡片（`msg_type=8`）仅对 `qq_official_full` 适配器生效，且 `callback_api_base` 须为公网可达 HTTPS。

---

## 2. 模块结构与扩展机制

```text
astrbot_plugin_rika_share/
├── main.py                      # 插件入口（ParserPlugin 与全部事件 Handler 壳子）
├── metadata.yaml                # AstrBot 插件元数据（唯一元数据来源）
├── _conf_schema.json            # AstrBot 存储契约（分组全 invisible，敏感项标 secret: true）
├── .astrbot-plugin/i18n/        # AstrBot 插件及 View 多语言文案
├── views/rika/                  # AstrBot 4.x WebUI 插件视图（设置 / 调试 / 外观）
│   └── themes/                  # 可插拔网页主题注册表与主题包
├── docs/                        # 架构备忘（本文）与预览图
├── scripts/                     # 独立辅助/回归脚本（输出统一落在 scripts/.out/）
└── link_parser/
    ├── config/                  # 配置子包：schema（唯一来源）/ nodes（分模式节点规则）/ groups（分群稀疏覆写）/ runtime（ContextVar 作用域）
    ├── adapters/                # 平台适配器（自动发现 + priority 排序 + 外部桥接 _external.py）
    ├── models/                  # ParseResult / MediaContent / PathTask / 平台响应模型
    ├── services/                # 流式下载 / 封面 / 实况合成 / B站账号 / CF 截图 / 调试探针 / card_render
    ├── output/                  # 消息链构建 / JSON与小程序卡片 / 引用提取 / 网页分享
    ├── utils/                   # 无状态工具（cache / cookie / formatting / media / url）
    ├── external.py              # 外部插件联动 SDK（ParserAPI）
    └── webui.py                 # WebUI 后端接口层（配置 / 状态 / B站扫码与检测 / 缓存 / 预览 / 调试）
```

### 四大「自动发现 + 自注册」扩展点
1. **新增平台适配器**：在 `link_parser/adapters/` 新建 `<name>.py`，继承 `BaseParser` 并调用 `register_adapter(AdapterSpec(...))`。
   - `adapters/__init__.py` 自动发现（`_` 前缀与 `base`/`registry` 除外），按 `AdapterSpec.priority` 排序。
   - **顺序敏感**：`priority` 同时决定解析器构建顺序、JSON 卡片认领顺序及 WebUI 开关排序。
2. **外部插件联动**：外部插件在自己目录放 `rikashare_bridge.py` 暴露 `register(api)`，由 `adapters/_external.py` 在 `_PLATFORM_HANDLERS` 生成前拉取注册。
   - 外部桥接不得在模块顶层自注册（防止本插件重载后注册表重建而桥接模块因 `sys.modules` 缓存跳过注册）。
   - `ModuleNotFoundError` 需判断缺失模块是否为候选根本身/前缀，避免未安装插件误刷 WARNING。
   - 与 `astrbot_plugin_multincm` 共存时，通过 `extra["suppress_text_output"]`、`extra["music_card"]`、`extra["audio_as_file"]` 协作（QQ 系支持先发解析卡片图再发 `Comp.Music` 卡片替代语音）。
3. **新增卡片样式**：在 `link_parser/services/card_render/styles/` 新建 `<name>.py`，继承 `CardStyle` 并调用 `register_style(StyleSpec(...))`。
   - 改动样式视觉后须将类属性 `version` +1，否则命中缓存旧图；无封面/超长文/无头像均须安全降级。
   - **动态人格水印兼容性**：标准样式通过 `self.footer_block(...)` 绘制页脚，系统会在底卡渲染阶段自动留出右侧安全宽并写入 `.anchor.json` 坐标，跨人格（`RENDER_PERSONA_WATERMARK`）复用同一份无水印 Base Card 仅叠印署名。若自定义样式不走 `footer_block`，请设类属性 `supports_dynamic_footer = False` 让渲染器自动回退到按署名分键整卡渲染。
4. **新增网页布局主题**：在 `views/rika/themes/` 新建主题模块调用 `registerTheme(...)`（可同时声明 `layout`、`navMode`、`light`/`dark` 变量及布局级 `css`）并在 `themes/index.js` 引入，即可自动出现在「主题与兜底」中并同步响应 AstrBot `light/dark`。

---

## 3. 数据目录、缓存与凭证备忘

- **数据目录**：`data/plugin_data/astrbot_plugin_rika_share/`（由 `StarTools.get_data_dir` 获取），包含：
  - `cache/`（媒体缓存、渲染卡片 `card_*.png`、CF 截图 `cloudflare_screenshots/`、调试日志 `debug/`）
  - `webpage/`（非 OneBot 分享页 `.html` 与封面 JPEG；复用键含 `:{rules_digest}:{seg_idx}` 以隔离不同节点编排）
  - `config/group_configs.json`、`bilibili_cookies.json`、`bili_cookie_encrypted.json`、`bili_cookie_status.json`、`.bili_cookie_key`
- **缓存两级失效**：
  - **内容标识键**（`BaseParser.cache_identity`）：优先命名分组（如 `bvid`/`aweme_id`/`tid`）→ 短链跳转 → URL 去跟踪参数归一化，确保同一内容不同短链共用缓存。
  - **实时数据 TTL**：带实时人数的平台（如 B站 `CACHE_TTL_SECONDS = 300`）超时后重新解析，卡片 `generation + 1` 换新文件名避免覆盖旧图。
  - **底卡与人格水印分离**：开启 `RENDER_PERSONA_WATERMARK`（默认关闭；关闭或命中 `default`/`[%None]`/`_chatui_default_` 时回退到可自定义的 `RENDER_BRAND_NAME`，默认 `莉卡解析`）时，同内容跨署名共享 `card_<base>_base.png` + `card_<base>_base.anchor.json`，仅做 RGBA 水印叠印生成 `card_<base>_w_<wm>.png`，纯文本头同步跟随 `brand_name` 变更。
  - **清理同步**：`initialize()` 定时清理及 `/clear_cache`（或 WebUI 一键清理）须同步清空 `_content_cache`、`_identity_cache` 与 `webpage/`（及 `_webpage_links`）。
- **B站 Cookie 单一真相**：权威副本仅由 `BilibiliParser`（`config/bilibili_cookies.json`）持有，`BiliAccountService` 只回读与写入；扫码登录（聊天 `/bili_login` 与 WebUI `POST /bili/login` + `GET /bili/status` 共用核心落盘逻辑）须从 `data.url`、`data.cookie_info.cookies`、`Set-Cookie` 三处合并 cookie 并提取 `data.refresh_token` 为 `ac_time_value`，且需补齐 `buvid3` / `buvid4`、合并响应头时仅采纳会话白名单字段；监控仅更新状态快照并在 WebUI/指令查看（已移除原先拼装无效 `default:FriendMessage:...` 私人会话的管理员失效推送 `BILI_NOTIFY_USER_ID`）。

---

## 4. 配置契约与 WebUI 受限沙箱备忘

1. **配置单一来源**：`link_parser/config/schema.py` 的 `CONFIG_META`（51 项 / 11 组，含「输出节点设置」与 `NODE_RULES`）同时驱动 WebUI 表单、类型校验（`coerce_value`）与 `_conf_schema.json` 一致性自检（`verify_schema_alignment`）。根 `.gitignore` 必须使用锚定前缀 `/cache/` 与 `/config/`，切勿屏蔽 `link_parser/config/` 源码包。
2. **分群稀疏覆写（零重解析代价）**：`link_parser/config/groups.py` 仅允许 `GROUP_OVERRIDABLE_KEYS`（18 项不触发重新解析/下载的参数）存入 `<data_dir>/config/group_configs.json`，匹配优先级为 `精确 UMO > group:<gid> > 通配符`；`config/runtime.py` 通过 `ContextVar`（`_active_config_var` / `scoped_config_for`）在消息入口 `_enter_event_scope` 与 WebUI 调试探测中激活有效配置。`main.py` 保持全量适配器常驻加载，按作用域动态检查 `DISABLED_PLATFORMS`，并用参数元组索引多 `ShareCardRenderer` 缓存（共享同一 `FontBook`），避免切换全局/分群时反复探测系统字体或污染 `_content_cache`。
3. **分模式输出节点规划与媒体合并规则**：`link_parser/config/nodes.py` 按内容形态分为 `video` / `gallery` / `dynamic` 三种模式，`output/builder.py::plan_output_segments()` 将启用的节点按顺序聚合为连续合并转发段与独立段。OneBot 下 `video.merge=True` 若 AstrBot 已配置 `callback_api_base` 则经文件服务下发 `Video.fromURL`，否则回退 `Video.fromFileSystem`；非 OneBot 平台自动保持 `video` / `audio` 独立发送以维持 `link_parser/output/webpage.py` 不变。`music_card` 强制 `supports_merge=False`（`merge=False`），启用且生效时按排序位置独立发送并自动抑制原生 `audio`。
4. **动态平台开关为什么用单键 `DISABLED_PLATFORMS`**：AstrBot 在实例化插件前用 `_conf_schema.json` 做完整性校验并剔除未知键，动态注入的 `PLATFORM_*_ENABLED` 键在下次重载时会静默丢失；因此平台列表由注册表动态下发，禁用结果按注册表顺序拼回静态逗号串 `DISABLED_PLATFORMS`。
5. **WebUI 沙箱约束**：AstrBot 插件 View 运行在 `sandbox="allow-scripts allow-forms allow-downloads"` 的受限 iframe 中（无 `allow-same-origin`），无法依赖 `localStorage` 持久化主题等偏好，须走 Bridge API 保存至后端配置（`WEBUI_THEME` / `WEBUI_COLOR_MODE`），危险操作使用行内确认替代 `window.confirm()`。分群接口包括 `GET/POST /groups` 与支持 `?scope=` 的 `/config`、`/config/reset`、`/overview`、`/debug/run`。
6. **表单控件赋值**：构造 `<textarea>` 与 `<select>` 时必须写 `node.value = ...` DOM 属性，不可用 `setAttribute("value", ...)`（否则 textarea 页面显示空框、保存时清空原配置）。
7. **官方机器人纯文本卡片与引用下载封面**：
   - `miniapp_card_handler` 与 `cloudflare_fallback_handler` 通过 `is_miniapp_card` 互斥；带 `jump_url` 的卡片优先让路给平台正则 Handler，纯标题小程序卡片才调用 `search_video_by_title`（带标题去前缀变体与严格标题前缀匹配）。
   - 「下载封面」使用 `@filter.regex` 而非 `@filter.command`（引用别人消息不算唤醒），且**只从被引用消息取链接**（优先框架 `quoted_message`、回退 `Reply` 组件），不猜测会话历史。

---

## 5. 验证命令

```bash
# 1) 代码规范与静态检查（应在插件根目录或 AstrBot venv 下运行）
python -m ruff check --no-cache --exclude __pycache__ .
python -m compileall -q .

# 2) 审核规范扫描（两条均应无任何生产代码命中）
#    - 禁止内置 logging / requests / 运行期 print

# 3) 卡片渲染、文档预览图与颜文字回退回归（临时输出落在 scripts/.out/）
python scripts/preview_layouts.py
python scripts/preview_layouts.py --export-docs
python scripts/kaomoji_render_test.py

# 4) 独立链接与B站扫码冒烟（输出落在 scripts/.out/smoke/）
python scripts/dev_smoke_test.py --no-download <url>
```
