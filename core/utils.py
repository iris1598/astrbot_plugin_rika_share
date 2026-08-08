"""工具函数"""

import re
import asyncio
import hashlib
import time
from pathlib import Path
from urllib.parse import urlparse

from astrbot.api import logger


def keep_zh_en_num(text: str) -> str:
    """保留字符串中的中英文和数字"""
    return re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9\-_]", "", text.replace(" ", "_"))


async def safe_unlink(path: Path):
    """安全删除文件"""
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


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

    for f in cache_dir.rglob("*"):
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
    """清空缓存目录中的所有文件，并保留目录结构。"""
    if not cache_dir.exists():
        return 0

    cleaned = 0
    for f in cache_dir.rglob("*"):
        if not f.is_file():
            continue
        try:
            await safe_unlink(f)
            if not f.exists():
                cleaned += 1
        except Exception:
            continue

    logger.info(f"缓存已手动清理: 已清理 {cleaned} 个文件 ({cache_dir})")
    return cleaned


async def exec_ffmpeg_cmd(cmd: list[str]) -> None:
    """执行 ffmpeg 命令"""
    logger.debug(f"Executing ffmpeg command: {' '.join(cmd)}")
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()
        return_code = process.returncode
    except FileNotFoundError:
        raise RuntimeError("ffmpeg 未安装或无法找到可执行文件")

    if return_code != 0:
        error_msg = stderr.decode().strip()
        raise RuntimeError(f"ffmpeg 执行失败: {error_msg}")


async def merge_av(
    *,
    v_path: Path,
    a_path: Path,
    output_path: Path,
) -> None:
    """合并视频和音频"""
    logger.info(f"Merging {v_path.name} and {a_path.name} to {output_path.name}")

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(v_path),
        "-i",
        str(a_path),
        "-c",
        "copy",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        str(output_path),
    ]

    await exec_ffmpeg_cmd(cmd)
    await asyncio.gather(safe_unlink(v_path), safe_unlink(a_path))
    logger.info(f"Merged {output_path.name}, {fmt_size(output_path)}")


async def merge_av_h264(
    *,
    v_path: Path,
    a_path: Path,
    output_path: Path,
) -> None:
    """合并视频和音频，并使用 H.264 编码"""
    logger.info(f"Merging {v_path.name} and {a_path.name} to {output_path.name} with H.264")

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(v_path),
        "-i",
        str(a_path),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        str(output_path),
    ]

    await exec_ffmpeg_cmd(cmd)
    await asyncio.gather(safe_unlink(v_path), safe_unlink(a_path))
    logger.info(f"Merged {output_path.name} with H.264, {fmt_size(output_path)}")


async def encode_video_to_h264(video_path: Path) -> Path:
    """将视频重新编码到 h264"""
    output_path = video_path.with_name(f"{video_path.stem}_h264{video_path.suffix}")
    if output_path.exists():
        return output_path
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "23",
        str(output_path),
    ]
    await exec_ffmpeg_cmd(cmd)
    logger.info(f"视频重新编码为 H.264 成功: {output_path}, {fmt_size(output_path)}")
    await safe_unlink(video_path)
    return output_path


async def extract_video_first_frame(video_path: Path) -> Path:
    """从视频中提取第一帧"""
    first_frame_path = video_path.with_suffix(".jpg")
    if first_frame_path.exists():
        return first_frame_path

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-ss",
        "00:00:01",
        "-vframes",
        "1",
        str(first_frame_path),
    ]

    await exec_ffmpeg_cmd(cmd)
    return first_frame_path


async def convert_video_to_gif(video_path: Path) -> Path:
    """将视频转换为 GIF"""
    gif_path = video_path.with_suffix(".gif")
    if gif_path.exists():
        return gif_path

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-c:v",
        "gif",
        str(gif_path),
    ]
    await exec_ffmpeg_cmd(cmd)
    return gif_path


def fmt_size(file_path: Path) -> str:
    """格式化文件大小"""
    return f"大小: {file_path.stat().st_size / 1024 / 1024:.2f} MB"


def generate_file_name(url: str, default_suffix: str = "") -> str:
    """根据 url 生成文件名"""
    path = Path(urlparse(url).path)
    suffix = path.suffix if path.suffix else default_suffix
    url_hash = hashlib.md5(url.encode()).hexdigest()[:16]
    file_name = f"{url_hash}{suffix}"
    return file_name


def is_module_available(module_name: str) -> bool:
    """检查模块是否可用"""
    import importlib.util
    return importlib.util.find_spec(module_name) is not None
