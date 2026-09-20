"""媒体处理工具：文件清理、ffmpeg 命令与文件名生成。"""

import asyncio
import hashlib
from pathlib import Path
from urllib.parse import urlparse

from astrbot.api import logger


async def safe_unlink(path: Path):
    """安全删除文件"""
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


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
