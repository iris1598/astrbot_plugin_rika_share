"""解析结果 → 消息链的输出规划与构建。

支持：
- 按视频 / 图文 / 动态三模式节点规则（启用开关 / 排序 / 是否放入合并转发）
  组装有序发送段（:func:`plan_output_segments`）；
- OneBot v11 合并转发按节点数 / 体积预算拆批（:func:`send_nodes_batched`）；
- 非 OneBot 平台纯文本 + 图片回退链（:func:`send_plain_output`）与媒体独立发送。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
import astrbot.api.message_components as Comp

from ..config import get_config
from ..config.nodes import (
    NODE_CATALOG,
    default_node_rules,
    detect_content_mode,
    normalize_node_rules,
)
from ..models import AudioContent, ImageContent, ParseResult, VideoContent
from ..utils.persona import DEFAULT_BRAND_NAME

__all__ = [
    "build_header_text",
    "build_platform_output",
    "plan_output_segments",
    "send_nodes_batched",
    "send_plain_output",
    "try_send_media",
]

_TEXT_LIMITS: dict[str, int] = {
    "bilibili": 200,
    "xiaohongshu": 300,
    "kuaishou": 100,
    "coolapk": 500,
}

_SUPPRESSIBLE_TEXT_NODES: frozenset[str] = frozenset({
    "header",
    "author",
    "title_url",
    "cover",
    "text",
    "meta",
    "images",
    "repost",
})

_FALLBACK_TEXT_NODES: frozenset[str] = frozenset({
    "header",
    "title_url",
    "cover",
    "text",
    "meta",
    "repost",
})


def _is_video_candidate(cont: Any) -> bool:
    """是否为「真视频」（排除已重建为图片类产物的动图 / 动态照片）。"""
    return isinstance(cont, VideoContent) and not cont.is_image_like


async def resolve_still_path(cont: VideoContent) -> Path | None:
    """图片类产物路径：动态照片(.jpg，抖音) / 动图(.gif，Twitter)；
    普通视频或产物缺失时返回 None。"""
    if not cont.is_image_like:
        return None
    task = cont.still_path
    if task is None:
        return None
    return await task.safe_get()


def build_header_text(
    result: ParseResult,
    platform: str,
    *,
    brand_name: str = DEFAULT_BRAND_NAME,
) -> str:
    """构造与各平台一致的署名标题头文案。"""
    platform_name = result.platform.display_name
    content_type = result.extra.get("content_type", "动态")
    brand = (brand_name or DEFAULT_BRAND_NAME).strip() or DEFAULT_BRAND_NAME

    if platform == "xiaohongshu":
        kind = "视频" if result.extra.get("is_video") else "图文"
        return f"{brand} | {platform_name} - {kind}"

    if platform == "douyin":
        is_video = not result.img_contents and any(
            _is_video_candidate(c) for c in result.contents
        )
        has_live_photo = any(
            isinstance(c, VideoContent) and c.is_live_photo for c in result.contents
        )
        has_animated = any(
            isinstance(c, VideoContent) and c.is_image_like and not c.is_live_photo
            for c in result.contents
        )
        if is_video:
            kind = "视频"
        elif has_live_photo:
            kind = "实况"
        elif has_animated:
            kind = "动图"
        else:
            kind = "图文"
        return f"{brand} | {platform_name} - {kind}"

    if platform == "kuaishou":
        is_video = any(isinstance(c, VideoContent) for c in result.contents)
        return f"{brand} | {platform_name} - {'视频' if is_video else '图文'}"

    return f"{brand} | {platform_name} - {content_type}"


async def _collect_images_for(result: ParseResult) -> list[list]:
    """收集 ``graphics`` 中的图片以及 ``contents`` 中的图片/动图/实况静态图。"""
    items: list[list] = []
    for g in result.graphics:
        if isinstance(g, ImageContent):
            path = await g.path_task.safe_get()
            if path:
                items.append([Comp.Image.fromFileSystem(str(path))])
    for c in result.contents:
        if isinstance(c, ImageContent):
            path = await c.path_task.safe_get()
            if path:
                items.append([Comp.Image.fromFileSystem(str(path))])
        elif isinstance(c, VideoContent):
            still_path = await resolve_still_path(c)
            if still_path is not None:
                items.append([Comp.Image.fromFileSystem(str(still_path))])
    return items


async def _extract_cover_items(result: ParseResult) -> list[list]:
    for c in result.contents:
        if isinstance(c, VideoContent) and c.cover is not None:
            cover_path = await c.cover.safe_get()
            if cover_path:
                return [[Comp.Image.fromFileSystem(str(cover_path))]]
    return []


def _extract_title_url_items(result: ParseResult, platform: str) -> list[list]:
    values: list[str] = []
    candidates = [result.url, result.title] if platform == "bilibili" else [result.title, result.url]
    for raw in candidates:
        text = str(raw or "").strip()
        if text and text not in values:
            values.append(text)
    return [[Comp.Plain("\n".join(values))]] if values else []


def _extract_author_items(result: ParseResult) -> list[list]:
    author = result.author
    if author is None:
        return []
    lines: list[str] = []
    name = str(author.name or "").strip()
    if name:
        lines.append(f"👤 作者：{name}")
    desc = str(author.description or "").strip()
    if desc:
        lines.append(desc[:160])
    return [[Comp.Plain("\n".join(lines))]] if lines else []


def _extract_text_items(result: ParseResult, platform: str) -> list[list]:
    parts: list[str] = []
    raw_text = str(result.text or "").strip()
    if raw_text:
        if platform == "douyin":
            tags = " #".join(raw_text.split()[:5])
            if tags:
                parts.append(f"#{tags}")
        elif platform == "bilibili":
            parts.append(f"📝 简介：{raw_text[:_TEXT_LIMITS['bilibili']]}")
        else:
            limit = _TEXT_LIMITS.get(platform, 220)
            parts.append(raw_text[:limit])

    graphic_texts = [
        str(g).strip() for g in result.graphics if isinstance(g, str) and str(g).strip()
    ]
    if graphic_texts:
        parts.append("\n".join(graphic_texts)[:600])

    text_body = "\n".join(parts).strip()
    return [[Comp.Plain(text_body)]] if text_body else []


def _extract_meta_items(result: ParseResult, *, include_warnings: bool = True) -> list[list]:
    lines: list[str] = []
    if dur := result.extra.get("duration"):
        lines.append(f"⏱ 时长：{dur}")
    if repo_line := result.extra.get("repo_line"):
        lines.append(str(repo_line))
    if stats := result.extra.get("stats_line"):
        lines.append(str(stats))
    if online := result.extra.get("online"):
        lines.append(str(online))
    if include_warnings:
        for w in result.extra.get("limit_warnings") or ():
            if w:
                lines.append(str(w))
    return [[Comp.Plain("\n".join(lines))]] if lines else []


async def _extract_repost_items(result: ParseResult) -> list[list]:
    rp = result.repost
    if rp is None:
        return []
    items: list[list] = []
    lines: list[str] = []
    rp_author = str(rp.author.name).strip() if rp.author and rp.author.name else ""
    lines.append(f"🔁 转发原帖{f'（@{rp_author}）' if rp_author else ''}")
    if rp.title:
        lines.append(str(rp.title).strip())
    if rp.url and rp.url != rp.title:
        lines.append(str(rp.url).strip())
    if rp.text:
        lines.append(str(rp.text).strip()[:300])
    items.append([Comp.Plain("\n".join(lines))])
    items.extend(await _collect_images_for(rp))
    if not any(isinstance(c, ImageContent) for c in rp.contents):
        items.extend(await _extract_cover_items(rp))
    return items


async def _extract_node_items(
    nid: str,
    result: ParseResult,
    platform: str,
    *,
    header_str: str,
    render_path: Path | None,
    music_card: Any,
    audio_as_file: bool,
    wants_merge: bool,
    is_onebot: bool,
    include_warnings: bool,
    video_url_resolver: Callable[[Path], Awaitable[str | None]] | None = None,
) -> list[list]:
    if nid == "card":
        return [[Comp.Image.fromFileSystem(str(render_path))]] if render_path is not None else []
    if nid == "header":
        return [[Comp.Plain(header_str)]] if header_str else []
    if nid == "author":
        return _extract_author_items(result)
    if nid == "title_url":
        return _extract_title_url_items(result, platform)
    if nid == "cover":
        return await _extract_cover_items(result)
    if nid == "text":
        return _extract_text_items(result, platform)
    if nid == "meta":
        return _extract_meta_items(result, include_warnings=include_warnings)
    if nid == "images":
        return await _collect_images_for(result)
    if nid == "repost":
        return await _extract_repost_items(result)
    if nid == "music_card":
        return [[music_card]] if music_card is not None else []
    if nid == "video":
        out: list[list] = []
        for cont in result.contents:
            if not _is_video_candidate(cont):
                continue
            path = await cont.path_task.safe_get()
            if path is None:
                continue
            comp: Any = None
            if wants_merge and is_onebot and video_url_resolver is not None:
                try:
                    url = await video_url_resolver(path)
                    if url:
                        comp = Comp.Video.fromURL(url)
                except Exception:
                    logger.debug("[link_parser] 合并视频转文件服务 URL 失败，回退本地路径", exc_info=True)
            if comp is None:
                comp = Comp.Video.fromFileSystem(str(path))
            out.append([comp])
        return out
    if nid == "audio":
        out = []
        for cont in result.contents:
            if not isinstance(cont, AudioContent):
                continue
            path = await cont.path_task.safe_get()
            if path is None:
                continue
            if audio_as_file:
                out.append([Comp.File(name=path.name, file=str(path))])
            else:
                out.append([Comp.Record.fromFileSystem(str(path))])
        return out
    return []


def _resolve_effective_rules(
    result: ParseResult,
    pconfig: Any,
    *,
    render_path: Path | None,
    music_card: Any,
) -> tuple[str, list[dict[str, Any]]]:
    """解析并落地当前条目的节点执行顺序、启用状态与合并策略。"""
    mode = detect_content_mode(result)
    defaults = default_node_rules()[mode]
    rules = [dict(r) for r in normalize_node_rules(pconfig.NODE_RULES).get(mode, defaults)]
    is_custom_mode = rules != defaults

    suppress_text = bool(result.extra.get("suppress_text_output")) and render_path is not None and not is_custom_mode
    card_rule = next((r for r in rules if r["id"] == "card"), None)
    text_like_enabled = any(
        r["enabled"] and r["id"] in {"header", "author", "title_url", "cover", "text", "meta", "repost"}
        for r in rules
    )
    need_nocard_fallback = (
        render_path is None
        and not suppress_text
        and bool(card_rule and card_rule["enabled"])
        and not text_like_enabled
    )

    music_rule = next((r for r in rules if r["id"] == "music_card"), None)
    suppress_audio_by_music = bool(music_card is not None and music_rule and music_rule["enabled"])

    effective: list[dict[str, Any]] = []
    for row in rules:
        r = dict(row)
        nid = r["id"]
        if suppress_text and nid in _SUPPRESSIBLE_TEXT_NODES:
            r["enabled"] = False
        elif need_nocard_fallback and nid in _FALLBACK_TEXT_NODES:
            r["enabled"] = True
            r["merge"] = True
        if suppress_audio_by_music and nid == "audio":
            r["enabled"] = False
        effective.append(r)

    return mode, effective


async def plan_output_segments(
    result: ParseResult,
    *,
    pconfig: Any = None,
    is_onebot: bool = True,
    chat_platform: str = "",
    brand_name: str = DEFAULT_BRAND_NAME,
    render_path: Path | None = None,
    music_card: Any = None,
    video_url_resolver: Callable[[Path], Awaitable[str | None]] | None = None,
) -> dict[str, Any]:
    """按分模式节点规则把解析结果规划为有序发送段（合并批 / 独立消息段）。"""
    cfg = pconfig or get_config()
    parser_platform = result.platform.name
    header_str = build_header_text(result, parser_platform, brand_name=brand_name)
    mode, rules = _resolve_effective_rules(
        result,
        cfg,
        render_path=render_path,
        music_card=music_card,
    )
    audio_as_file = bool(result.extra.get("audio_as_file") or "discord" in chat_platform.lower())
    include_warnings = render_path is None or not any(
        r["id"] == "card" and r["enabled"] for r in rules
    )

    segments: list[dict[str, Any]] = []
    pending_merge: list[list] = []
    pending_header = ""
    pending_has_non_header = False

    def flush_merge() -> None:
        nonlocal pending_merge, pending_header, pending_has_non_header
        if not pending_merge:
            return
        segments.append(
            {
                "kind": "merge",
                "items": pending_merge,
                "header": pending_header,
                "has_non_header": pending_has_non_header,
            }
        )
        pending_merge = []
        pending_header = ""
        pending_has_non_header = False

    for rule in rules:
        if not rule["enabled"]:
            continue
        nid = rule["id"]
        meta = NODE_CATALOG.get(nid, {})
        supports_merge = bool(meta.get("supports_merge", True))
        wants_merge = bool(rule["merge"]) and supports_merge

        # 非 OneBot 平台（webpage / plain）仅文本与图片节点可合并；视频/音频固定独立发送避免丢媒体
        if not is_onebot and nid in {"video", "audio"}:
            wants_merge = False
        # Comp.File 组件在 OneBot 转发节点外发送更稳妥
        if nid == "audio" and audio_as_file:
            wants_merge = False

        items = await _extract_node_items(
            nid,
            result,
            parser_platform,
            header_str=header_str,
            render_path=render_path,
            music_card=music_card,
            audio_as_file=audio_as_file,
            wants_merge=wants_merge,
            is_onebot=is_onebot,
            include_warnings=include_warnings,
            video_url_resolver=video_url_resolver,
        )
        if not items:
            continue

        if wants_merge:
            if nid == "header":
                pending_header = header_str
            else:
                pending_has_non_header = True
            pending_merge.extend(items)
        else:
            flush_merge()
            segments.append(
                {
                    "kind": "standalone",
                    "nid": nid,
                    "items": items,
                    "proactive_image": (nid == "card")
                    or (not is_onebot and nid in {"cover", "images"}),
                }
            )

    flush_merge()
    return {
        "mode": mode,
        "header": header_str,
        "rules": rules,
        "segments": segments,
    }


async def build_platform_output(
    result: ParseResult,
    platform: str,
    *,
    brand_name: str = DEFAULT_BRAND_NAME,
) -> tuple[str, list[list]]:
    """兼容旧调用方（如链接调试页）：构建 ``(标题头, 合并转发节点列表)``。"""
    header = build_header_text(result, platform, brand_name=brand_name)
    nodes: list[list] = []

    if platform == "bilibili":
        nodes.extend(_extract_title_url_items(result, platform))
        nodes.extend(await _extract_cover_items(result))
        if dur := result.extra.get("duration"):
            nodes.append([Comp.Plain(f"⏱ 时长：{dur}")])
        meta_parts: list[str] = []
        if stats := result.extra.get("stats_line"):
            meta_parts.append(str(stats))
        if result.text:
            prefix = "\n" if meta_parts else ""
            meta_parts.append(f"{prefix}📝 简介：{result.text[:200]}")
        if online := result.extra.get("online"):
            prefix = "\n" if meta_parts else ""
            meta_parts.append(f"{prefix}{online}")
        if meta_parts:
            nodes.append([Comp.Plain("".join(meta_parts))])
        nodes.extend(await _collect_images_for(result))
        return header, nodes

    if platform == "xiaohongshu":
        nodes.extend(_extract_text_items(result, platform))
        nodes.extend(await _collect_images_for(result))
        return header, nodes

    if platform == "douyin":
        is_video = not result.img_contents and any(
            _is_video_candidate(c) for c in result.contents
        )
        text_items: list[str] = []
        if result.title:
            text_items.append(result.title)
        if result.text:
            tags = " #".join(result.text.split()[:5])
            if tags:
                text_items.append(f"#{tags}")
        if text_items:
            content = [Comp.Plain("\n".join(text_items))]
            if is_video:
                covers = await _extract_cover_items(result)
                if covers:
                    content.extend(covers[0])
            nodes.append(content)
        nodes.extend(await _collect_images_for(result))
        return header, nodes

    if platform == "kuaishou":
        if result.title:
            nodes.append([Comp.Plain(result.title)])
        if result.text:
            nodes.append([Comp.Plain(result.text[:100])])
        nodes.extend(await _extract_cover_items(result))
        return header, nodes

    if platform == "github":
        nodes.extend(_extract_title_url_items(result, platform))
        node2_parts = []
        if repo_line := result.extra.get("repo_line"):
            node2_parts.append(str(repo_line))
        if result.text:
            prefix = "📝 " if node2_parts else ""
            node2_parts.append(f"{prefix}{result.text[:200]}")
        if stats := result.extra.get("stats_line"):
            node2_parts.append(str(stats))
        if node2_parts:
            nodes.append([Comp.Plain("\n".join(node2_parts))])
        return header, nodes

    if platform == "coolapk":
        text_items = []
        if result.text:
            text_items.append(result.text[:500])
        if stats := result.extra.get("stats_line"):
            text_items.append(str(stats))
        if text_items:
            nodes.append([Comp.Plain("\n".join(text_items))])
        nodes.extend(await _collect_images_for(result))
        return header, nodes

    if result.title:
        nodes.append([Comp.Plain(result.title)])
    if result.text:
        nodes.append([Comp.Plain(result.text[:150])])
    images = await _collect_images_for(result)
    if images:
        nodes.extend(images)
    else:
        nodes.extend(await _extract_cover_items(result))
    return header, nodes


def estimate_item_bytes(item: list) -> int:
    """估算单个节点内容的图片字节数（文本忽略不计）。"""
    total = 0
    for comp in item:
        if not isinstance(comp, Comp.Image):
            continue
        raw = comp.path or ""
        if not raw:
            continue
        try:
            path = Path(raw)
            if path.is_file():
                total += path.stat().st_size
        except Exception:
            continue
    return total


def split_node_items(text_items: list[list]) -> list[list[list]]:
    """按字节预算与节点数上限把节点切成多批。"""
    pconfig = get_config()
    max_bytes = pconfig.FORWARD_MAX_BATCH_MB * 1024 * 1024
    max_nodes = pconfig.FORWARD_MAX_NODES

    batches: list[list[list]] = []
    current: list[list] = []
    current_bytes = 0

    for item in text_items:
        size = estimate_item_bytes(item)
        if current and (
            current_bytes + size > max_bytes or len(current) >= max_nodes
        ):
            batches.append(current)
            current, current_bytes = [], 0
        current.append(item)
        current_bytes += size
        if current_bytes >= max_bytes or len(current) >= max_nodes:
            batches.append(current)
            current, current_bytes = [], 0

    if current:
        batches.append(current)
    return batches


async def send_nodes_batched(
    event: AstrMessageEvent,
    header: str,
    text_items: list[list],
    *,
    header_inline: bool = False,
):
    """按预算拆成多条合并转发逐条发送。

    ``header_inline=True`` 表示 ``text_items`` 内部已按用户设定位置包含标题头节点，
    第一批不再额外在顶部插入 ``header``；拆分第 2+ 批时自动补上续批提示头。
    """
    batches = split_node_items(text_items)
    if not batches:
        return

    sender_name = event.get_sender_name()
    sender_id = event.get_sender_id()
    total = len(batches)
    if total > 1:
        logger.info(f"[link_parser] 内容节点较多，合并转发拆分为 {total} 条发送")

    for idx, batch in enumerate(batches, start=1):
        nodes = Comp.Nodes([])
        if idx == 1:
            title = "" if header_inline else header
        else:
            title = f"{header} (续 {idx}/{total})" if header else f"合并内容 ({idx}/{total})"
        if title:
            nodes.nodes.append(
                Comp.Node(
                    uin=sender_id,
                    name=sender_name,
                    content=[Comp.Plain(title)],
                )
            )
        for item in batch:
            nodes.nodes.append(
                Comp.Node(
                    uin=sender_id,
                    name=sender_name,
                    content=item,
                )
            )
        yield event.chain_result([nodes])
        if idx < total:
            await asyncio.sleep(0.5)


async def send_plain_output(
    event: AstrMessageEvent,
    header: str,
    nodes_content: list[list],
):
    """将 header + 所有文本 + 所有图片合并为一条消息链发送。"""
    parts: list = []

    if header:
        parts.append(Comp.Plain(header + "\n"))

    text_lines: list[str] = []
    for node_content in nodes_content:
        for comp in node_content:
            if isinstance(comp, Comp.Plain):
                text_lines.append(comp.text)
            elif isinstance(comp, Comp.Image):
                parts.append(comp)

    if text_lines:
        parts.append(Comp.Plain("\n".join(text_lines)))

    if parts:
        yield event.chain_result(parts)


async def try_send_media(event: AstrMessageEvent, result: ParseResult):
    """单独发送媒体文件（视频 / 音频）。"""
    for cont in result.contents:
        if not isinstance(cont, (VideoContent, AudioContent)):
            continue
        path = await cont.path_task.safe_get()
        if path is None:
            continue

        if isinstance(cont, VideoContent):
            if await resolve_still_path(cont) is not None:
                continue
            yield event.chain_result([Comp.Video.fromFileSystem(str(path))])
        elif isinstance(cont, AudioContent):
            try:
                platform_name = event.get_platform_name().lower()
            except Exception:
                platform_name = ""
            if result.extra.get("audio_as_file") or "discord" in platform_name:
                yield event.chain_result([Comp.File(name=path.name, file=str(path))])
            else:
                yield event.chain_result([Comp.Record(file=str(path))])
