"""封面下载：从解析结果里挑出「封面」并落盘。

各平台 / 各内容类型的封面字段并不统一（视频有 ``VideoContent.cover``，
图文只有图片列表），这里按「视频封面 → 图文首图 → 动图·实况的静态图」
的顺序回退，让「引用消息 + 下载封面」对所有已支持的内容形态都有确定的行为。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..models import ImageContent, ParseResult, VideoContent
from ..models.task import PathTask

__all__ = ["CoverPick", "download_cover", "select_cover"]


@dataclass(slots=True)
class CoverPick:
    """选中的封面：惰性路径任务 + 展示用标签（``封面`` / ``首图``）。"""

    task: PathTask
    label: str


def select_cover(result: ParseResult) -> CoverPick | None:
    """按内容形态挑出封面；没有任何可用图片时返回 ``None``。"""
    # 视频封面（B站 / 抖音 / 快手 / AcFun 等）
    for cont in result.contents:
        if isinstance(cont, VideoContent) and cont.cover is not None:
            return CoverPick(cont.cover, "封面")
    # 图文笔记的首图（B站 Opus / 小红书 / 微博长文）
    for graphic in result.graphics:
        if isinstance(graphic, ImageContent):
            return CoverPick(graphic.path_task, "首图")
    # 图集 / 动态里的第一张图
    for cont in result.contents:
        if isinstance(cont, ImageContent):
            return CoverPick(cont.path_task, "首图")
    # 动图（Twitter gif）/ 实况照片（抖音）对外发送的那张静态图
    for cont in result.contents:
        if isinstance(cont, VideoContent) and cont.still_path is not None:
            return CoverPick(cont.still_path, "首图")
    return None


async def download_cover(result: ParseResult) -> tuple[CoverPick | None, Path | None]:
    """选封面并等它落盘，返回 ``(选择结果, 文件路径)``。

    ``选择结果`` 为 ``None`` 表示这条内容没有封面；``路径`` 为 ``None``
    表示有封面但没下下来——两者对用户的提示文案不同，不要合并。
    """
    pick = select_cover(result)
    if pick is None:
        return None, None
    return pick, await pick.task.safe_get()
