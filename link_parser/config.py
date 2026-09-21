"""配置管理模块

配置项的**唯一来源**是 :data:`CONFIG_META`（分组 + 键 + 类型 + 默认值 + 文案）：

- 插件网页设置页（``pages/rika``）直接按它渲染表单；
- ``_conf_schema.json`` 是同一次定义的**存储契约**——AstrBot 加载插件配置时会剔除
  schema 之外的键，两者不一致会让用户保存的值在重载时静默丢失，
  因此启动时用 :func:`verify_schema_alignment` 自检；
- 原生配置面板只保留**功能开关**（bool），其余条目在 schema 里标 ``invisible``，
  维护入口统一收敛到插件页面。

为保证旧版本已保存的扁平配置不丢失，读取时优先使用分组值，
分组值为默认值时回退到扁平旧值；插件启动时会将旧值迁移到分组中。
"""

import re
from pathlib import Path
from typing import Any

_config = None

# 解析器开关：平台名 -> 展示名。顺序与 ``adapters/__init__._ADAPTER_MODULES`` 一致。
# 一个平台一个 bool 开关，取代旧版「DISABLED_PLATFORMS 逗号填名字」的写法。
# 新增平台适配器时在这里补一行，并在 _conf_schema.json 的「解析器开关」组加同名条目。
PLATFORM_SWITCHES: tuple[tuple[str, str], ...] = (
    ("bilibili", "B站"),
    ("douyin", "抖音"),
    ("kuaishou", "快手"),
    ("weibo", "微博"),
    ("xiaohongshu", "小红书"),
    ("twitter", "Twitter/X"),
    ("nga", "NGA"),
    ("acfun", "AcFun"),
)

#: 旧版 DISABLED_PLATFORMS 所在的分组（迁移时要从这儿读旧值）
_LEGACY_DISABLED_GROUP = "平台设置"


def platform_switch_key(name: str) -> str:
    """平台名 -> 开关配置键，如 ``bilibili`` → ``PLATFORM_BILIBILI_ENABLED``。"""
    return f"PLATFORM_{name.upper()}_ENABLED"


# 分组展示顺序即此处的顺序（常用在前、折腾在后）。
# 组名同时是 _conf_schema.json 里的 object 键与配置文件的分组键，**不要改**。
CONFIG_GROUPS: tuple[tuple[str, str], ...] = (
    ("解析器开关", "各平台解析器的启用开关"),
    ("平台设置", "各平台的解析与下载设置"),
    ("Twitter 设置", "Twitter/X 反代（媒体与解析接口改走自定义反代，绕过 twimg.com / api.vxtwitter.com 无法直连）"),
    ("B站设置", "B站 Cookie、下载清晰度与 Cookie 监控"),
    ("缓存设置", "缓存文件过期与自动清理策略"),
    ("解析图片渲染", "将解析结果渲染为精美卡片图片发送（Pillow 实现，无需浏览器）"),
    ("Cloudflare 基础设置", "Cloudflare 网页截图兜底的开关、凭据与缓存"),
    ("Cloudflare 截图设置", "页面渲染与截图参数（视窗、等待策略、格式等）"),
    ("调试设置", "日志与调试选项"),
)

# 配置项元数据。字段说明：
#   key/group/label/type/default/hint 必填
#   type 取值 string | text | int | float | bool | select | list
#   secret=True 表示页面用密码框展示（仅遮罩显示，配置文件里仍是明文，与原生面板一致）
#   options/labels 仅 select 使用；min/max/unit 仅 int / float 使用
#   placeholder 仅输入框使用；max_length 限制文本长度
CONFIG_META: tuple[dict[str, Any], ...] = (
    # ---------------- 解析器开关 ---------------- #
    *(
        {
            "key": platform_switch_key(name),
            "group": "解析器开关",
            "label": f"解析 {label} 链接",
            "type": "bool",
            "default": True,
            "hint": f"关闭后不再解析{label}链接，其余平台不受影响",
        }
        for name, label in PLATFORM_SWITCHES
    ),
    # ---------------- 平台设置 ---------------- #
    {
        "key": "VIDEO_DURATION_MAXIMUM",
        "group": "平台设置",
        "label": "视频/音频最大时长",
        "type": "int",
        "default": 480,
        "min": 0,
        "max": 86400,
        "unit": "秒",
        "hint": "超过此时长的视频不会被下载，但仍会返回标题、作者和封面",
    },
    {
        "key": "DOUYIN_LIVE_PHOTO_ENABLED",
        "group": "平台设置",
        "label": "抖音动态图重建",
        "type": "bool",
        "default": True,
        "hint": "开启后，抖音的实况照片与普通动图都改为「主图 + 短视频」重建为单文件动态照片（可用 Google 相册 / 小米 / OPPO / vivo / 三星相册播放）；关闭则只发静态主图。不依赖 ffmpeg",
    },
    {
        "key": "XHS_CK",
        "group": "平台设置",
        "label": "小红书 Cookie",
        "type": "text",
        "default": "",
        "secret": True,
        "hint": "从浏览器获取 xiaohongshu.com 的 cookie（可选）",
    },
    {
        "key": "FORWARD_MAX_NODES",
        "group": "平台设置",
        "label": "单条合并转发最大节点数",
        "type": "int",
        "default": 10,
        "min": 1,
        "max": 50,
        "unit": "个",
        "hint": "OneBot 合并转发会把节点内的图片全部 base64 编码后再整体序列化，峰值内存约为图片总量的 4 倍。图集较大时按此值拆成多条发送，避免 OOM。仅对 OneBot(aiocqhttp) 生效",
    },
    {
        "key": "FORWARD_MAX_BATCH_MB",
        "group": "平台设置",
        "label": "单条合并转发图片体积上限",
        "type": "int",
        "default": 30,
        "min": 1,
        "max": 64,
        "unit": "MB",
        "hint": "按图片原始字节累计计算，超出即拆成下一条。调小更省内存但会发更多条消息。单张超过此值的图片会单独成一条发送",
    },
    # ---------------- Twitter 设置 ---------------- #
    {
        "key": "TWITTER_MEDIA_PROXY_ENABLED",
        "group": "Twitter 设置",
        "label": "启用 Twitter 反代",
        "type": "bool",
        "default": False,
        "hint": "开启后，推文的图片、视频、封面与作者头像改从自定义反代地址下载，解析接口 api.vxtwitter.com 也一并改走反代（需部署最新版 Worker）",
    },
    {
        "key": "TWITTER_MEDIA_PROXY_BASE",
        "group": "Twitter 设置",
        "label": "Twitter 反代地址",
        "type": "string",
        "default": "",
        "placeholder": "https://x-media-proxy.xxx.workers.dev",
        "hint": "Cloudflare Worker 反代根地址，结尾不要带斜杠",
    },
    # ---------------- B站设置 ---------------- #
    {
        "key": "BILI_CK",
        "group": "B站设置",
        "label": "哔哩哔哩 Cookie",
        "type": "text",
        "default": "",
        "secret": True,
        "hint": "从浏览器获取 bilibili.com 的 SESSDATA 值，或用 /bili_login 扫码登录自动写入；配了才能下 1080P 及以上",
    },
    {
        "key": "BILI_QUALITY",
        "group": "B站设置",
        "label": "B站视频下载清晰度",
        "type": "select",
        "default": "1080P",
        "options": ["360P", "480P", "720P", "1080P", "1080P+", "4K", "8K"],
        "hint": "需要对应账号权限；未登录时实际只能拿到 720P",
    },
    {
        "key": "BILI_COOKIE_MONITOR_ENABLED",
        "group": "B站设置",
        "label": "启用B站Cookie定时监控",
        "type": "bool",
        "default": True,
        "hint": "开启后将定时检测B站Cookie是否有效，失效时自动通知",
    },
    {
        "key": "BILI_COOKIE_CHECK_INTERVAL",
        "group": "B站设置",
        "label": "B站Cookie检测间隔",
        "type": "int",
        "default": 3600,
        "min": 60,
        "max": 86400,
        "unit": "秒",
        "hint": "每隔多少秒检测一次Cookie有效性，最小 60 秒",
    },
    {
        "key": "BILI_NOTIFY_USER_ID",
        "group": "B站设置",
        "label": "Cookie失效/恢复时通知的QQ号",
        "type": "string",
        "default": "",
        "hint": "留空则不发送通知，只记录日志",
    },
    # ---------------- 缓存设置 ---------------- #
    {
        "key": "CACHE_TTL_HOURS",
        "group": "缓存设置",
        "label": "缓存文件过期时间",
        "type": "int",
        "default": 24,
        "min": 0,
        "max": 720,
        "unit": "小时",
        "hint": "缓存文件超过此时间未被使用将被清理；设为 0 禁用自动清理",
    },
    {
        "key": "CACHE_CLEANUP_INTERVAL_MINUTES",
        "group": "缓存设置",
        "label": "缓存清理检查间隔",
        "type": "int",
        "default": 60,
        "min": 1,
        "max": 1440,
        "unit": "分钟",
        "hint": "每隔多少分钟检查一次过期缓存（改动需重载插件后生效）",
    },
    # ---------------- 解析图片渲染 ---------------- #
    {
        "key": "RENDER_ENABLED",
        "group": "解析图片渲染",
        "label": "启用解析图片渲染",
        "type": "bool",
        "default": True,
        "hint": "开启后解析结果会渲染成一张分享卡片图片；渲染失败时自动回退为文本输出",
    },
    {
        "key": "RENDER_THEME",
        "group": "解析图片渲染",
        "label": "卡片主题",
        "type": "select",
        "default": "dark",
        "options": ["dark", "light"],
        "labels": ["dark 深色", "light 浅色"],
        "hint": "深色 / 浅色两套主题",
    },
    {
        "key": "RENDER_LAYOUT",
        "group": "解析图片渲染",
        "label": "卡片布局",
        "type": "select",
        "default": "standard",
        "options": ["standard", "magazine", "immersive", "feed"],
        "labels": [
            "standard 标准横幅（全宽封面）",
            "magazine 双栏杂志（封面左置）",
            "immersive 沉浸全屏（无图自动回退标准）",
            "feed 社交动态（作者优先，媒体内嵌）",
        ],
        "hint": "无封面内容在 immersive 布局下会自动回退到 standard",
    },
    {
        "key": "RENDER_WIDTH",
        "group": "解析图片渲染",
        "label": "卡片宽度",
        "type": "int",
        "default": 800,
        "min": 520,
        "max": 1080,
        "unit": "px",
        "hint": "卡片图片宽度，范围 520-1080",
    },
    {
        "key": "RENDER_FONT_PATH",
        "group": "解析图片渲染",
        "label": "自定义渲染字体",
        "type": "string",
        "default": "",
        "placeholder": "留空自动探测",
        "hint": "填写 .ttf/.ttc/.otf 字体文件路径或所在目录；留空自动探测系统中文字体",
    },
    {
        "key": "RENDER_COVER_FULL_SIZE",
        "group": "解析图片渲染",
        "label": "封面全尺寸模式",
        "type": "bool",
        "default": False,
        "hint": "开启后不再裁剪封面图片，而是按封面原始宽高比完整展示",
    },
    # ---------------- Cloudflare 基础设置 ---------------- #
    {
        "key": "CLOUDFLARE_FALLBACK_ENABLED",
        "group": "Cloudflare 基础设置",
        "label": "启用 Cloudflare 网页截图 Fallback",
        "type": "bool",
        "default": False,
        "hint": "开启后，链接不匹配任何已适配平台时，自动使用 Cloudflare Browser Rendering 渲染网页截图为图片发送",
    },
    {
        "key": "CLOUDFLARE_ACCOUNT_ID",
        "group": "Cloudflare 基础设置",
        "label": "Cloudflare 账号 ID",
        "type": "string",
        "default": "",
        "hint": "Cloudflare Dashboard 可查看，需开通 Browser Rendering 服务",
    },
    {
        "key": "CLOUDFLARE_API_TOKEN",
        "group": "Cloudflare 基础设置",
        "label": "Cloudflare API Token",
        "type": "string",
        "default": "",
        "secret": True,
        "hint": "需拥有 Browser Rendering - Edit 权限",
    },
    {
        "key": "CLOUDFLARE_TIMEOUT",
        "group": "Cloudflare 基础设置",
        "label": "截图 API 超时时间",
        "type": "int",
        "default": 60,
        "min": 1,
        "max": 600,
        "unit": "秒",
        "hint": "Cloudflare 渲染页面超时，建议 30-120 秒",
    },
    {
        "key": "CLOUDFLARE_CACHE_TTL",
        "group": "Cloudflare 基础设置",
        "label": "截图缓存时间",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 86400,
        "unit": "秒",
        "hint": "0 表示不缓存、始终重新渲染；设置后相同页面在 TTL 内直接返回缓存结果（省额度）",
    },
    {
        "key": "CLOUDFLARE_BLACKLIST",
        "group": "Cloudflare 基础设置",
        "label": "截图黑名单",
        "type": "list",
        "default": [],
        "hint": "一行一条。命中后跳过该链接的 Cloudflare 截图，支持域名（example.com 含子域名）、通配符（*.example.com、https://example.com/*）和不含点的关键词",
    },
    # ---------------- Cloudflare 截图设置 ---------------- #
    {
        "key": "CLOUDFLARE_VIEWPORT_WIDTH",
        "group": "Cloudflare 截图设置",
        "label": "截图视窗宽度",
        "type": "int",
        "default": 1280,
        "min": 320,
        "max": 3840,
        "unit": "px",
        "hint": "渲染页面使用的浏览器视窗宽度",
    },
    {
        "key": "CLOUDFLARE_VIEWPORT_HEIGHT",
        "group": "Cloudflare 截图设置",
        "label": "截图视窗高度",
        "type": "int",
        "default": 720,
        "min": 320,
        "max": 4320,
        "unit": "px",
        "hint": "渲染页面使用的浏览器视窗高度",
    },
    {
        "key": "CLOUDFLARE_WAIT_UNTIL",
        "group": "Cloudflare 截图设置",
        "label": "页面加载等待策略",
        "type": "select",
        "default": "networkidle0",
        "options": ["load", "domcontentloaded", "networkidle0", "networkidle2"],
        "hint": "JS 重页面建议 networkidle0/networkidle2（等待网络空闲后再截图）；速度优先可选 load/domcontentloaded",
    },
    {
        "key": "CLOUDFLARE_GOTO_TIMEOUT",
        "group": "Cloudflare 截图设置",
        "label": "页面加载超时",
        "type": "int",
        "default": 45000,
        "min": 5000,
        "max": 120000,
        "unit": "毫秒",
        "hint": "Cloudflare 页面导航超时，官方推荐 45000ms",
    },
    {
        "key": "CLOUDFLARE_FULL_PAGE",
        "group": "Cloudflare 截图设置",
        "label": "整页截图",
        "type": "bool",
        "default": False,
        "hint": "开启后截取完整页面（含滚动区域），关闭则只截当前视窗",
    },
    {
        "key": "CLOUDFLARE_DEVICE_SCALE_FACTOR",
        "group": "Cloudflare 截图设置",
        "label": "截图清晰度",
        "type": "float",
        "default": 1,
        "min": 1,
        "max": 3,
        "unit": "倍",
        "hint": "deviceScaleFactor。增大可避免大视窗截图模糊，建议 1-3",
    },
    {
        "key": "CLOUDFLARE_SCREENSHOT_TYPE",
        "group": "Cloudflare 截图设置",
        "label": "截图格式",
        "type": "select",
        "default": "png",
        "options": ["png", "jpeg"],
        "hint": "png 支持透明背景；jpeg 体积更小，可配合质量参数",
    },
    {
        "key": "CLOUDFLARE_SCREENSHOT_QUALITY",
        "group": "Cloudflare 截图设置",
        "label": "截图质量",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 100,
        "hint": "仅 jpeg 有效，0-100。0 表示不指定（使用 Cloudflare 默认）；png 下会被自动忽略",
    },
    {
        "key": "CLOUDFLARE_OMIT_BACKGROUND",
        "group": "Cloudflare 截图设置",
        "label": "透明背景",
        "type": "bool",
        "default": False,
        "hint": "开启后隐藏默认白色背景，适合 png 透明图（仅 png 生效）",
    },
    {
        "key": "CLOUDFLARE_SELECTOR",
        "group": "Cloudflare 截图设置",
        "label": "指定元素截图",
        "type": "string",
        "default": "",
        "placeholder": "#content",
        "hint": "填写 CSS 选择器，只截取该元素区域，留空截取整个页面",
    },
    {
        "key": "CLOUDFLARE_WAIT_FOR_SELECTOR",
        "group": "Cloudflare 截图设置",
        "label": "等待元素出现后再截图",
        "type": "string",
        "default": "",
        "placeholder": "#content",
        "hint": "JS 动态页面可填写内容加载完成的 CSS 选择器，浏览器会等该元素出现再截图",
    },
    {
        "key": "CLOUDFLARE_WAIT_FOR_TIMEOUT",
        "group": "Cloudflare 截图设置",
        "label": "等待元素超时",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 120000,
        "unit": "毫秒",
        "hint": "配合「等待元素出现」使用，0 表示使用 Cloudflare 默认",
    },
    {
        "key": "CLOUDFLARE_USER_AGENT",
        "group": "Cloudflare 截图设置",
        "label": "自定义 User-Agent",
        "type": "string",
        "default": "",
        "hint": "留空使用 Cloudflare 默认 UA；部分站点按 UA 返回不同内容",
    },
    {
        "key": "CLOUDFLARE_EXTRA_HEADERS",
        "group": "Cloudflare 截图设置",
        "label": "附加请求头",
        "type": "text",
        "default": "",
        "hint": '加载页面时附加的 HTTP 头，JSON 格式，如 {"Authorization":"Bearer xxx"}',
    },
    {
        "key": "CLOUDFLARE_COOKIES",
        "group": "Cloudflare 截图设置",
        "label": "附加 Cookie",
        "type": "text",
        "default": "",
        "hint": '需要登录的页面可配置 Cookie 数组，如 [{"name":"session","value":"xxx","domain":"example.com","path":"/"}]',
    },
    # ---------------- 调试设置 ---------------- #
    {
        "key": "DEBUG_LOG_ENABLED",
        "group": "调试设置",
        "label": "启用详细错误日志",
        "type": "bool",
        "default": True,
        "hint": "关闭后，下载失败等错误不会在日志中打印详细堆栈",
    },
    {
        "key": "SEND_ERROR_MESSAGES",
        "group": "调试设置",
        "label": "发送插件错误消息",
        "type": "bool",
        "default": False,
        "hint": "开启后，插件发生错误时向对话发送错误信息；关闭后仅保留插件日志",
    },
)

_ITEM_BY_KEY: dict[str, dict[str, Any]] = {item["key"]: item for item in CONFIG_META}

# 分组名 -> 组内配置项（由 CONFIG_META 按 CONFIG_GROUPS 的顺序派生）
CONFIG_GROUP_KEYS: dict[str, tuple[str, ...]] = {
    group: tuple(item["key"] for item in CONFIG_META if item["group"] == group)
    for group, _ in CONFIG_GROUPS
}

_KEY_GROUP_MAP: dict[str, str] = {
    key: group for group, keys in CONFIG_GROUP_KEYS.items() for key in keys
}

# 各配置项的默认值（与 _conf_schema.json 保持一致），用于旧配置迁移判断
_LEGACY_DEFAULTS: dict[str, Any] = {item["key"]: item["default"] for item in CONFIG_META}

#: 文本类配置项的长度上限（Cookie / JSON 字段可能很长，但不能无限长）
_MAX_TEXT_LENGTH = 8000

#: 只留在 ``_conf_schema.json`` 里、不再对外暴露的旧键。
#
# ``DISABLED_PLATFORMS`` 被「解析器开关」取代后不再是配置项，但它必须继续留在
# schema 中：AstrBot 加载插件配置时会剔除 schema 之外的键，一旦剔掉，
# 老用户填过的禁用平台名就没机会被 :func:`migrate_platform_switches` 读到。
LEGACY_ONLY_KEYS: frozenset[str] = frozenset({"DISABLED_PLATFORMS"})


def config_meta_payload() -> dict[str, Any]:
    """返回供网页设置页渲染的配置元数据（分组 + 全部配置项定义）。"""
    return {
        "groups": [
            {
                "name": name,
                "description": description,
                "keys": list(CONFIG_GROUP_KEYS.get(name, ())),
            }
            for name, description in CONFIG_GROUPS
        ],
        "items": [dict(item) for item in CONFIG_META],
    }


def coerce_value(item: dict[str, Any], raw: Any) -> tuple[Any, str | None]:
    """把网页设置页提交的值转成配置要求的类型。

    Returns:
        (转换后的值, 错误描述)。错误描述非 None 时调用方应丢弃该值。
    """
    key = item["key"]
    label = item.get("label", key)
    kind = item["type"]

    if kind == "bool":
        if isinstance(raw, bool):
            return raw, None
        if isinstance(raw, str):
            lowered = raw.strip().lower()
            if lowered in {"true", "1", "yes", "on"}:
                return True, None
            if lowered in {"false", "0", "no", "off", ""}:
                return False, None
        return None, f"{label}：需要是开关值"

    if kind == "int":
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            return None, f"{label}：需要是整数"
        low, high = item.get("min"), item.get("max")
        if low is not None and value < low:
            return None, f"{label}：不能小于 {low}"
        if high is not None and value > high:
            return None, f"{label}：不能大于 {high}"
        return value, None

    if kind == "float":
        try:
            value = float(str(raw).strip())
        except (TypeError, ValueError):
            return None, f"{label}：需要是数字"
        low, high = item.get("min"), item.get("max")
        if low is not None and value < low:
            return None, f"{label}：不能小于 {low}"
        if high is not None and value > high:
            return None, f"{label}：不能大于 {high}"
        return value, None

    if kind == "list":
        # 页面用「一行一条」的 textarea 编辑；也接受直接提交的数组
        rows = raw if isinstance(raw, list) else str(raw or "").splitlines()
        values: list[str] = []
        for row in rows:
            text = str(row).strip()
            if not text:
                continue
            # 兼容用户在单行里用逗号分隔的写法
            for part in text.split(","):
                part = part.strip()
                if part and part not in values:
                    values.append(part)
        return values, None

    text = "" if raw is None else str(raw).strip()

    if kind == "select":
        options = item.get("options") or []
        if text and text not in options:
            return None, f"{label}：只能是 {' / '.join(options)} 之一"
        return text, None

    if len(text) > _MAX_TEXT_LENGTH:
        return None, f"{label}：内容过长（超过 {_MAX_TEXT_LENGTH} 字）"

    max_length = item.get("max_length")
    if max_length is not None and len(text) > int(max_length):
        return None, f"{label}：不能超过 {max_length} 个字符"
    pattern = item.get("pattern")
    if pattern and text and not re.match(pattern, text):
        return None, f"{label}：格式不正确（需要 {pattern}）"
    return text, None


def verify_schema_alignment(schema: dict[str, Any]) -> list[str]:
    """自检 ``_conf_schema.json`` 与 :data:`CONFIG_META` 的键集合是否一致。

    AstrBot 加载插件配置时会剔除 schema 之外的键，两者一旦不一致，用户保存的值
    会在下次重载时静默丢失，因此必须显式比对。

    schema 底部的旧版扁平条目（``invisible`` 且不在任何分组里）是迁移契约，
    不参与本校验。:data:`LEGACY_ONLY_KEYS` 同理——它们只为迁移而存在，
    但**必须**在 schema 里出现，否则老配置会被 AstrBot 直接剔除。

    还会校验**分组可见性**：AstrBot 渲染插件配置时（``AstrBotConfig.vue``）组标题
    只看 ``type === 'object'``，不检查组内是否还有可见项，所以组内条目全被隐藏时
    必须把组对象本身也标 ``invisible``，否则面板上会残留一个空标题。

    Returns:
        描述差异的字符串列表，空列表表示一致。
    """
    schema_keys: set[str] = set()
    schema_group_of: dict[str, str] = {}
    problems: list[str] = []

    for group, node in schema.items():
        if not isinstance(node, dict) or not isinstance(node.get("items"), dict):
            continue  # 旧版扁平条目：不是分组，跳过
        for key in node["items"]:
            if key in LEGACY_ONLY_KEYS:
                continue
            schema_keys.add(key)
            schema_group_of[key] = group
        if group not in CONFIG_GROUP_KEYS:
            problems.append(f"schema 里存在 CONFIG_GROUPS 未声明的分组：{group}")

        # 分组可见性必须与「组内是否有可见条目」一致，否则不是空标题就是误藏
        has_visible = any(
            item.get("invisible") is not True for item in node["items"].values()
        )
        if has_visible == (node.get("invisible") is True):
            if has_visible:
                problems.append(
                    f"{group} 组内还有可见条目，但分组被标了 invisible，整组都会被藏起来"
                )
            else:
                problems.append(
                    f"{group} 组内条目全部 invisible，但分组本身没标 invisible，"
                    "原生配置面板会残留一个空标题"
                )

    for key in sorted(LEGACY_ONLY_KEYS):
        if key not in schema and not any(
            isinstance(node, dict)
            and isinstance(node.get("items"), dict)
            and key in node["items"]
            for node in schema.values()
        ):
            problems.append(
                f"迁移用的旧键 {key} 不在 schema 里，老配置会被 AstrBot 剔除"
            )

    meta_keys = set(_ITEM_BY_KEY)
    for key in sorted(schema_keys - meta_keys):
        problems.append(f"schema 有而 CONFIG_META 缺失的键：{key}")
    for key in sorted(meta_keys - schema_keys):
        problems.append(f"CONFIG_META 有而 schema 缺失的键：{key}")
    for key in sorted(schema_keys & meta_keys):
        if schema_group_of[key] != _KEY_GROUP_MAP.get(key):
            problems.append(
                f"{key} 在 schema 里属于 {schema_group_of[key]} 组，"
                f"但 CONFIG_META 归到 {_KEY_GROUP_MAP.get(key)} 组"
            )
    return problems


def _known_platform_names() -> list[str]:
    """当前注册的全部平台名（含 CONFIG_META 里没写开关的新平台）。

    运行时才从注册表读，避免 config 与 adapters 形成模块级循环导入。
    """
    try:
        from .adapters import adapter_names

        names = list(adapter_names())
        if names:
            return names
    except Exception:  # noqa: BLE001 - 注册表不可用时退回静态清单
        pass
    return [name for name, _ in PLATFORM_SWITCHES]


def _read_legacy_disabled(config: Any) -> str:
    """读旧版 DISABLED_PLATFORMS 逗号串（可能存在分组里，也可能在顶层）。"""
    for source in (config.get(_LEGACY_DISABLED_GROUP), config):
        if isinstance(source, dict):
            raw = source.get("DISABLED_PLATFORMS")
            if raw:
                return str(raw)
    return ""


def migrate_platform_switches(config: Any) -> bool:
    """把旧版 ``DISABLED_PLATFORMS`` 逗号串迁移成各解析器的独立开关。

    迁移后清空旧串，让「开关」成为平台启停的唯一真相——否则旧串里残留的名字
    会在用户把开关拨回「启用」时把它按回去，表现为开关拨不动。

    重复调用是幂等的（旧串为空时直接返回 False）。
    """
    legacy = _read_legacy_disabled(config)
    names = [item.strip().lower() for item in legacy.split(",") if item.strip()]
    if not names:
        return False

    group = _KEY_GROUP_MAP[platform_switch_key(PLATFORM_SWITCHES[0][0])]
    group_cfg = config.get(group)
    if not isinstance(group_cfg, dict):
        group_cfg = {}
        config[group] = group_cfg

    changed = False
    for name in names:
        key = platform_switch_key(name)
        if key not in _ITEM_BY_KEY:
            continue  # 平台已下线或改名，忽略
        if group_cfg.get(key, True) is False:
            continue
        group_cfg[key] = False
        changed = True

    # 旧串已搬完，清空（分组里和顶层都要清，两处都会被读到）
    config["DISABLED_PLATFORMS"] = ""
    legacy_group = config.get(_LEGACY_DISABLED_GROUP)
    if isinstance(legacy_group, dict):
        legacy_group["DISABLED_PLATFORMS"] = ""
    return changed


def migrate_grouped_config(config: Any) -> bool:
    """将旧版扁平配置迁移到分组配置，返回是否发生变更

    仅当分组值仍为默认值、而扁平旧值被用户改过时才迁移，
    因此重复调用是幂等的。
    """
    changed = False
    for group, keys in CONFIG_GROUP_KEYS.items():
        group_cfg = config.get(group)
        if not isinstance(group_cfg, dict):
            group_cfg = {}
            config[group] = group_cfg
        for key in keys:
            default = _LEGACY_DEFAULTS.get(key)
            flat_val = config.get(key, default)
            nested_val = group_cfg.get(key, default)
            if nested_val == default and flat_val != default:
                group_cfg[key] = flat_val
                config[key] = default
                changed = True
    return changed


class ParserConfig:
    """解析器配置 - 由插件入口（main.py）初始化

    通过 :func:`get_config` 全局访问；未初始化时调用会抛 ``RuntimeError``。
    """

    def __init__(self, astrbot_config: Any, cache_dir: Path, config_dir: Path):
        self._cfg = astrbot_config
        self.cache_dir = cache_dir
        self.config_dir = config_dir

    # ---------------- 网页设置页读写 ---------------- #

    def current_values(self) -> dict[str, Any]:
        """返回全部配置项的当前生效值（键 → 值）。"""
        return {
            item["key"]: self._cfg_get(item["key"], item["default"])
            for item in CONFIG_META
        }

    def apply_updates(self, payload: Any) -> tuple[list[str], list[str]]:
        """按白名单把网页设置页提交的值写回配置。

        只接受 :data:`CONFIG_META` 里声明的键；写入分组位置的同时把扁平旧键重置为
        默认值，避免遗留的旧值把新值盖掉（与 :func:`migrate_grouped_config` 同源）。

        Args:
            payload: 页面提交的 ``{配置键: 新值}``。

        Returns:
            (实际变更的键列表, 错误信息列表)。
        """
        if not isinstance(payload, dict):
            return [], ["提交内容不是对象"]

        changed: list[str] = []
        errors: list[str] = []

        for key, raw in payload.items():
            item = _ITEM_BY_KEY.get(key)
            if item is None:
                errors.append(f"未知配置项：{key}")
                continue
            value, error = coerce_value(item, raw)
            if error is not None:
                errors.append(error)
                continue
            if self._cfg_get(key, item["default"]) == value:
                continue
            group = _KEY_GROUP_MAP[key]
            group_cfg = self._cfg.get(group)
            if not isinstance(group_cfg, dict):
                group_cfg = {}
                self._cfg[group] = group_cfg
            group_cfg[key] = value
            # 同步重置扁平旧键，否则 _cfg_get 的回退分支会让旧值盖掉新值
            self._cfg[key] = item["default"]
            changed.append(key)

        if changed and not self.save():
            errors.append(
                "配置已生效但没能写入磁盘，重载插件后会回滚；"
                "请检查配置目录是否可写、磁盘是否已满"
            )
        return changed, errors

    def reset_to_defaults(self) -> list[str]:
        """把所有配置项恢复为默认值，返回被改动的键列表。"""
        changed, _ = self.apply_updates(
            {item["key"]: item["default"] for item in CONFIG_META}
        )
        return changed

    def save(self) -> bool:
        """持久化配置（AstrBotConfig 提供 ``save_config``，缺失时静默跳过）。

        Returns:
            是否真的写盘成功。失败必须让调用方看见——只写内存的修改在重载后会
            无声回滚，页面却已经提示「已保存」。
        """
        save = getattr(self._cfg, "save_config", None)
        if not callable(save):
            from astrbot.api import logger

            logger.warning(
                "[link_parser] 配置对象没有 save_config，本次修改只存在于内存，"
                "重载后会回滚"
            )
            return False
        try:
            save()
            return True
        except Exception:
            from astrbot.api import logger

            logger.exception(
                "[link_parser] 配置写入磁盘失败，本次修改只存在于内存，重载后会回滚"
            )
            return False

    # ---------------- 解析行为 ---------------- #

    def _cfg_get(self, key: str, default: Any = None) -> Any:
        """优先读取分组配置，其次回退到扁平旧配置"""
        group = _KEY_GROUP_MAP.get(key)
        if group is not None:
            group_cfg = self._cfg.get(group)
            if isinstance(group_cfg, dict) and key in group_cfg:
                default_val = _LEGACY_DEFAULTS.get(key, default)
                flat_val = self._cfg.get(key, default_val)
                nested_val = group_cfg[key]
                # 分组仍是默认值而扁平旧值被改过时，优先旧值（兼容迁移前的状态）
                if nested_val == default_val and flat_val != default_val:
                    return flat_val
                return nested_val
        return self._cfg.get(key, default)

    @property
    def BILI_CK(self) -> str | None:
        return self._cfg_get("BILI_CK", None)

    @property
    def XHS_CK(self) -> str | None:
        return self._cfg_get("XHS_CK", None)

    @property
    def TWITTER_MEDIA_PROXY_ENABLED(self) -> bool:
        """是否启用 Twitter/X 反代（媒体 CDN + 解析接口）"""
        return bool(self._cfg_get("TWITTER_MEDIA_PROXY_ENABLED", False))

    @property
    def TWITTER_MEDIA_PROXY_BASE(self) -> str:
        """Twitter/X 反代根地址（结尾斜杠会被去除）"""
        return str(self._cfg_get("TWITTER_MEDIA_PROXY_BASE", "") or "").strip().rstrip("/")

    @property
    def VIDEO_DURATION_MAXIMUM(self) -> int:
        return int(self._cfg_get("VIDEO_DURATION_MAXIMUM", 480))

    @property
    def DOUYIN_LIVE_PHOTO_ENABLED(self) -> bool:
        """抖音实况照片 / 普通动图是否重建为单文件动态照片

        关闭时只发静态主图（不再转 GIF）。
        """
        return bool(self._cfg_get("DOUYIN_LIVE_PHOTO_ENABLED", True))

    @property
    def DISABLED_PLATFORMS(self) -> list[str]:
        """被关闭的平台名列表，由「解析器开关」推导。

        开关是唯一真相；旧版 ``DISABLED_PLATFORMS`` 逗号串在启动时由
        :func:`migrate_platform_switches` 搬进开关后即被清空，不再参与判断。
        注册表里有、但没写开关的新平台默认启用。
        """
        return [
            name
            for name in _known_platform_names()
            if not bool(self._cfg_get(platform_switch_key(name), True))
        ]

    @property
    def FORWARD_MAX_NODES(self) -> int:
        """单条合并转发最多容纳的节点数（超出则拆成多条发送）"""
        return max(1, min(50, int(self._cfg_get("FORWARD_MAX_NODES", 10))))

    @property
    def FORWARD_MAX_BATCH_MB(self) -> int:
        """单条合并转发内图片原始字节累计上限（MB，超出则拆成多条发送）"""
        return max(1, min(64, int(self._cfg_get("FORWARD_MAX_BATCH_MB", 12))))

    @property
    def CACHE_TTL_HOURS(self) -> int:
        return int(self._cfg_get("CACHE_TTL_HOURS", 24))

    @property
    def CACHE_CLEANUP_INTERVAL_MINUTES(self) -> int:
        return int(self._cfg_get("CACHE_CLEANUP_INTERVAL_MINUTES", 60))

    # ==================== 解析图片渲染 ====================

    @property
    def RENDER_ENABLED(self) -> bool:
        """是否启用解析结果精美卡片渲染"""
        return bool(self._cfg_get("RENDER_ENABLED", True))

    @property
    def RENDER_THEME(self) -> str:
        """卡片主题：dark / light"""
        val = str(self._cfg_get("RENDER_THEME", "dark")).strip().lower()
        return val if val in {"dark", "light"} else "dark"

    @property
    def RENDER_LAYOUT(self) -> str:
        """卡片布局：standard / magazine / immersive / feed"""
        val = str(self._cfg_get("RENDER_LAYOUT", "standard")).strip().lower()
        return val if val in {"standard", "magazine", "immersive", "feed"} else "standard"

    @property
    def RENDER_WIDTH(self) -> int:
        """卡片宽度（像素）"""
        return max(520, min(1080, int(self._cfg_get("RENDER_WIDTH", 800))))

    @property
    def RENDER_FONT_PATH(self) -> str:
        """自定义渲染字体文件路径（留空自动探测系统字体）"""
        return str(self._cfg_get("RENDER_FONT_PATH", "") or "").strip()

    @property
    def RENDER_COVER_FULL_SIZE(self) -> bool:
        """是否启用封面全尺寸模式（不裁剪封面）"""
        return bool(self._cfg_get("RENDER_COVER_FULL_SIZE", False))

    @property
    def BILI_QUALITY(self) -> str:
        return str(self._cfg_get("BILI_QUALITY", "1080P"))

    @property
    def BILI_COOKIE_MONITOR_ENABLED(self) -> bool:
        return bool(self._cfg_get("BILI_COOKIE_MONITOR_ENABLED", True))

    @property
    def BILI_COOKIE_CHECK_INTERVAL(self) -> int:
        val = int(self._cfg_get("BILI_COOKIE_CHECK_INTERVAL", 3600))
        return max(60, val)

    @property
    def BILI_NOTIFY_USER_ID(self) -> str:
        return str(self._cfg_get("BILI_NOTIFY_USER_ID", ""))

    # ==================== Cloudflare 截图 Fallback ====================

    @property
    def CLOUDFLARE_FALLBACK_ENABLED(self) -> bool:
        """是否启用 Cloudflare 截图 fallback"""
        return bool(self._cfg_get("CLOUDFLARE_FALLBACK_ENABLED", False))

    @property
    def CLOUDFLARE_ACCOUNT_ID(self) -> str:
        """Cloudflare 账号 ID"""
        return str(self._cfg_get("CLOUDFLARE_ACCOUNT_ID", ""))

    @property
    def CLOUDFLARE_API_TOKEN(self) -> str:
        """Cloudflare API Token（需要 Browser Rendering - Edit 权限）"""
        return str(self._cfg_get("CLOUDFLARE_API_TOKEN", ""))

    @property
    def CLOUDFLARE_TIMEOUT(self) -> int:
        """截图 API 超时时间（秒）"""
        return int(self._cfg_get("CLOUDFLARE_TIMEOUT", 60))

    @property
    def CLOUDFLARE_VIEWPORT_WIDTH(self) -> int:
        """截图视窗宽度"""
        return int(self._cfg_get("CLOUDFLARE_VIEWPORT_WIDTH", 1280))

    @property
    def CLOUDFLARE_VIEWPORT_HEIGHT(self) -> int:
        """截图视窗高度"""
        return int(self._cfg_get("CLOUDFLARE_VIEWPORT_HEIGHT", 720))

    @property
    def CLOUDFLARE_WAIT_UNTIL(self) -> str:
        """页面加载等待策略"""
        val = str(self._cfg_get("CLOUDFLARE_WAIT_UNTIL", "networkidle0")).strip().lower()
        if val not in {"load", "domcontentloaded", "networkidle0", "networkidle2"}:
            return "networkidle0"
        return val

    @property
    def CLOUDFLARE_GOTO_TIMEOUT(self) -> int:
        """页面加载超时（毫秒）"""
        return max(0, int(self._cfg_get("CLOUDFLARE_GOTO_TIMEOUT", 45000)))

    @property
    def CLOUDFLARE_FULL_PAGE(self) -> bool:
        """是否整页截图"""
        return bool(self._cfg_get("CLOUDFLARE_FULL_PAGE", False))

    @property
    def CLOUDFLARE_DEVICE_SCALE_FACTOR(self) -> float:
        """截图清晰度（deviceScaleFactor）"""
        try:
            val = float(self._cfg_get("CLOUDFLARE_DEVICE_SCALE_FACTOR", 1))
        except (TypeError, ValueError):
            val = 1.0
        return val if val > 0 else 1.0

    @property
    def CLOUDFLARE_OMIT_BACKGROUND(self) -> bool:
        """是否隐藏默认白色背景（仅 png 有效）"""
        return bool(self._cfg_get("CLOUDFLARE_OMIT_BACKGROUND", False))

    @property
    def CLOUDFLARE_SCREENSHOT_TYPE(self) -> str:
        """截图格式（png/jpeg）"""
        val = (
            str(self._cfg_get("CLOUDFLARE_SCREENSHOT_TYPE", "png"))
            .strip()
            .lower()
            .lstrip(".")
        )
        if val == "jpg":
            val = "jpeg"
        return val if val in {"png", "jpeg"} else "png"

    @property
    def CLOUDFLARE_SCREENSHOT_QUALITY(self) -> int:
        """截图质量（仅 jpeg 有效，0 表示不指定）"""
        return max(
            0, min(100, int(self._cfg_get("CLOUDFLARE_SCREENSHOT_QUALITY", 0)))
        )

    @property
    def CLOUDFLARE_SELECTOR(self) -> str:
        """指定元素截图 CSS 选择器"""
        return str(self._cfg_get("CLOUDFLARE_SELECTOR", "") or "").strip()

    @property
    def CLOUDFLARE_WAIT_FOR_SELECTOR(self) -> str:
        """等待元素出现的 CSS 选择器"""
        return str(self._cfg_get("CLOUDFLARE_WAIT_FOR_SELECTOR", "") or "").strip()

    @property
    def CLOUDFLARE_WAIT_FOR_TIMEOUT(self) -> int:
        """等待元素超时（毫秒），0 表示不指定"""
        return max(0, int(self._cfg_get("CLOUDFLARE_WAIT_FOR_TIMEOUT", 0)))

    @property
    def CLOUDFLARE_USER_AGENT(self) -> str:
        """自定义 User-Agent"""
        return str(self._cfg_get("CLOUDFLARE_USER_AGENT", "") or "").strip()

    @property
    def CLOUDFLARE_EXTRA_HEADERS(self) -> str:
        """附加请求头（JSON 字符串）"""
        return str(self._cfg_get("CLOUDFLARE_EXTRA_HEADERS", "") or "")

    @property
    def CLOUDFLARE_COOKIES(self) -> str:
        """附加 Cookie（JSON 字符串）"""
        return str(self._cfg_get("CLOUDFLARE_COOKIES", "") or "")

    @property
    def CLOUDFLARE_CACHE_TTL(self) -> int:
        """截图缓存时间（秒），0 表示不缓存"""
        return max(0, min(86400, int(self._cfg_get("CLOUDFLARE_CACHE_TTL", 0))))

    @property
    def CLOUDFLARE_BLACKLIST(self) -> list[str]:
        """Cloudflare 截图黑名单（域名/通配符/关键词，逗号或换行分隔）"""
        from .services.web_screenshot import normalize_blacklist

        return normalize_blacklist(self._cfg_get("CLOUDFLARE_BLACKLIST", []))

    @property
    def DEBUG_LOG_ENABLED(self) -> bool:
        """是否启用详细错误日志"""
        return bool(self._cfg_get("DEBUG_LOG_ENABLED", True))

    @property
    def SEND_ERROR_MESSAGES(self) -> bool:
        """是否向对话发送插件错误消息"""
        return bool(self._cfg_get("SEND_ERROR_MESSAGES", False))


def init_config(astrbot_config: Any, cache_dir: Path, config_dir: Path) -> ParserConfig:
    global _config
    _config = ParserConfig(astrbot_config, cache_dir, config_dir)
    return _config


def get_config() -> ParserConfig:
    global _config
    if _config is None:
        raise RuntimeError("ParserConfig not initialized yet")
    return _config
