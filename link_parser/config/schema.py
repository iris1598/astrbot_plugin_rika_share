"""配置元数据定义、类型校验与 Schema 一致性自检。

配置项的唯一来源是 :data:`CONFIG_META`：
- WebUI 页面（``views/rika``）按它动态渲染分类与表单；
- ``_conf_schema.json`` 是同一次定义的存储契约，启动时通过
  :func:`verify_schema_alignment` 校验两者完全一致。
"""

from __future__ import annotations

import re
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .runtime import ParserConfig

#: ``CONFIG_META`` 中不走通用控件渲染的特殊钩子标识
CONTROL_PLATFORMS = "platforms"
CONTROL_THEME = "theme"

#: 文本类配置项的长度上限
_MAX_TEXT_LENGTH = 8000

#: 样式注册表不可用时的内置回退清单
_BUILTIN_STYLE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("standard", "standard · 标准横幅（顶部全宽封面 + 纵向信息流）"),
    ("magazine", "magazine · 双栏杂志（封面左置、标题作者右置）"),
    ("immersive", "immersive · 沉浸全屏（封面铺满整卡，无图回退标准）"),
    ("feed", "feed · 社交动态（作者优先，媒体内嵌）"),
)

#: 配置分组定义：(分组名, 分组说明, 所属一级分类)
#: 分组名同时是 _conf_schema.json 中的 object 键与持久化配置分组键。
CONFIG_GROUPS: tuple[tuple[str, str, str], ...] = (
    ("平台设置", "各平台的通用解析、视频时长上限与合并转发限制", "platforms"),
    ("B站设置", "B站 Cookie、下载清晰度、编码偏好与失效监控", "platforms"),
    ("Twitter 设置", "Twitter/X 反代（媒体 CDN 与解析接口改走自定义 Worker）", "platforms"),
    ("解析图片渲染", "Pillow 分享卡片样式、配色与字体设置", "output"),
    ("网页分享设置", "非 OneBot 平台将合并转发转为网页链接发送", "output"),
    ("缓存设置", "缓存文件过期时间与自动清理间隔", "output"),
    ("Cloudflare 基础设置", "未适配链接的网页截图兜底开关、凭据与黑名单", "fallback"),
    ("Cloudflare 截图设置", "浏览器视窗、等待策略、格式与附加请求头等高级参数", "fallback"),
    ("调试设置", "错误堆栈日志与对话错误回显策略", "fallback"),
    ("外观设置", "控制面板主题风格与明暗配色模式", "appearance"),
)

#: 全部配置项元数据（唯一数据源）
CONFIG_META: tuple[dict[str, Any], ...] = (
    # ---------------- 平台设置 ---------------- #
    {
        "key": "DISABLED_PLATFORMS",
        "group": "平台设置",
        "label": "解析器开关",
        "type": "string",
        "default": "",
        "control": CONTROL_PLATFORMS,
        "hint": "点一下即可启用或关闭对应平台解析；清单由适配器注册表实时生成",
    },
    {
        "key": "VIDEO_DURATION_MAXIMUM",
        "group": "平台设置",
        "label": "视频/音频最大时长",
        "type": "int",
        "default": 480,
        "min": 0,
        "max": 86400,
        "unit": "秒",
        "hint": "超过此时长的视频或音频不会下载媒体文件，但仍会返回标题、作者与封面",
    },
    {
        "key": "DOUYIN_LIVE_PHOTO_ENABLED",
        "group": "平台设置",
        "label": "抖音动态图重建",
        "type": "bool",
        "default": True,
        "hint": "开启后将抖音实况照片与动图重建为单文件动态照片（支持主流手机相册播放）；关闭则仅发静态主图",
    },
    {
        "key": "XHS_CK",
        "group": "平台设置",
        "label": "小红书 Cookie",
        "type": "text",
        "default": "",
        "secret": True,
        "hint": "从浏览器获取 xiaohongshu.com 的 Cookie（可选，填入后可提升高清资源稳定性）",
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
        "hint": "图集较多时按此上限拆成多条合并转发，避免 OneBot 协议端序列化内存过高（仅 aiocqhttp 生效）",
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
        "hint": "按图片原始字节累计计算，超出即拆批；单张超过此值的图片会单独发送",
    },
    # ---------------- B站设置 ---------------- #
    {
        "key": "BILI_CK",
        "group": "B站设置",
        "label": "哔哩哔哩 Cookie",
        "type": "text",
        "default": "",
        "secret": True,
        "hint": "填入 SESSDATA 等完整 Cookie，或直接使用 /bili_login 扫码登录自动加密保存",
    },
    {
        "key": "BILI_QUALITY",
        "group": "B站设置",
        "label": "视频下载清晰度",
        "type": "select",
        "default": "1080P",
        "options": ["360P", "480P", "720P", "1080P", "1080P+", "4K", "8K"],
        "hint": "高画质需要对应账号权限；未登录时最高通常为 720P",
    },
    {
        "key": "BILI_CODEC",
        "group": "B站设置",
        "label": "视频编码格式",
        "type": "select",
        "default": "H264",
        "options": ["H264", "H265", "AV1"],
        "labels": [
            "H.264 (AVC) · 兼容性最好",
            "H.265 (HEVC) · 体积更小",
            "AV1 · 画质最优但部分客户端不兼容",
        ],
        "hint": "QQ / 微信对 AV1 支持较差，推荐优先 H.264；所选编码不可用时自动回退",
    },
    {
        "key": "BILI_COOKIE_MONITOR_ENABLED",
        "group": "B站设置",
        "label": "启用 Cookie 定时监控",
        "type": "bool",
        "default": True,
        "hint": "定期检测 B站 Cookie 有效性，并在服务端回传 Set-Cookie 时自动续期",
    },
    {
        "key": "BILI_COOKIE_CHECK_INTERVAL",
        "group": "B站设置",
        "label": "Cookie 检测间隔",
        "type": "int",
        "default": 3600,
        "min": 60,
        "max": 86400,
        "unit": "秒",
        "hint": "每隔多少秒检查一次 Cookie 有效性（最小 60 秒）",
    },
    # ---------------- Twitter 设置 ---------------- #
    {
        "key": "TWITTER_MEDIA_PROXY_ENABLED",
        "group": "Twitter 设置",
        "label": "启用 Twitter 反代",
        "type": "bool",
        "default": False,
        "hint": "开启后，推文媒体 CDN 与 api.vxtwitter.com 解析接口一并走自定义反代（不可用时回退直连）",
    },
    {
        "key": "TWITTER_MEDIA_PROXY_BASE",
        "group": "Twitter 设置",
        "label": "Twitter 反代地址",
        "type": "string",
        "default": "",
        "placeholder": "https://x-media-proxy.xxx.workers.dev",
        "hint": "Cloudflare Worker 反代根地址，末尾不要带斜杠",
    },
    # ---------------- 解析图片渲染 ---------------- #
    {
        "key": "RENDER_ENABLED",
        "group": "解析图片渲染",
        "label": "启用解析图片渲染",
        "type": "bool",
        "default": True,
        "hint": "开启后将解析结果渲染为分享卡片图片发送；失败时自动回退纯文本",
    },
    {
        "key": "RENDER_STYLE",
        "group": "解析图片渲染",
        "label": "卡片版式样式",
        "type": "select",
        "default": "standard",
        "options": ["standard", "magazine", "immersive", "feed"],
        "labels": [
            "standard · 标准横幅（顶部全宽封面 + 纵向信息流）",
            "magazine · 双栏杂志（封面左置、标题作者右置）",
            "immersive · 沉浸全屏（封面铺满整卡，无图回退标准）",
            "feed · 社交动态（作者优先，媒体内嵌）",
        ],
        "options_from": "styles",
        "hint": "样式清单自动读取 card_render/styles 注册表，新增样式文件后自动出现",
    },
    {
        "key": "RENDER_THEME",
        "group": "解析图片渲染",
        "label": "卡片配色方案",
        "type": "select",
        "default": "dark",
        "options": ["dark", "light"],
        "labels": ["dark 深色", "light 浅色"],
        "hint": "分享卡片图片的深 / 浅双色主题（固定配色的自定义样式会忽略此项）",
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
        "hint": "输出卡片图片像素宽度，建议 720-900",
    },
    {
        "key": "RENDER_COVER_FULL_SIZE",
        "group": "解析图片渲染",
        "label": "封面全尺寸模式",
        "type": "bool",
        "default": False,
        "hint": "开启后不再裁切封面，按封面原始宽高比完整呈现",
    },
    {
        "key": "RENDER_FONT_PATH",
        "group": "解析图片渲染",
        "label": "自定义渲染字体",
        "type": "string",
        "default": "",
        "placeholder": "留空自动探测系统中文字体",
        "hint": "可填写 .ttf / .ttc / .otf 字体路径或所在目录",
    },
    {
        "key": "RENDER_PERSONA_WATERMARK",
        "group": "解析图片渲染",
        "label": "随会话人格署名",
        "type": "bool",
        "default": False,
        "hint": "开启后，卡片右下角水印与纯文本消息头跟随当前会话生效的 AstrBot 人格名称（如「达妮娅解析」）；默认关闭",
    },
    {
        "key": "RENDER_BRAND_NAME",
        "group": "解析图片渲染",
        "label": "自定义解析署名",
        "type": "string",
        "default": "莉卡解析",
        "max_length": 16,
        "placeholder": "莉卡解析",
        "hint": "关闭「随会话人格署名」（或当前会话使用系统默认人格）时卡片右下角与纯文本消息头的署名",
    },
    # ---------------- 网页分享设置 ---------------- #
    {
        "key": "WEBPAGE_FALLBACK_ENABLED",
        "group": "网页分享设置",
        "label": "合并转发转网页",
        "type": "bool",
        "default": True,
        "hint": "非 OneBot 平台（QQ Official / Telegram / Discord 等）将多条内容汇总为临时网页链接发送（需配置 AstrBot callback_api_base）",
    },
    {
        "key": "WEBPAGE_TDOCS_JUMP",
        "group": "网页分享设置",
        "label": "QQ 内腾讯文档外链跳转",
        "type": "bool",
        "default": True,
        "hint": "QQ 系平台经 docs.qq.com 跳转页打开分享链接，避免客户端直接拦截外部 URL",
    },
    # ---------------- 缓存设置 ---------------- #
    {
        "key": "CACHE_TTL_HOURS",
        "group": "缓存设置",
        "label": "缓存过期时间",
        "type": "int",
        "default": 24,
        "min": 0,
        "max": 720,
        "unit": "小时",
        "hint": "缓存文件及分享网页有效期；设为 0 则不自动清理（分享网页到 AstrBot 重启前有效）",
    },
    {
        "key": "CACHE_CLEANUP_INTERVAL_MINUTES",
        "group": "缓存设置",
        "label": "清理检查间隔",
        "type": "int",
        "default": 60,
        "min": 1,
        "max": 1440,
        "unit": "分钟",
        "hint": "后台扫描清理过期缓存的周期（修改后需重载插件生效）",
    },
    # ---------------- Cloudflare 基础设置 ---------------- #
    {
        "key": "CLOUDFLARE_FALLBACK_ENABLED",
        "group": "Cloudflare 基础设置",
        "label": "启用网页截图兜底",
        "type": "bool",
        "default": False,
        "hint": "当消息里的链接未匹配任何平台适配器时，调用 Cloudflare Browser Rendering 截图发送",
    },
    {
        "key": "CLOUDFLARE_ACCOUNT_ID",
        "group": "Cloudflare 基础设置",
        "label": "Cloudflare 账号 ID",
        "type": "string",
        "default": "",
        "hint": "Cloudflare Dashboard 中的 Account ID（需开通 Browser Rendering）",
    },
    {
        "key": "CLOUDFLARE_API_TOKEN",
        "group": "Cloudflare 基础设置",
        "label": "Cloudflare API Token",
        "type": "string",
        "default": "",
        "secret": True,
        "hint": "需具备 Browser Rendering - Edit 权限",
    },
    {
        "key": "CLOUDFLARE_TIMEOUT",
        "group": "Cloudflare 基础设置",
        "label": "API 请求超时",
        "type": "int",
        "default": 60,
        "min": 1,
        "max": 600,
        "unit": "秒",
        "hint": "Cloudflare 渲染接口 HTTP 超时，建议 30-120 秒",
    },
    {
        "key": "CLOUDFLARE_CACHE_TTL",
        "group": "Cloudflare 基础设置",
        "label": "截图云端缓存",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 86400,
        "unit": "秒",
        "hint": "0 表示每次实时渲染；设正值可在 TTL 内复用同 URL 截图以节省额度",
    },
    {
        "key": "CLOUDFLARE_BLACKLIST",
        "group": "Cloudflare 基础设置",
        "label": "截图黑名单",
        "type": "list",
        "default": [],
        "hint": "每行一条，支持域名（含子域）、通配符（*.example.com）或无点关键词",
    },
    # ---------------- Cloudflare 截图设置（高阶参数） ---------------- #
    {
        "key": "CLOUDFLARE_VIEWPORT_WIDTH",
        "group": "Cloudflare 截图设置",
        "label": "视窗宽度",
        "type": "int",
        "default": 1280,
        "min": 320,
        "max": 3840,
        "unit": "px",
        "tier": "advanced",
        "hint": "无头浏览器渲染视窗宽度",
    },
    {
        "key": "CLOUDFLARE_VIEWPORT_HEIGHT",
        "group": "Cloudflare 截图设置",
        "label": "视窗高度",
        "type": "int",
        "default": 720,
        "min": 320,
        "max": 4320,
        "unit": "px",
        "tier": "advanced",
        "hint": "无头浏览器渲染视窗高度",
    },
    {
        "key": "CLOUDFLARE_WAIT_UNTIL",
        "group": "Cloudflare 截图设置",
        "label": "页面加载等待策略",
        "type": "select",
        "default": "networkidle0",
        "options": ["load", "domcontentloaded", "networkidle0", "networkidle2"],
        "tier": "advanced",
        "hint": "SPA / 动态页面建议 networkidle0 或 networkidle2；追求速度可选 load",
    },
    {
        "key": "CLOUDFLARE_GOTO_TIMEOUT",
        "group": "Cloudflare 截图设置",
        "label": "页面导航超时",
        "type": "int",
        "default": 45000,
        "min": 5000,
        "max": 120000,
        "unit": "毫秒",
        "tier": "advanced",
        "hint": "页面跳转等待超时，官方推荐 45000ms",
    },
    {
        "key": "CLOUDFLARE_FULL_PAGE",
        "group": "Cloudflare 截图设置",
        "label": "整页长图模式",
        "type": "bool",
        "default": False,
        "tier": "advanced",
        "hint": "开启后截取完整滚动页面，关闭则只截取首屏视窗",
    },
    {
        "key": "CLOUDFLARE_DEVICE_SCALE_FACTOR",
        "group": "Cloudflare 截图设置",
        "label": "清晰度倍率 (DPR)",
        "type": "float",
        "default": 1,
        "min": 1,
        "max": 3,
        "unit": "倍",
        "tier": "advanced",
        "hint": "deviceScaleFactor，建议 1-2；调高可提升文字锐度",
    },
    {
        "key": "CLOUDFLARE_SCREENSHOT_TYPE",
        "group": "Cloudflare 截图设置",
        "label": "截图格式",
        "type": "select",
        "default": "png",
        "options": ["png", "jpeg"],
        "tier": "advanced",
        "hint": "png 支持透明底；jpeg 体积更小",
    },
    {
        "key": "CLOUDFLARE_SCREENSHOT_QUALITY",
        "group": "Cloudflare 截图设置",
        "label": "JPEG 压缩质量",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 100,
        "tier": "advanced",
        "hint": "仅 jpeg 有效（0-100），0 表示由 Cloudflare 默认",
    },
    {
        "key": "CLOUDFLARE_OMIT_BACKGROUND",
        "group": "Cloudflare 截图设置",
        "label": "隐藏白色默认背景",
        "type": "bool",
        "default": False,
        "tier": "advanced",
        "hint": "仅 png 格式生效，适合透明背景卡片页",
    },
    {
        "key": "CLOUDFLARE_SELECTOR",
        "group": "Cloudflare 截图设置",
        "label": "指定元素选择器",
        "type": "string",
        "default": "",
        "placeholder": "#main-content",
        "tier": "advanced",
        "hint": "仅截取匹配的 CSS 元素区域，留空截整页",
    },
    {
        "key": "CLOUDFLARE_WAIT_FOR_SELECTOR",
        "group": "Cloudflare 截图设置",
        "label": "等待元素出现",
        "type": "string",
        "default": "",
        "placeholder": ".article-body",
        "tier": "advanced",
        "hint": "等待该 CSS 选择器渲染完成再截图",
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
        "tier": "advanced",
        "hint": "配合「等待元素出现」使用，0 表示默认",
    },
    {
        "key": "CLOUDFLARE_USER_AGENT",
        "group": "Cloudflare 截图设置",
        "label": "自定义 User-Agent",
        "type": "string",
        "default": "",
        "tier": "advanced",
        "hint": "留空使用 Cloudflare 默认浏览器 UA",
    },
    {
        "key": "CLOUDFLARE_EXTRA_HEADERS",
        "group": "Cloudflare 截图设置",
        "label": "附加请求头 (JSON)",
        "type": "text",
        "default": "",
        "tier": "advanced",
        "hint": 'JSON 对象格式，例如 {"Authorization":"Bearer xxx"}',
    },
    {
        "key": "CLOUDFLARE_COOKIES",
        "group": "Cloudflare 截图设置",
        "label": "附加 Cookie (JSON)",
        "type": "text",
        "default": "",
        "tier": "advanced",
        "hint": 'JSON 数组格式，例如 [{"name":"session","value":"xxx","domain":"example.com","path":"/"}]',
    },
    # ---------------- 调试设置 ---------------- #
    {
        "key": "DEBUG_LOG_ENABLED",
        "group": "调试设置",
        "label": "记录详细错误日志",
        "type": "bool",
        "default": True,
        "hint": "关闭后，下载失败等场景不再输出完整异常堆栈",
    },
    {
        "key": "SEND_ERROR_MESSAGES",
        "group": "调试设置",
        "label": "向会话回显错误提示",
        "type": "bool",
        "default": False,
        "hint": "开启后解析失败会回复报错提示；关闭则保持静默，仅记录插件日志",
    },
    # ---------------- 外观设置 ---------------- #
    {
        "key": "WEBUI_THEME",
        "group": "外观设置",
        "label": "网页主题布局",
        "type": "string",
        "default": "studio",
        "control": CONTROL_THEME,
        "pattern": r"^[a-z][a-z0-9_-]*$",
        "hint": "决定控制面板的整体布局与视觉体系（内置工作台分栏 / 悬浮控制中心，可通过扩展接口新增）",
    },
    {
        "key": "WEBUI_COLOR_MODE",
        "group": "外观设置",
        "label": "网页明暗模式",
        "type": "select",
        "default": "auto",
        "options": ["auto", "light", "dark"],
        "labels": [
            "跟随 AstrBot 面板",
            "浅色模式 (Light)",
            "深色模式 (Dark)",
        ],
        "hint": "默认跟随 AstrBot Dashboard 的深浅模式实时切换，也可在此强制指定",
    },
)

_ITEM_BY_KEY: dict[str, dict[str, Any]] = {item["key"]: item for item in CONFIG_META}

CONFIG_GROUP_KEYS: dict[str, tuple[str, ...]] = {
    group: tuple(item["key"] for item in CONFIG_META if item["group"] == group)
    for group, _, _ in CONFIG_GROUPS
}

_KEY_GROUP_MAP: dict[str, str] = {
    key: group for group, keys in CONFIG_GROUP_KEYS.items() for key in keys
}


def registered_styles() -> list[tuple[str, str]]:
    """从卡片样式注册表读取 ``(样式名, 展示文案)`` 列表。"""
    try:
        from ..services.card_render.styles import iter_styles
    except Exception:  # noqa: BLE001 - 注册表不可用不该拖垮配置页
        from astrbot.api import logger

        logger.warning(
            "[link_parser] 读取卡片样式注册表失败，使用内置样式清单", exc_info=True
        )
        return list(_BUILTIN_STYLE_OPTIONS)

    pairs = [(spec.name, spec.label) for spec in iter_styles()]
    return pairs or list(_BUILTIN_STYLE_OPTIONS)


def _effective_options(item: dict[str, Any]) -> list[str]:
    if item.get("options_from") == "styles":
        names = [name for name, _ in registered_styles()]
        if names:
            return names
    return list(item.get("options") or [])


def _dynamic_item(item: dict[str, Any]) -> dict[str, Any]:
    result = dict(item)
    if item.get("options_from") == "styles":
        pairs = registered_styles()
        if pairs:
            result["options"] = [name for name, _ in pairs]
            result["labels"] = [label for _, label in pairs]
    return result


def config_meta_payload() -> dict[str, Any]:
    """返回供 WebUI 渲染的配置元数据（分类分组 + 全部配置项定义）。"""
    return {
        "groups": [
            {
                "name": name,
                "description": description,
                "category": category,
                "keys": list(CONFIG_GROUP_KEYS.get(name, ())),
            }
            for name, description, category in CONFIG_GROUPS
        ],
        "items": [_dynamic_item(item) for item in CONFIG_META],
    }


def coerce_value(item: dict[str, Any], raw: Any) -> tuple[Any, str | None]:
    """把 WebUI 提交的值转为目标类型并校验范围。"""
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
        rows = raw if isinstance(raw, list) else str(raw or "").splitlines()
        values: list[str] = []
        for row in rows:
            text = str(row).strip()
            if not text:
                continue
            for part in text.split(","):
                part = part.strip()
                if part and part not in values:
                    values.append(part)
        return values, None

    text = "" if raw is None else str(raw).strip()

    if kind == "select":
        options = _effective_options(item)
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
        return None, f"{label}：格式不正确"
    return text, None


def verify_schema_alignment(schema: dict[str, Any]) -> list[str]:
    """校验 ``_conf_schema.json`` 与 :data:`CONFIG_META` 的键、分组及可见性一致性。"""
    schema_keys: set[str] = set()
    schema_group_of: dict[str, str] = {}
    problems: list[str] = []

    for group, node in schema.items():
        if not isinstance(node, dict) or not isinstance(node.get("items"), dict):
            problems.append(f"schema 顶层存在非分组条目：{group}")
            continue
        for key in node["items"]:
            schema_keys.add(key)
            schema_group_of[key] = group
        if group not in CONFIG_GROUP_KEYS:
            problems.append(f"schema 里存在 CONFIG_GROUPS 未声明的分组：{group}")

        has_visible = any(
            isinstance(item, dict) and item.get("invisible") is not True
            for item in node["items"].values()
        )
        if has_visible == (node.get("invisible") is True):
            problems.append(
                f"{group} 分组可见性与内部条目不一致（全隐藏时分组本身也必须 invisible: true）"
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


def registered_platforms() -> list[dict[str, str]]:
    """从适配器注册表读取平台元数据列表（name / label / description）。"""
    try:
        from ..adapters import iter_adapters
    except Exception:  # noqa: BLE001
        from astrbot.api import logger

        logger.warning("[link_parser] 读取适配器注册表失败，解析器开关不可用", exc_info=True)
        return []

    items: list[dict[str, str]] = []
    for spec in iter_adapters():
        try:
            label = spec.display_name
        except Exception:  # noqa: BLE001
            label = spec.name
        items.append(
            {
                "name": spec.name,
                "label": label or spec.name,
                "description": spec.description or "",
                "external": spec.priority >= 100 and getattr(spec.parser_cls, "__module__", "").endswith("external"),
            }
        )
    return items


def platform_options(pconfig: "ParserConfig") -> list[dict[str, Any]]:
    """供 WebUI 使用的解析器开关清单（含启用状态与能力说明）。"""
    disabled = set(pconfig.DISABLED_PLATFORMS)
    return [
        {
            "name": item["name"],
            "label": item["label"],
            "description": item["description"],
            "external": item["external"],
            "enabled": item["name"] not in disabled,
        }
        for item in registered_platforms()
    ]


__all__ = [
    "CONFIG_GROUPS",
    "CONFIG_GROUP_KEYS",
    "CONFIG_META",
    "CONTROL_PLATFORMS",
    "CONTROL_THEME",
    "_ITEM_BY_KEY",
    "_KEY_GROUP_MAP",
    "coerce_value",
    "config_meta_payload",
    "platform_options",
    "registered_platforms",
    "registered_styles",
    "verify_schema_alignment",
]
