"""缓存目录清理工具。"""

import time
from pathlib import Path

from astrbot.api import logger

from .media import safe_unlink


async def cleanup_cache_dir(cache_dir: Path, ttl_hours: int) -> int:
    """清理缓存目录中超过 TTL 的过期文件。

    Args:
        cache_dir: 缓存目录路径。
        ttl_hours: 文件存活阈值（小时）。文件最后修改时间早于
                   (now - ttl_hours) 则视为过期。

    Returns:
        清理的文件数量。
    """
    if not cache_dir.exists():
        return 0

    cutoff = time.time() - ttl_hours * 3600
    cleaned = 0

    for f in cache_dir.iterdir():
        if not f.is_file():
            continue
        try:
            if f.stat().st_mtime < cutoff:
                await safe_unlink(f)
                cleaned += 1
        except Exception:
            continue

    if cleaned > 0:
        logger.info(f"缓存清理完成: 已清理 {cleaned} 个过期文件 ({cache_dir})")
    return cleaned


async def clear_cache_dir(cache_dir: Path) -> int:
    """清空缓存目录中的所有文件，并删除其中的空目录。

    缓存目录本身会保留，配置目录不在此目录内，因此不会被清理。

    Returns:
        成功清理的文件数量。
    """
    if not cache_dir.exists():
        return 0

    cleaned = 0
    entries = sorted(
        cache_dir.rglob("*"),
        key=lambda path: len(path.parts),
        reverse=True,
    )

    for entry in entries:
        try:
            # 先判断符号链接，避免误将链接目标当作缓存目录递归处理。
            if entry.is_symlink() or entry.is_file():
                entry.unlink()
                cleaned += 1
            elif entry.is_dir():
                entry.rmdir()
        except FileNotFoundError:
            # 清理过程中可能被下载任务或其他清理任务先行删除。
            continue
        except OSError as exc:
            logger.warning(f"清理缓存失败: {entry} ({exc})")

    logger.info(f"缓存清理完成: 已清理 {cleaned} 个文件 ({cache_dir})")
    return cleaned
