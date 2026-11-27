"""输出节点注册表与按内容模式（视频 / 图文 / 动态）的默认规则。"""

from __future__ import annotations

import copy
import json
from typing import Any

#: 三种内容形态：(mode_id, 展示标题, 触发说明)
NODE_MODES: tuple[tuple[str, str, str], ...] = (
    ("video", "视频模式", "含真实视频本体的链接（B站视频/番剧、抖音视频、快手/微博/X 视频等）"),
    ("gallery", "图文模式", "含图集、Opus、实况静态图或动图的链接（小红书、B站动态、微博多图、NGA 等）"),
    ("dynamic", "动态 / 文章模式", "无图纯文动态、GitHub 仓库卡、音频及外部网易云联动等"),
)

NODE_MODE_IDS: tuple[str, ...] = tuple(m[0] for m in NODE_MODES)

#: 全部标准化输出节点目录（单源描述节点身份、排序默认与能力边界）
NODE_CATALOG: dict[str, dict[str, Any]] = {
    "card": {
        "id": "card",
        "label": "解析卡片图",
        "description": "Pillow 渲染的高清分享卡片大图（关闭 RENDER_ENABLED 时自动跳过）",
        "modes": ("video", "gallery", "dynamic"),
        "supports_merge": True,
        "merge_note": "",
    },
    "header": {
        "id": "header",
        "label": "署名标题头",
        "description": "平台与内容类型标题行（如：莉卡解析 | 哔哩哔哩 - 视频）",
        "modes": ("video", "gallery", "dynamic"),
        "supports_merge": True,
        "merge_note": "",
    },
    "author": {
        "id": "author",
        "label": "作者信息",
        "description": "发布者昵称、个人签名与头像（无作者信息时自动跳过）",
        "modes": ("video", "gallery", "dynamic"),
        "supports_merge": True,
        "merge_note": "",
    },
    "title_url": {
        "id": "title_url",
        "label": "标题与原文链接",
        "description": "内容主标题及规范化原网页链接",
        "modes": ("video", "gallery", "dynamic"),
        "supports_merge": True,
        "merge_note": "",
    },
    "cover": {
        "id": "cover",
        "label": "视频 / 直播封面",
        "description": "视频封面或直播间封面大图（非图集正图）",
        "modes": ("video", "dynamic"),
        "supports_merge": True,
        "merge_note": "",
    },
    "text": {
        "id": "text",
        "label": "正文与简介",
        "description": "动态正文、视频简介、标签及图文混排文字段",
        "modes": ("video", "gallery", "dynamic"),
        "supports_merge": True,
        "merge_note": "",
    },
    "meta": {
        "id": "meta",
        "label": "统计与元信息",
        "description": "时长、播放/点赞数据、在线人数、GitHub 仓库数据及限流提醒",
        "modes": ("video", "gallery", "dynamic"),
        "supports_merge": True,
        "merge_note": "",
    },
    "images": {
        "id": "images",
        "label": "正文图集 / 动图",
        "description": "图文正图、小红书/酷安多图、抖音实况静态图与 GIF 动图（合并时按体积预算拆批）",
        "modes": ("video", "gallery"),
        "supports_merge": True,
        "merge_note": "",
    },
    "repost": {
        "id": "repost",
        "label": "转发 / 引用原文",
        "description": "嵌套的被转发/引用原帖作者、标题、正文与附图",
        "modes": ("video", "gallery", "dynamic"),
        "supports_merge": True,
        "merge_note": "",
    },
    "video": {
        "id": "video",
        "label": "视频文件",
        "description": "真实视频文件本体；OneBot 下支持放进合并转发（非 OneBot 平台自动保持独立发送）",
        "modes": ("video",),
        "supports_merge": True,
        "merge_note": "OneBot 下支持放入合并转发；建议在 AstrBot 配置 callback_api_base 以兼容跨容器协议端",
    },
    "audio": {
        "id": "audio",
        "label": "语音 / 音频文件",
        "description": "独立语音条或音频文件（不含下方音乐卡片）",
        "modes": ("video", "gallery", "dynamic"),
        "supports_merge": True,
        "merge_note": "语音支持放入 OneBot 合并转发；以文件形态（Discord / send_as_file）发送时固定单独发送",
    },
    "music_card": {
        "id": "music_card",
        "label": "音乐卡片（外部联动）",
        "description": "网易云联动插件开启音乐卡片时发出的 QQ 音乐卡片，启用后会替代同条语音避免重复",
        "modes": ("dynamic",),
        "supports_merge": False,
        "merge_note": "QQ 音乐卡片受协议组件限制，不支持放入合并转发，启用后将按排列顺序独立发送",
    },
}

#: 各模式默认规则（严格保持与既有默认发送形态一致）
_DEFAULT_NODE_RULES: dict[str, list[dict[str, Any]]] = {
    "video": [
        {"id": "card", "enabled": True, "merge": False},
        {"id": "header", "enabled": False, "merge": True},
        {"id": "author", "enabled": False, "merge": True},
        {"id": "title_url", "enabled": False, "merge": True},
        {"id": "cover", "enabled": False, "merge": True},
        {"id": "text", "enabled": False, "merge": True},
        {"id": "meta", "enabled": False, "merge": True},
        {"id": "images", "enabled": False, "merge": True},
        {"id": "repost", "enabled": False, "merge": True},
        {"id": "video", "enabled": True, "merge": False},
        {"id": "audio", "enabled": False, "merge": False},
    ],
    "gallery": [
        {"id": "card", "enabled": True, "merge": False},
        {"id": "header", "enabled": True, "merge": True},
        {"id": "author", "enabled": False, "merge": True},
        {"id": "title_url", "enabled": True, "merge": True},
        {"id": "text", "enabled": True, "merge": True},
        {"id": "meta", "enabled": True, "merge": True},
        {"id": "images", "enabled": True, "merge": True},
        {"id": "repost", "enabled": False, "merge": True},
        {"id": "audio", "enabled": True, "merge": False},
    ],
    "dynamic": [
        {"id": "card", "enabled": True, "merge": False},
        {"id": "header", "enabled": True, "merge": True},
        {"id": "author", "enabled": False, "merge": True},
        {"id": "title_url", "enabled": True, "merge": True},
        {"id": "cover", "enabled": True, "merge": True},
        {"id": "text", "enabled": True, "merge": True},
        {"id": "meta", "enabled": True, "merge": True},
        {"id": "repost", "enabled": False, "merge": True},
        {"id": "audio", "enabled": True, "merge": False},
        {"id": "music_card", "enabled": True, "merge": False},
    ],
}


def default_node_rules() -> dict[str, list[dict[str, Any]]]:
    """返回三模式默认节点规则的深拷贝。"""
    return copy.deepcopy(_DEFAULT_NODE_RULES)


def _normalize_mode_items(mode: str, raw_list: Any) -> list[dict[str, Any]]:
    defaults = _DEFAULT_NODE_RULES[mode]
    default_by_id = {row["id"]: row for row in defaults}
    allowed_ids = set(default_by_id)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    if isinstance(raw_list, list):
        for entry in raw_list:
            if not isinstance(entry, dict):
                continue
            nid = str(entry.get("id") or "").strip()
            if nid not in allowed_ids or nid in seen:
                continue
            seen.add(nid)
            meta = NODE_CATALOG[nid]
            base = default_by_id[nid]
            enabled = bool(entry.get("enabled", base["enabled"]))
            merge = bool(entry.get("merge", base["merge"])) if meta["supports_merge"] else False
            out.append({"id": nid, "enabled": enabled, "merge": merge})

    for row in defaults:
        if row["id"] not in seen:
            out.append(dict(row))
    return out


def normalize_node_rules(raw: Any) -> dict[str, list[dict[str, Any]]]:
    """将字符串 / 字典 / 空值归一化为完整三模式节点规则字典。"""
    if raw is None or raw == "":
        return default_node_rules()

    data: Any = raw
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return default_node_rules()
        try:
            data = json.loads(stripped)
        except Exception:
            return default_node_rules()

    if not isinstance(data, dict):
        return default_node_rules()

    return {mode: _normalize_mode_items(mode, data.get(mode)) for mode in NODE_MODE_IDS}


def coerce_node_rules(raw: Any) -> tuple[str, str | None]:
    """校验并序列化节点规则；与系统默认完全一致时返回空串以便稀疏保存。"""
    if raw is None or raw == "":
        return "", None

    parsed: Any = raw
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return "", None
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            return "", f"解析输出节点规则：JSON 格式无效（{exc.msg}）"

    if not isinstance(parsed, dict):
        return "", "解析输出节点规则：必须是 JSON 对象"

    normalized = normalize_node_rules(parsed)
    if normalized == _DEFAULT_NODE_RULES:
        return "", None

    encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > 8000:
        return "", "解析输出节点规则：配置内容过长"
    return encoded, None


def detect_content_mode(result: Any) -> str:
    """根据 :class:`ParseResult` 实际内容自动归类为 ``video`` / ``gallery`` / ``dynamic``。

    例外：外部解析器声明 ``extra["music_card"]``（网易云联动歌曲）时恒归 ``dynamic``
    —— ``music_card`` 输出节点只存在于 dynamic 模式，而歌曲封面会以 ``ImageContent``
    挂进 ``graphics`` 供卡片渲染，仅按内容推断会被误归 ``gallery``。
    """
    from ..models import ImageContent, VideoContent

    # 显式声明优先于内容推断（详见上方 docstring 的例外说明）
    if getattr(result, "extra", None) and result.extra.get("music_card"):
        return "dynamic"

    contents = getattr(result, "contents", ()) or ()
    graphics = getattr(result, "graphics", ()) or ()

    if any(isinstance(c, VideoContent) and not c.is_image_like for c in contents):
        return "video"
    if any(isinstance(g, ImageContent) for g in graphics) or any(
        isinstance(c, ImageContent) or (isinstance(c, VideoContent) and c.is_image_like)
        for c in contents
    ):
        return "gallery"
    return "dynamic"


def node_schema_payload() -> dict[str, Any]:
    """供 WebUI 节点编排器渲染的元数据清单。"""
    return {
        "modes": [
            {"id": mode_id, "label": label, "description": desc}
            for mode_id, label, desc in NODE_MODES
        ],
        "catalog": {
            nid: {
                "id": info["id"],
                "label": info["label"],
                "description": info["description"],
                "modes": list(info["modes"]),
                "supports_merge": info["supports_merge"],
                "merge_note": info["merge_note"],
            }
            for nid, info in NODE_CATALOG.items()
        },
        "defaults": default_node_rules(),
    }


__all__ = [
    "NODE_CATALOG",
    "NODE_MODES",
    "NODE_MODE_IDS",
    "coerce_node_rules",
    "default_node_rules",
    "detect_content_mode",
    "node_schema_payload",
    "normalize_node_rules",
]
