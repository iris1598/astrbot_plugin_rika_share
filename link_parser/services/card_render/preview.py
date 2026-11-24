"""卡片预览样例构造与离线资产管理（供 WebUI 实时预览与回归/文档图脚本复用）。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ...models import Author, ImageContent, ParseResult, Platform, VideoContent
from .theme import Image, ImageDraw

#: WebUI 下拉切换的内置预览样例清单
PREVIEW_SAMPLE_SPECS: tuple[dict[str, str], ...] = (
    {
        "id": "video",
        "label": "B站视频（横幅封面）",
        "description": "含视频封面、统计徽章、在线人数与作者简介，完整呈现横幅/沉浸等布局",
    },
    {
        "id": "gallery",
        "label": "小红书 7 图集",
        "description": "多图网格 + 作者信息 + 正文摘要，可测试图集裁切与排版差异",
    },
    {
        "id": "repost",
        "label": "微博转发（无图动态）",
        "description": "纯文本含转发引用块；选择「沉浸全屏」时可直观观察无图自动回退效果",
    },
)


class _StaticPathTask:
    """轻量静态路径替身：免创建未等待的 asyncio.Task，可在任意线程/事件循环复用。"""

    __slots__ = ("_path",)

    def __init__(self, path: Path):
        self._path = path

    async def get(self) -> Path:
        return self._path

    async def safe_get(self, on_error: Any = None) -> Path | None:  # noqa: ARG002
        return self._path if self._path.exists() else None


def _task(path: Path) -> Any:
    return _StaticPathTask(path)


def ensure_preview_assets(asset_dir: Path) -> Path:
    """在 ``asset_dir`` 下生成轻量离线的示例头像/封面/图集占位图。"""
    asset_dir.mkdir(parents=True, exist_ok=True)
    if Image is None or ImageDraw is None:
        return asset_dir

    def _make_gradient(
        name: str,
        size: tuple[int, int],
        top: tuple[int, int, int],
        bottom: tuple[int, int, int],
        *,
        accent: tuple[int, int, int] | None = None,
    ) -> None:
        target = asset_dir / name
        if target.exists():
            return
        w, h = size
        im = Image.new("RGBA", (w, h))
        draw = ImageDraw.Draw(im)
        for y in range(h):
            t = y / max(h - 1, 1)
            rgb = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
            draw.line([(0, y), (w, y)], fill=(*rgb, 255))
        if accent is not None:
            glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow)
            gd.ellipse(
                (round(w * 0.55), round(h * -0.15), round(w * 1.05), round(h * 0.65)),
                fill=(*accent, 88),
            )
            gd.ellipse(
                (round(w * -0.12), round(h * 0.45), round(w * 0.42), round(h * 1.15)),
                fill=(255, 255, 255, 34),
            )
            im.alpha_composite(glow)
        im.convert("RGB").save(target, "PNG")

    _make_gradient("avatar.png", (160, 160), (79, 70, 229), (14, 165, 233), accent=(236, 72, 153))
    _make_gradient("avatar1.png", (160, 160), (236, 72, 153), (245, 158, 11), accent=(255, 255, 255))
    _make_gradient("hero0.png", (1280, 720), (24, 48, 118), (13, 148, 136), accent=(129, 140, 248))
    _make_gradient("hero1.png", (1080, 810), (88, 28, 135), (219, 39, 119), accent=(251, 191, 36))
    for i in range(7):
        _make_gradient(
            f"g{i}.png",
            (640, 640),
            (46 + i * 24, 96 + i * 14, 198 - i * 16),
            (220 - i * 12, 110 + i * 12, 164),
            accent=(255, 255, 255),
        )
    dummy = asset_dir / "video.mp4"
    if not dummy.exists():
        dummy.write_bytes(b"")
    return asset_dir


def build_preview_sample(sample_id: str, asset_dir: Path) -> tuple[str, ParseResult]:
    """构建指定 ``sample_id`` 的离线 ``ParseResult`` 实例。"""
    ensure_preview_assets(asset_dir)
    now = int(datetime.now().timestamp())
    key = (sample_id or "video").strip().lower()

    if key == "gallery":
        return (
            "gallery",
            ParseResult(
                platform=Platform("xiaohongshu", "小红书"),
                author=Author(
                    "桃子味汽水",
                    avatar=_task(asset_dir / "avatar1.png"),
                    description="记录城市漫步与胶片日常",
                ),
                title="周末 City Walk｜这条老街也太出片了吧",
                text="咖啡香、窗台上的猫和爬满砖墙的植物。整理了 7 个适合傍晚顺光拍照的机位，大家路过可以收藏打卡。",
                timestamp=now - 5400,
                url="https://www.xiaohongshu.com/explore/64f0abcd1234",
                graphics=[ImageContent(_task(asset_dir / f"g{i}.png")) for i in range(7)],
                extra={"content_type": "图文", "is_video": False},
            ),
        )

    if key == "repost":
        return (
            "repost",
            ParseResult(
                platform=Platform("weibo", "微博"),
                author=Author(
                    "科技观察室",
                    avatar=_task(asset_dir / "avatar.png"),
                    description="关注端侧智能与产品设计",
                ),
                title=None,
                text="实测跨人格共享底卡缓存时，纯文本与转发引用块也能完美保持紧凑排版与自适应折行效果。",
                timestamp=now - 1800,
                url="https://weibo.com/1887344341/PeExample",
                repost=ParseResult(
                    platform=Platform("weibo", "微博"),
                    author=Author("开源周刊", avatar=None),
                    title=None,
                    text="本周亮点：端侧多模态卡片渲染耗时已优化至 30ms 以内，支持零侵入热插拔样式与主题。",
                    timestamp=now - 3600,
                    url="https://weibo.com/6105753431/OpenSource",
                ),
                extra={"content_type": "动态"},
            ),
        )

    return (
        "video",
        ParseResult(
            platform=Platform("bilibili", "哔哩哔哩"),
            author=Author(
                "极光影像志",
                avatar=_task(asset_dir / "avatar.png"),
                description="4K HDR 摄影 · 探索自然光影",
            ),
            title="【4K】跨越北极圈：我们在暴雪夜拍到了整片绿色极光爆发",
            text="历时两周的极地拍摄终于成片，记录零下三十度冰原上的极光磁暴，分P附完整延时摄影参数与器材清单。",
            timestamp=now,
            url="https://www.bilibili.com/video/BV1GJ411x7h7",
            contents=[
                VideoContent(
                    _task(asset_dir / "hero0.png"),
                    cover=_task(asset_dir / "hero0.png"),
                    duration=754,
                )
            ],
            extra={
                "stats_line": "👍 12.3万 🪙 4.5万 ⭐ 2.1万 💬 3.2千 👀 105.8万",
                "duration": "12:34",
                "online": "🏄 1.2万人正在观看",
                "content_type": "视频",
            },
        ),
    )


def preview_images_for(sample_id: str, asset_dir: Path) -> dict[str, Any]:
    """直接返回供同步测试或离线预热使用的本地图片路径字典。"""
    ensure_preview_assets(asset_dir)
    if sample_id == "gallery":
        return {
            "avatar": asset_dir / "avatar1.png",
            "hero": None,
            "grid": [asset_dir / f"g{i}.png" for i in range(7)],
        }
    if sample_id == "repost":
        return {"avatar": asset_dir / "avatar.png", "hero": None, "grid": []}
    return {
        "avatar": asset_dir / "avatar.png",
        "hero": asset_dir / "hero0.png",
        "grid": [],
    }
