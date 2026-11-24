"""会话生效人格署名解析工具。"""

from __future__ import annotations

from typing import Any

from astrbot.api import logger

DEFAULT_BRAND_NAME = "莉卡解析"

#: AstrBot 保留的占位人格 ID，不应拼成人格署名
_PLACEHOLDER_PERSONA_IDS = frozenset({
    "default",
    "[%none]",
    "_chatui_default_",
    "none",
})


def format_brand_name(
    persona_name: str | None,
    *,
    default: str = DEFAULT_BRAND_NAME,
) -> str:
    """将人格名称格式化为署名文案（如 ``达妮娅`` -> ``达妮娅解析``）。"""
    text = " ".join(str(persona_name or "").split()).strip()
    if not text or text.lower() in _PLACEHOLDER_PERSONA_IDS:
        return default
    if text.endswith("解析"):
        return text[:16]
    if len(text) > 12:
        text = text[:12]
    return f"{text}解析"


async def resolve_brand_name(
    context: Any,
    event: Any,
    *,
    enabled: bool,
    default: str = DEFAULT_BRAND_NAME,
) -> str:
    """按 AstrBot 会话与人格优先级解析当前消息应使用的署名。"""
    if not enabled or context is None or event is None:
        return default

    persona_mgr = getattr(context, "persona_manager", None)
    resolve_fn = getattr(persona_mgr, "resolve_selected_persona", None)
    if not callable(resolve_fn):
        return default

    umo = getattr(event, "unified_msg_origin", None)
    if not umo:
        return default

    conv_persona_id: str | None = None
    conv_mgr = getattr(context, "conversation_manager", None)
    if conv_mgr is not None:
        try:
            get_cid = getattr(conv_mgr, "get_curr_conversation_id", None)
            get_conv = getattr(conv_mgr, "get_conversation", None)
            if callable(get_cid) and callable(get_conv):
                curr_cid = await get_cid(umo)
                if curr_cid:
                    conv = await get_conv(umo, curr_cid)
                    conv_persona_id = getattr(conv, "persona_id", None)
        except Exception:
            logger.debug("[link_parser] 读取当前对话人格失败，回退默认人格查找", exc_info=True)

    platform_name = ""
    get_plat = getattr(event, "get_platform_name", None)
    if callable(get_plat):
        try:
            platform_name = str(get_plat() or "")
        except Exception:
            platform_name = ""

    try:
        resolved = await resolve_fn(
            umo=umo,
            conversation_persona_id=conv_persona_id,
            platform_name=platform_name,
        )
        persona_id = resolved[0] if isinstance(resolved, tuple) and len(resolved) >= 1 else None
        persona_obj = resolved[1] if isinstance(resolved, tuple) and len(resolved) >= 2 else None
        raw_name: str | None = None
        if isinstance(persona_obj, dict):
            raw_name = persona_obj.get("name")
        elif persona_obj is not None:
            raw_name = getattr(persona_obj, "name", None)
        return format_brand_name(raw_name or persona_id, default=default)
    except Exception:
        logger.debug("[link_parser] 解析会话人格失败，使用默认署名", exc_info=True)
        return default
