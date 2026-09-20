"""解析结果 → 消息链的输出构建。

按平台规则把 :class:`~link_parser.models.result.ParseResult` 组装成「标题头 + 节点内容」，
并提供两种发送方式：

- :func:`send_nodes_batched`  OneBot v11 合并转发（按体积/节点数预算拆分）
- :func:`send_plain_output`  其他平台（QQ Official / Telegram 等）的纯文本 + 图片链
"""

import asyncio
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
import astrbot.api.message_components as Comp

from ..config import get_config
from ..models import AudioContent, ImageContent, ParseResult, VideoContent

__all__ = [
    "build_platform_output",
    "send_nodes_batched",
    "send_plain_output",
    "try_send_media",
]


def _is_video_candidate(cont) -> bool:
    """是否为「真视频」（排除已重建为图片类产物的动图 / 动态照片）。"""
    return isinstance(cont, VideoContent) and not cont.is_image_like


async def resolve_still_path(cont: VideoContent) -> Path | None:
    """图片类产物路径：动态照片(.jpg，抖音) / 动图(.gif，Twitter)；
    普通视频或产物缺失时返回 None"""
    if not cont.is_image_like:
        return None
    task = cont.still_path
    if task is None:
        return None
    return await task.safe_get()


async def build_platform_output(
    result: ParseResult, platform: str
) -> tuple[str, list[list]]:
    """构建各平台输出：返回 (标题头, 合并转发节点内容列表)"""
    platform_name = result.platform.display_name
    content_type = result.extra.get("content_type", "动态")

    if platform == "bilibili":
        header = f"莉卡解析 | {platform_name} - {content_type}"
        # 第一条消息：链接 + 标题 + 封面
        node1_text = "\n".join([v for v in [result.url, result.title] if v])
        node1 = [Comp.Plain(node1_text)] if node1_text else []
        if result.contents:
            vc = next((c for c in result.contents if isinstance(c, VideoContent)), None)
            if vc and vc.cover:
                cover_path = await vc.cover.safe_get()
                if cover_path:
                    node1.append(Comp.Image.fromFileSystem(str(cover_path)))
        # 第二条消息：时长
        node2 = []
        if dur := result.extra.get("duration"):
            node2.append(Comp.Plain(f"⏱ 时长：{dur}"))
        # 第三条消息：统计 + 简介 + 在线
        node3_parts = []
        if stats := result.extra.get("stats_line"):
            node3_parts.append(stats)
        if result.text:
            prefix = "\n" if node3_parts else ""
            node3_parts.append(f"{prefix}📝 简介：{result.text[:200]}")
        if online := result.extra.get("online"):
            prefix = "\n" if node3_parts else ""
            node3_parts.append(f"{prefix}{online}")
        node3 = [Comp.Plain("".join(node3_parts))] if node3_parts else []
        nodes = []
        if node1:
            nodes.append(node1)
        if node2:
            nodes.append(node2)
        if node3:
            nodes.append(node3)
        # 图片内容：来自图文(Opus)解析的 graphics
        for g in result.graphics:
            if isinstance(g, ImageContent):
                path = await g.path_task.safe_get()
                if path:
                    nodes.append([Comp.Image.fromFileSystem(str(path))])
            elif isinstance(g, str):
                nodes.append([Comp.Plain(g)])
        # 图片内容：来自动态解析的 contents
        for c in result.contents:
            if isinstance(c, ImageContent):
                path = await c.path_task.safe_get()
                if path:
                    nodes.append([Comp.Image.fromFileSystem(str(path))])
        return header, nodes

    if platform == "xiaohongshu":
        header = f"莉卡解析 | {platform_name} - {'视频' if result.extra.get('is_video') else '图文'}"
        nodes = []
        # 正文文字
        if result.text:
            nodes.append([Comp.Plain(result.text[:300])])
        # 正文中的图片
        for g in result.graphics:
            if isinstance(g, ImageContent):
                path = await g.path_task.safe_get()
                if path:
                    nodes.append([Comp.Image.fromFileSystem(str(path))])
            elif isinstance(g, str):
                nodes.append([Comp.Plain(g)])
        # 内容中的图片
        for c in result.contents:
            if isinstance(c, ImageContent):
                path = await c.path_task.safe_get()
                if path:
                    nodes.append([Comp.Image.fromFileSystem(str(path))])
        return header, nodes

    if platform == "douyin":
        is_video = not result.img_contents and any(
            _is_video_candidate(c) for c in result.contents
        )
        has_live_photo = any(
            isinstance(c, VideoContent) and c.is_live_photo for c in result.contents
        )
        # 重建后的普通动图（非实况照片）
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
        header = f"莉卡解析 | {platform_name} - {kind}"
        nodes = []
        text_items = []
        if result.title:
            text_items.append(result.title)
        if result.text:
            tags = " #".join(result.text.split()[:5])
            if tags:
                text_items.append(f"#{tags}")
        # 简介 + 封面放在同一条消息（仅纯视频，图文/动图已放入图片节点）
        if text_items:
            content = [Comp.Plain("\n".join(text_items))]
            # 尝试加入封面
            if is_video:
                vc = next(
                    (c for c in result.contents if _is_video_candidate(c)), None
                )
                if vc and vc.cover:
                    cover_path = await vc.cover.safe_get()
                    if cover_path:
                        content.append(Comp.Image.fromFileSystem(str(cover_path)))
            nodes.append(content)
        # 图片 / 动图内容放进合并转发
        for c in result.contents:
            if isinstance(c, ImageContent):
                path = await c.path_task.safe_get()
                if path:
                    nodes.append([Comp.Image.fromFileSystem(str(path))])
            elif isinstance(c, VideoContent):
                still_path = await resolve_still_path(c)
                if still_path is not None:
                    nodes.append([Comp.Image.fromFileSystem(str(still_path))])
        return header, nodes

    if platform == "kuaishou":
        is_video = any(isinstance(c, VideoContent) for c in result.contents)
        header = f"莉卡解析 | {platform_name} - {'视频' if is_video else '图文'}"
        nodes = []
        if result.title:
            nodes.append([Comp.Plain(result.title)])
        if result.text:
            nodes.append([Comp.Plain(result.text[:100])])
        # 图片/封面
        if result.contents:
            vc = next((c for c in result.contents if isinstance(c, VideoContent)), None)
            if vc and vc.cover:
                cover_path = await vc.cover.safe_get()
                if cover_path:
                    nodes.append([Comp.Image.fromFileSystem(str(cover_path))])
        return header, nodes

    # 通用平台
    header = f"莉卡解析 | {platform_name} - {content_type}"
    nodes = []
    if result.title:
        nodes.append([Comp.Plain(result.title)])
    if result.text:
        nodes.append([Comp.Plain(result.text[:150])])
    # 图片放进合并转发
    for c in result.contents:
        if isinstance(c, ImageContent):
            path = await c.path_task.safe_get()
            if path:
                nodes.append([Comp.Image.fromFileSystem(str(path))])
        elif isinstance(c, VideoContent):
            still_path = await resolve_still_path(c)
            if still_path is not None:
                nodes.append([Comp.Image.fromFileSystem(str(still_path))])
            elif c.cover:
                cover_path = await c.cover.safe_get()
                if cover_path:
                    nodes.append([Comp.Image.fromFileSystem(str(cover_path))])
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
    """按字节预算与节点数上限把节点切成多批。

    OneBot 发送合并转发时会把节点内所有图片完整 base64 编码，再整体
    JSON 序列化，峰值内存约为图片原始总量的 4 倍，且这些拷贝同时存活。
    大图集一次性发送极易 OOM，因此按预算切分，使峰值只与单批相关。
    单张超过预算的图片无法再拆，会单独成一条发送。
    """
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
):
    """按预算拆成多条合并转发逐条发送。

    每条独立经历 to_dict -> base64 -> 发送 -> 释放，因此峰值内存只与
    单批大小相关，而不是整个图集。
    """
    batches = split_node_items(text_items)
    if not batches:
        return

    sender_name = event.get_sender_name()
    sender_id = event.get_sender_id()
    total = len(batches)
    if total > 1:
        logger.info(f"[link_parser] 图集较大，合并转发拆分为 {total} 条发送")

    for idx, batch in enumerate(batches, start=1):
        nodes = Comp.Nodes([])
        if idx == 1:
            title = header
        else:
            title = f"{header} (图集 {idx}/{total})" if header else f"图集 {idx}/{total}"
        if title:
            nodes.nodes.append(Comp.Node(
                uin=sender_id, name=sender_name,
                content=[Comp.Plain(title)],
            ))
        for item in batch:
            nodes.nodes.append(Comp.Node(
                uin=sender_id, name=sender_name, content=item,
            ))
        yield event.chain_result([nodes])
        if idx < total:
            await asyncio.sleep(0.5)


async def send_plain_output(
    event: AstrMessageEvent,
    header: str,
    nodes_content: list[list],
):
    """将 header + 所有文本 + 所有图片合并为一条消息链发送。

    适用于不支持 Comp.Nodes（合并转发）的平台，包括 QQ Official Bot、
    Telegram 等。视频由 :func:`try_send_media` 单独处理。
    """
    parts: list = []

    # header 文本
    if header:
        parts.append(Comp.Plain(header + "\n"))

    # 收集所有节点的文本和图片
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
    """单独发送媒体文件（视频 / 音频）。所有图片/封面已在合并转发中，不重复发送。

    qqofficial_full 适配器支持分片上传（>20MB 自动走 chunked upload），
    因此不再在插件层做文件大小限制，交由适配器处理。
    """
    for cont in result.contents:
        if not isinstance(cont, (VideoContent, AudioContent)):
            continue  # 图片已在合并转发中
        path = await cont.path_task.safe_get()
        if path is None:
            continue

        if isinstance(cont, VideoContent):
            if await resolve_still_path(cont) is not None:
                continue  # 动图 / 实况照片已作为图片并入合并转发
            yield event.chain_result([Comp.Video.fromFileSystem(str(path))])
        elif isinstance(cont, AudioContent):
            yield event.chain_result([Comp.Record(file=str(path))])
