"""全布局 × 全类型 渲染回归与预览（一次性脚本）

使用插件内置 ShareCardRenderer(layout=...) 渲染
4 布局 × dark/light × 5 类样例（B站视频 / 小红书多图 / 微博转发 / 抖音无封面 / 单图），
共 40 张 PNG，验证各解析结果类型在所有布局下均正常。
"""

from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime
from pathlib import Path

if "astrbot" not in sys.modules:
    import logging

    logging.basicConfig(level=logging.WARNING)
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api.logger = logging.getLogger("layouts")
    astrbot.api = api
    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))

from core.data import Author, ImageContent, ParseResult, Platform, VideoContent  # noqa: E402
from core.render import LAYOUT_NAMES, ShareCardRenderer  # noqa: E402
from core.task import PathTask  # noqa: E402

OUT_DIR = PLUGIN_ROOT / "scripts" / "preview_out" / "layouts"
ASSET_DIR = PLUGIN_ROOT / "scripts" / "preview_out" / "assets"


async def _p(path: Path) -> Path:
    return path


def task(path: Path) -> PathTask:
    return PathTask(_p(path))


def build_samples() -> list[tuple[str, ParseResult]]:
    now = int(datetime.now().timestamp())
    return [
        ("bilibili-video", ParseResult(
            platform=Platform("bilibili", "哔哩哔哩"),
            author=Author("影视飓风", avatar=task(ASSET_DIR / "avatar.png"), description="无限进步 · 科技美学"),
            title="【8K】我们拍到了极光爆发！这趟冰岛之旅值了",
            text="历时两周的冰岛拍摄终于成片，8K HDR 记录下了极光爆发的全过程。幕后花絮和拍摄参数都在视频里，记得一键三连支持一下！",
            timestamp=now,
            url="https://www.bilibili.com/video/BV1xx411c7mD",
            contents=[VideoContent(task(ASSET_DIR / "hero0.png"), cover=task(ASSET_DIR / "hero0.png"), duration=754)],
            extra={"stats_line": "👍 12.3万 🪙 4.5万 ⭐ 2.1万 💬 3.2千 👀 105.8万",
                   "duration": "12:34", "online": "🏄 1.2万人正在观看", "content_type": "视频"},
        )),
        ("xhs-gallery", ParseResult(
            platform=Platform("xiaohongshu", "小红书"),
            author=Author("桃子味汽水", avatar=task(ASSET_DIR / "avatar1.png"), description="分享生活的小美好"),
            title="周末 City Walk｜这条老街太好拍了吧",
            text="发现一条宝藏老街，咖啡香、猫、还有满墙的爬山虎。整理了 7 个机位给大家，建议傍晚去，光线绝绝子～",
            timestamp=now - 7200,
            url="https://www.xiaohongshu.com/explore/64f0abcd1234",
            graphics=[ImageContent(task(ASSET_DIR / f"g{i}.png")) for i in range(7)],
            extra={"content_type": "图文", "is_video": False},
        )),
        ("weibo-repost", ParseResult(
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
                text="刚刚：某厂发布新一代端侧大模型，7B 参数在手机上实现 30 tokens/s 推理速度，功耗下降 40%。",
                timestamp=now - 5400,
                url="https://weibo.com/6105753431/QbitAI",
            ),
            extra={"content_type": "动态"},
        )),
        ("douyin-nocover", ParseResult(
            platform=Platform("douyin", "抖音"),
            author=Author("街头摄影老王", avatar=task(ASSET_DIR / "avatar1.png"), description=None),
            title="凌晨四点的菜市场，藏着这座城市最真实的样子",
            text="跟拍了三个月，剪出这条 3 分钟的片子。每一个认真生活的人都值得被看见。",
            timestamp=now - 86400,
            url="https://www.douyin.com/video/7412345678901234567",
            contents=[VideoContent(task(ASSET_DIR / "video.mp4"), cover=None, duration=180)],
            extra={"content_type": "视频"},
        )),
        ("single-image", ParseResult(
            platform=Platform("twitter", "Twitter / X"),
            author=Author("Design Weekly", avatar=task(ASSET_DIR / "avatar.png"), description="Weekly design inspiration"),
            title="This week's UI trend: glassmorphism is back",
            text="Glass cards, soft gradients and generous whitespace are everywhere again.",
            timestamp=now - 172800,
            url="https://twitter.com/designweekly/status/1789012345678",
            graphics=[ImageContent(task(ASSET_DIR / "hero1.png"))],
            extra={"content_type": "图文"},
        )),
        ("video-limit-warning", ParseResult(
            platform=Platform("bilibili", "哔哩哔哩"),
            author=Author("长视频纪录片", avatar=task(ASSET_DIR / "avatar.png"), description="纪录片官方频道"),
            title="【4K】4小时深度纪录片：探索深海未解之谜",
            text="本集将带你深入马里亚纳海沟，记录人类从未触及的神秘世界...",
            timestamp=now - 3600,
            url="https://www.bilibili.com/video/BV1overduration",
            contents=[VideoContent(task(ASSET_DIR / "hero0.png"), cover=task(ASSET_DIR / "hero0.png"), duration=14400)],
            extra={
                "stats_line": "👍 50.2万 🪙 30.1万 ⭐ 40.5万 💬 1.8万 👀 350.2万",
                "duration": "04:00:00",
                "content_type": "视频",
                "limit_warnings": ["⚠️ 视频时长(04:00:00)超过限制(00:30:00)，不会下载视频"],
            },
        )),
    ]


async def main() -> None:
    samples = build_samples()
    total = 0
    for layout in LAYOUT_NAMES:
        for theme in ("dark", "light"):
            renderer = ShareCardRenderer(OUT_DIR, width=800, theme=theme, layout=layout)
            for slug, res in samples:
                out = await renderer.render(res, cache_key=f"lay2-{layout}-{theme}-{slug}")
                assert out and out.exists(), (layout, theme, slug)
                total += 1
                print(f"[{layout}/{theme}] {slug}: {out.name}")
    print(f"\n共渲染 {total} 张，全部成功")


if __name__ == "__main__":
    asyncio.run(main())
