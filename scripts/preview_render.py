"""解析卡片渲染预览脚本（一次性，不随插件加载）

用法：
    python scripts/preview_render.py [输出目录]

用程序生成的测试图构造 5 类代表性样例，分别以 dark / light 主题渲染，
共输出 10 张 PNG 供样式确认。
"""

from __future__ import annotations

import asyncio
import math
import sys
import types
from datetime import datetime
from pathlib import Path

# ---- mock astrbot.api（预览环境无 AstrBot） ----
if "astrbot" not in sys.modules:
    import logging

    logging.basicConfig(level=logging.WARNING)
    _logger = logging.getLogger("preview")
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api.logger = _logger
    astrbot.api = api
    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from core.data import Author, ImageContent, ParseResult, Platform, VideoContent  # noqa: E402
from core.render import ShareCardRenderer  # noqa: E402
from core.task import PathTask  # noqa: E402

OUT_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else PLUGIN_ROOT / "scripts" / "preview_out"
ASSET_DIR = OUT_DIR / "assets"


# ---------------- 测试图生成 ----------------


def _vgrad(size, c1, c2):
    w, h = size
    img = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        img.putpixel((0, y), tuple(round(c1[i] + (c2[i] - c1[i]) * t) for i in range(3)))
    return img.resize((w, h))


def make_hero(path: Path, seed: int = 0):
    w, h = 1280, 720
    palettes = [
        ((64, 90, 190), (170, 80, 160)),
        ((20, 160, 170), (40, 60, 140)),
        ((230, 120, 60), (160, 40, 90)),
    ]
    c1, c2 = palettes[seed % len(palettes)]
    img = _vgrad((w, h), c1, c2)
    d = ImageDraw.Draw(img, "RGBA")
    for i in range(6):
        r = 60 + i * 30
        x = 200 + (i * 173 + seed * 90) % (w - 200)
        y = 150 + (i * 211 + seed * 60) % (h - 250)
        d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, 26))
    d.rectangle((0, h - 160, w, h), fill=(0, 0, 0, 40))
    img.save(path)


def make_avatar(path: Path, seed: int = 0):
    size = 256
    c1 = (250, 140, 160) if seed % 2 == 0 else (90, 160, 240)
    c2 = (130, 70, 190) if seed % 2 == 0 else (40, 90, 170)
    img = _vgrad((size, size), c1, c2)
    d = ImageDraw.Draw(img, "RGBA")
    d.ellipse((64, 70, 192, 198), fill=(255, 255, 255, 200))
    d.ellipse((104, 108, 152, 156), fill=(60, 60, 80, 255))
    img.save(path)


def make_grid(path: Path, seed: int):
    size = 480
    hue = (seed * 47) % 360
    # 简单 HSV->RGB
    import colorsys

    c1 = tuple(round(v * 255) for v in colorsys.hsv_to_rgb(hue / 360, 0.55, 0.92))
    c2 = tuple(round(v * 255) for v in colorsys.hsv_to_rgb(((hue + 60) % 360) / 360, 0.6, 0.75))
    img = _vgrad((size, size), c1, c2)
    d = ImageDraw.Draw(img, "RGBA")
    for i in range(4):
        off = i * 46
        d.arc((60 + off, 60 + off, size - 60 - off, size - 60 - off), 0, 300, fill=(255, 255, 255, 90), width=10)
    img.save(path)


# ---------------- 样例构造 ----------------


async def _p(path: Path) -> Path:
    return path


def task(path: Path) -> PathTask:
    return PathTask(_p(path))


def build_samples() -> list[tuple[str, ParseResult]]:
    now = int(datetime.now().timestamp())
    samples: list[tuple[str, ParseResult]] = []

    # 1. B站视频：横幅 + 播放按钮 + 统计 + 在线人数
    samples.append((
        "bilibili-video",
        ParseResult(
            platform=Platform("bilibili", "哔哩哔哩"),
            author=Author("影视飓风", avatar=task(ASSET_DIR / "avatar.png"), description="无限进步 · 科技美学"),
            title="【8K】我们拍到了极光爆发！这趟冰岛之旅值了",
            text="历时两周的冰岛拍摄终于成片，8K HDR 记录下了极光爆发的全过程。幕后花絮和拍摄参数都在视频里，记得一键三连支持一下！",
            timestamp=now,
            url="https://www.bilibili.com/video/BV1xx411c7mD",
            contents=[VideoContent(task(ASSET_DIR / "hero0.png"), cover=task(ASSET_DIR / "hero0.png"), duration=754)],
            extra={
                "stats_line": "👍 12.3万 🪙 4.5万 ⭐ 2.1万 💬 3.2千 👀 105.8万",
                "duration": "12:34",
                "online": "🏄 1.2万人正在观看",
                "content_type": "视频",
            },
        ),
    ))

    # 2. 小红书图文：7 张图（网格 6 + +N）
    samples.append((
        "xhs-gallery",
        ParseResult(
            platform=Platform("xiaohongshu", "小红书"),
            author=Author("桃子味汽水", avatar=task(ASSET_DIR / "avatar1.png"), description="分享生活的小美好"),
            title="周末 City Walk｜这条老街太好拍了吧",
            text="发现一条宝藏老街，咖啡香、猫、还有满墙的爬山虎。整理了 7 个机位给大家，建议傍晚去，光线绝绝子～",
            timestamp=now - 7200,
            url="https://www.xiaohongshu.com/explore/64f0abcd1234",
            graphics=[ImageContent(task(ASSET_DIR / f"g{i}.png")) for i in range(7)],
            extra={"content_type": "图文", "is_video": False},
        ),
    ))

    # 3. 微博转发：无图纯文本 + 引用卡片
    samples.append((
        "weibo-repost",
        ParseResult(
            platform=Platform("weibo", "微博"),
            author=Author("科技圈那点事", avatar=task(ASSET_DIR / "avatar.png"), description="专注科技资讯"),
            title=None,
            text="这个方向确实值得关注，端侧推理的成本已经降到去年的十分之一了，明年大概率会看到一波应用爆发。",
            timestamp=now - 3600,
            url="https://weibo.com/1887344341/PeExample",
            repost=ParseResult(
                platform=Platform("weibo", "微博"),
                author=Author("量子位", avatar=None),
                title=None,
                text="刚刚：某厂发布新一代端侧大模型，7B 参数在手机上实现 30 tokens/s 推理速度，功耗下降 40%。这意味着手机本地跑 AI 助手真正可用了。",
                timestamp=now - 5400,
                url="https://weibo.com/6105753431/QbitAI",
            ),
            extra={"content_type": "动态"},
        ),
    ))

    # 4. 抖音视频（无封面）：纯文本头部 + 无横幅
    samples.append((
        "douyin-nocover",
        ParseResult(
            platform=Platform("douyin", "抖音"),
            author=Author("街头摄影老王", avatar=task(ASSET_DIR / "avatar1.png"), description=None),
            title="凌晨四点的菜市场，藏着这座城市最真实的样子",
            text="跟拍了三个月，剪出这条 3 分钟的片子。每一个认真生活的人都值得被看见。",
            timestamp=now - 86400,
            url="https://www.douyin.com/video/7412345678901234567",
            contents=[VideoContent(task(ASSET_DIR / "video.mp4"), cover=None, duration=180)],
            extra={"content_type": "视频"},
        ),
    ))

    # 5. 单图图文：1 张大图网格（首图升为横幅）
    samples.append((
        "single-image",
        ParseResult(
            platform=Platform("twitter", "Twitter / X"),
            author=Author("Design Weekly", avatar=task(ASSET_DIR / "avatar.png"), description="Weekly design inspiration"),
            title="This week's UI trend: glassmorphism is back",
            text="Glass cards, soft gradients and generous whitespace are everywhere again. Here is a curated collection of 20 examples.",
            timestamp=now - 172800,
            url="https://twitter.com/designweekly/status/1789012345678",
            graphics=[ImageContent(task(ASSET_DIR / "hero1.png"))],
            extra={"content_type": "图文"},
        ),
    ))
    return samples


async def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    make_hero(ASSET_DIR / "hero0.png", 0)
    make_hero(ASSET_DIR / "hero1.png", 1)
    make_avatar(ASSET_DIR / "avatar.png", 0)
    make_avatar(ASSET_DIR / "avatar1.png", 1)
    for i in range(7):
        make_grid(ASSET_DIR / f"g{i}.png", i)

    samples = build_samples()
    for theme in ("dark", "light"):
        renderer = ShareCardRenderer(OUT_DIR, width=800, theme=theme)
        for idx, (slug, res) in enumerate(samples):
            out = await renderer.render(res, cache_key=f"preview-{theme}-{idx}-{slug}")
            print(f"[{theme}] {slug}: {out}")
    print(f"\n输出目录: {OUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
