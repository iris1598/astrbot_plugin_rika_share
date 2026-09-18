"""实况照片重建（非苹果系 · 单文件「动态照片」）

抖音等平台的实况照片，CDN 只会给出两份原始素材：
    - 主图 JPEG（纯图，实测连 EXIF 都没有）
    - 短视频 MP4（2~4 秒，H.264）
成品容器必须在本地合成。这里实现的是单文件动态照片：

    主图 JPEG（APP1 段写入 XMP 索引） + 直接拼接在文件尾部的 MP4

读取方（Google 相册、小米 / OPPO / vivo / 三星等相册、Windows 照片）通过 XMP 里的
``GCamera:MicroVideoOffset`` / ``Container:Directory`` 定位尾部视频并播放；
文件本身仍是一个完全合法的 JPEG，任何看图软件都能正常打开主图。

为什么不做苹果 Live Photo：
    苹果方案要求主图的 Apple MakerNote 里带 ``com.apple.quicktime.content.identifier``，
    而 Apple MakerNote 无法从零构造（必须由相机/相册写入），MOV 侧还额外要求
    HEVC + ``still-image-time`` 元数据轨。抖音主图本身就是纯 JPEG（无任何 EXIF），
    走非苹果系单文件格式更贴合源素材，且无需 ffmpeg 参与合成。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from astrbot.api import logger

__all__ = [
    "build_motion_photo",
    "create_motion_photo",
    "find_motion_photo_offset",
]

XMP_NAMESPACE = b"http://ns.adobe.com/xap/1.0/\x00"

_JPEG_SOI = b"\xff\xd8"
_XMP_PADDING = 2048
# 扫描视频 fourcc 的最大字节数（moov 可能在头也可能在尾）
_CODEC_SCAN_LIMIT = 8 * 1024 * 1024

_HEVC_FOURCCS = (b"hvc1", b"hev1")
_AVC_FOURCCS = (b"avc1", b"avc3")

# XMP 包体。同时写两套规范：
#   - Camera:MotionPhoto + Container:Directory —— 新规范，Google / 三星 / 小米 / OPPO / vivo 读这个
#   - GCamera:MicroVideo + MicroVideoOffset  —— 旧规范，兼容老设备与老版本相册
_XMP_TEMPLATE = """<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="rika-share/live-photo">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:Camera="http://ns.google.com/photos/1.0/camera/"
    xmlns:GCamera="http://ns.google.com/photos/1.0/camera/"
    xmlns:Container="http://ns.google.com/photos/1.0/container/"
    xmlns:Item="http://ns.google.com/photos/1.0/container/item/"
    Camera:MotionPhoto="1"
    Camera:MotionPhotoVersion="1"
    Camera:MotionPhotoPresentationTimestampUs="{ts}"
    GCamera:MicroVideo="1"
    GCamera:MicroVideoVersion="1"
    GCamera:MicroVideoOffset="{video_len}"
    GCamera:MicroVideoPresentationTimestampUs="{ts}">
   <Container:Directory>
    <rdf:Seq>
     <rdf:li rdf:parseType="Resource">
      <Container:Item Item:Mime="image/jpeg" Item:Semantic="Primary" Item:Length="0" Item:Padding="0"/>
     </rdf:li>
     <rdf:li rdf:parseType="Resource">
      <Container:Item Item:Mime="video/mp4" Item:Semantic="MotionPhoto" Item:Length="{video_len}" Item:Padding="0"/>
     </rdf:li>
    </rdf:Seq>
   </Container:Directory>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>"""


def build_xmp(video_len: int, presentation_ts_us: int = 0) -> bytes:
    """构建动图索引 XMP 包。

    Args:
        video_len: 尾部视频的字节数。Google 规范里的 ``MicroVideoOffset``
            指的是「文件末尾往回退多少字节到达视频起点」，因此正好等于视频长度。
        presentation_ts_us: 主图对应视频中的时间戳（微秒）。0 表示未指定。
    """
    packet = _XMP_TEMPLATE.format(ts=int(presentation_ts_us), video_len=int(video_len))
    return packet.encode("utf-8") + b" " * _XMP_PADDING


def _head_segments(data: bytes) -> list[tuple[int, int, int]]:
    """遍历 JPEG 中 SOS 之前的所有段。

    Returns:
        ``[(marker, start, end)]``，end 为下一段的起点。
    """
    segments: list[tuple[int, int, int]] = []
    i, n = 2, len(data)
    while i + 1 < n:
        if data[i] != 0xFF:
            break
        marker = data[i + 1]
        if marker == 0xFF:  # 填充字节
            i += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            segments.append((marker, i, i + 2))
            i += 2
            continue
        if marker in (0xD9, 0xDA):  # EOI / SOS：后面是熵编码数据
            break
        if i + 4 > n:
            break
        seg_len = int.from_bytes(data[i + 2 : i + 4], "big")
        if seg_len < 2 or i + 2 + seg_len > n:
            break
        segments.append((marker, i, i + 2 + seg_len))
        i += 2 + seg_len
    return segments


def _is_xmp_app1(data: bytes, start: int) -> bool:
    head = data[start + 4 : start + 4 + len(XMP_NAMESPACE)]
    return head == XMP_NAMESPACE


def _strip_xmp_app1(data: bytes) -> bytes:
    """移除已有的 XMP APP1 段，保证重复构建时不会叠加。"""
    segments = _head_segments(data)
    if not any(m == 0xE1 and _is_xmp_app1(data, s) for m, s, _ in segments):
        return data
    out = bytearray(data[:2])
    for marker, start, end in segments:
        if marker == 0xE1 and _is_xmp_app1(data, start):
            continue
        out += data[start:end]
    tail_start = segments[-1][2] if segments else 2
    out += data[tail_start:]
    return bytes(out)


def _insert_xmp_app1(data: bytes, payload: bytes) -> bytes:
    """把 XMP 作为 APP1 段插入。

    插入位置在所有前置 APPn/COM 段之后（即 APP0/JFIF 之后、DQT 之前），
    这样既能保持 JFIF 头在最前，也满足 EXIF/XMP 的常规布局。
    """
    if len(payload) + 2 > 0xFFFF:
        raise ValueError("XMP 过大，无法放入单个 APP1 段")

    segments = _head_segments(data)
    insert_at = 2
    for marker, _start, end in segments:
        if marker == 0xFE or 0xE0 <= marker <= 0xEF:
            insert_at = end
        else:
            break

    segment = b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload
    return data[:insert_at] + segment + data[insert_at:]


def build_motion_photo(
    still: bytes,
    video: bytes,
    presentation_ts_us: int = 0,
) -> bytes:
    """把主图 JPEG 与视频 MP4 合成单文件动态照片。

    Raises:
        ValueError: 主图不是 JPEG，或视频不是 MP4/MOV。
    """
    if not still.startswith(_JPEG_SOI):
        raise ValueError("主图不是 JPEG 数据")
    if len(video) < 12 or video[4:8] != b"ftyp":
        raise ValueError("视频不是 MP4/MOV 数据")

    xmp = build_xmp(len(video), presentation_ts_us)
    head = _insert_xmp_app1(_strip_xmp_app1(still), XMP_NAMESPACE + xmp)
    return head + video


def find_motion_photo_offset(data: bytes) -> int | None:
    """从 XMP 中解析出尾部视频的起点偏移；不是动态照片时返回 None。"""
    marker = b"GCamera:MicroVideoOffset=\""
    idx = data.find(marker)
    if idx < 0:
        return None
    start = idx + len(marker)
    end = data.find(b'"', start)
    if end < 0:
        return None
    try:
        offset = int(data[start:end])
    except ValueError:
        return None
    if offset <= 0 or offset > len(data):
        return None
    return len(data) - offset


def _detect_video_codec(data: bytes) -> str | None:
    """粗略判断视频编码：``"h264"`` / ``"hevc"`` / ``None``（无法判断）。"""
    window = data[:_CODEC_SCAN_LIMIT]
    if any(fourcc in window for fourcc in _HEVC_FOURCCS):
        return "hevc"
    if any(fourcc in window for fourcc in _AVC_FOURCCS):
        return "h264"
    return None


async def _transcode_to_h264(video_path: Path) -> Path:
    """把视频转成兼容性最好的 H.264 + yuv420p，供相册侧解码。"""
    from .utils import exec_ffmpeg_cmd, safe_unlink

    output_path = video_path.with_name(f"{video_path.stem}_h264{video_path.suffix}")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(output_path),
    ]
    await exec_ffmpeg_cmd(cmd)
    await safe_unlink(video_path)
    return output_path


async def create_motion_photo(
    still_path: Path,
    video_path: Path,
    output_path: Path,
    *,
    presentation_ts_us: int = 0,
    transcode_hevc: bool = True,
) -> Path:
    """由主图与视频文件生成单文件动态照片，返回输出路径。

    合成过程本身不需要 ffmpeg；仅当视频是 HEVC 且系统装了 ffmpeg 时才转码一次
    （HEVC-in-MP4 在多数相册上无法播放）。
    """
    still = await asyncio.to_thread(still_path.read_bytes)
    video = await asyncio.to_thread(video_path.read_bytes)

    if transcode_hevc and _detect_video_codec(video) == "hevc":
        logger.info("实况照片视频为 HEVC，转码为 H.264 以提升相册兼容性")
        try:
            transcoded = await _transcode_to_h264(video_path)
            video = await asyncio.to_thread(transcoded.read_bytes)
        except Exception as e:
            logger.warning(f"HEVC 转码失败，沿用原始视频: {e}")

    data = build_motion_photo(still, video, presentation_ts_us)

    offset = find_motion_photo_offset(data)
    if offset is None or data[offset + 4 : offset + 8] != b"ftyp":
        raise ValueError("动态照片自校验失败：尾部视频偏移不正确")

    await asyncio.to_thread(output_path.write_bytes, data)
    logger.info(
        f"实况照片已生成: {output_path.name} "
        f"(主图 {len(still) / 1024:.0f} KB + 视频 {len(video) / 1024:.0f} KB)"
    )
    return output_path
