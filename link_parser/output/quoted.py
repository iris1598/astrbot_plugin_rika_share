"""引用（回复）消息的内容提取。

聊天里「引用一条消息 + 回复『下载封面』」时，需要拿到**被引用消息**的文本与链接。
两种取法，按优先级：

1. 框架自带的引用消息解析器（``astrbot.core.utils.quoted_message``，较新版本才有）：
   它能处理 OneBot 只回传 reply id 的情况——按 id 反查原消息，连合并转发都会展开。
2. 回退：直接读 ``Reply`` 组件自带的 ``message_str`` / ``chain``。AstrBot 打开
   「获取引用消息」时，OneBot 适配器已经把原消息内容塞进组件里了。

老版本 AstrBot 没有第 1 种，第 2 种也能覆盖大部分场景，所以导入失败不算错误。
"""

from __future__ import annotations

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
import astrbot.api.message_components as Comp

from .json_card import extract_links_from_json, extract_links_from_text

__all__ = [
    "find_reply_component",
    "quoted_links",
    "quoted_text",
]


def _iter_components(event: AstrMessageEvent):
    message_obj = getattr(event, "message_obj", None)
    for comp in getattr(message_obj, "message", None) or []:
        yield comp


def find_reply_component(event: AstrMessageEvent) -> Comp.Reply | None:
    """取事件消息链里的引用段（没有引用时返回 ``None``）。"""
    for comp in _iter_components(event):
        if isinstance(comp, Comp.Reply):
            return comp
        # 部分适配器把消息段留成原始 dict
        if isinstance(comp, dict) and comp.get("type") == "reply":
            try:
                return Comp.Reply(**(comp.get("data") or {}))
            except Exception:
                return None
    return None


def _text_from_chain(chain) -> str:
    """引用段自带的原消息链 → 纯文本（只取文本段）。"""
    parts: list[str] = []
    for comp in chain or []:
        if isinstance(comp, Comp.Plain):
            parts.append(comp.text)
        elif isinstance(comp, dict):
            data = comp.get("data") or {}
            if comp.get("type") == "text" and isinstance(data.get("text"), str):
                parts.append(data["text"])
    return "\n".join(p for p in parts if p)


def _embedded_text(event: AstrMessageEvent) -> str | None:
    """引用段里**已经带着**的原消息文本（不发起远程请求）。"""
    reply = find_reply_component(event)
    if reply is None:
        return None
    text = (getattr(reply, "message_str", None) or "").strip()
    if text:
        return text
    return _text_from_chain(getattr(reply, "chain", None)).strip() or None


async def _framework_quoted_text(event: AstrMessageEvent) -> str | None:
    """用框架的引用消息解析器取原消息文本（能按 reply id 反查）。"""
    try:
        from astrbot.core.utils.quoted_message import extract_quoted_message_text
    except Exception:  # 老版本 AstrBot 没有这个模块
        return None
    try:
        return await extract_quoted_message_text(event)
    except Exception:
        logger.debug("引用消息内容解析失败，回退到 Reply 组件", exc_info=True)
        return None


async def quoted_text(event: AstrMessageEvent) -> str | None:
    """被引用消息的纯文本；没有引用或取不到时返回 ``None``。"""
    return await _framework_quoted_text(event) or _embedded_text(event)


def quoted_links(event: AstrMessageEvent, text: str | None) -> list[str]:
    """被引用消息里的链接：先看文本，再翻引用段里的 JSON 分享卡片。

    返回值未做尾部标点清理，由调用方按需处理（与 ``json_card`` 的口径一致）。
    """
    links = extract_links_from_text(text or "")
    reply = find_reply_component(event)
    for comp in (getattr(reply, "chain", None) or []) if reply is not None else []:
        if isinstance(comp, Comp.Json):
            links.extend(extract_links_from_json(comp.data))
        elif isinstance(comp, dict) and comp.get("type") == "json":
            links.extend(extract_links_from_json(comp.get("data")))
    return list(dict.fromkeys(links))
