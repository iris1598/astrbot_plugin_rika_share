"""JSON 分享卡片处理。

QQ 等平台会把分享内容封装为 JSON 消息组件（卡片），其中可能藏有真实链接。
本模块负责识别 JSON 组件并从中抽取链接，再交给对应的平台适配器解析。
"""

import json

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
import astrbot.api.message_components as Comp

from ..constants import GENERIC_URL_PATTERN


class EventUrlWrapper:
    """把单个 URL 包装成事件，复用基于 ``event.message_str`` 的解析流程。"""

    def __init__(self, event: AstrMessageEvent, url: str):
        self._event = event
        self.message_str = url

    def __getattr__(self, name):
        return getattr(self._event, name)


def has_json_component(event: AstrMessageEvent) -> bool:
    """事件消息链中是否包含 JSON 卡片组件（reply 引用除外）。"""
    if not hasattr(event, "message_obj") or not hasattr(event.message_obj, "message"):
        return False
    for c in event.message_obj.message:
        if isinstance(c, dict):
            t = c.get("type")
            if t == "reply":
                continue
            if t and "json" in str(t).lower():
                return True
            continue
        if isinstance(c, Comp.Json):
            return True
        t = getattr(c, "type", None)
        if t and "json" in str(t).lower():
            return True
    return False


def extract_links_from_text(text: str) -> list[str]:
    """从纯文本中提取全部 http(s) 链接。"""
    if not text:
        return []
    return GENERIC_URL_PATTERN.findall(text)


def extract_links_from_event(event: AstrMessageEvent) -> list[str]:
    """从事件的消息链（JSON 卡片 / 文本）与纯文本内容中提取链接。"""
    links: list[str] = []
    if hasattr(event, "message_obj") and hasattr(event.message_obj, "message"):
        for c in event.message_obj.message:
            if isinstance(c, dict):
                t = c.get("type")
                if t == "reply":
                    continue
                if t and "json" in str(t).lower():
                    links.extend(extract_links_from_json(c.get("data", c)))
                continue
            if isinstance(c, Comp.Json):
                links.extend(extract_links_from_json(c.data))
            elif isinstance(c, Comp.Plain):
                links.extend(extract_links_from_text(c.text))
    links.extend(extract_links_from_text(event.message_str))
    return links


def extract_links_from_json(data) -> list[str]:
    """递归遍历 JSON 卡片结构，收集其中出现的链接。"""
    links: list[str] = []
    try:
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return links

        def search(obj):
            found = []
            if isinstance(obj, dict):
                for v in obj.values():
                    if isinstance(v, str) and (v.startswith("http://") or v.startswith("https://")):
                        found.append(v)
                    elif isinstance(v, (dict, list)):
                        found.extend(search(v))
                meta = obj.get("meta", {})
                if isinstance(meta, dict):
                    for dk in ("detail_1", "detail", "news", "music"):
                        d = meta.get(dk, {})
                        if isinstance(d, dict):
                            for uk in ("qqdocurl", "url", "jumpUrl"):
                                v = d.get(uk, "")
                                if isinstance(v, str) and v:
                                    found.append(v)
            elif isinstance(obj, list):
                for item in obj:
                    if isinstance(item, (dict, list)):
                        found.extend(search(item))
            return found

        links.extend(search(data))
    except Exception as e:
        logger.warning(f"解析 JSON 消息组件失败: {e}")
    return links


__all__ = [
    "EventUrlWrapper",
    "extract_links_from_event",
    "extract_links_from_json",
    "extract_links_from_text",
    "has_json_component",
]
