"""完整主题方案对比预览（一次性脚本）

向 _THEMES 注入 4 套完整主题（不修改 render.py），
用同一张 B 站视频样例卡渲染对比效果。
"""

from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime
from pathlib import Path

if "astrbot" not in sys.modules:
    import logging

    logging.basicConfig(level=logging.CRITICAL)
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api.logger = logging.getLogger("themes")
    astrbot.api = api
    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))

from core.data import Author, ParseResult, Platform, VideoContent  # noqa: E402
from core.render import ShareCardRenderer, _Theme, _THEMES  # noqa: E402
from core.task import PathTask  # noqa: E402

OUT_DIR = PLUGIN_ROOT / "scripts" / "preview_out" / "themes"
ASSET_DIR = PLUGIN_ROOT / "scripts" / "preview_out" / "assets"

# ---------- 注入 4 套完整主题 ----------

_THEMES["obsidian"] = _Theme(  # 曜石：当前默认深色毛玻璃（对照组）
    gradient_top="#242B3F", gradient_bottom="#12161F",
    border="#FFFFFF",
    text_primary="#F5F7FC", text_secondary="#AEB6C8", text_tertiary="#7B8598",
    pill_bg="#FFFFFF", quote_bg="#FFFFFF", divider="#FFFFFF",
    shadow_alpha=130, stat_pill_bg="#FFFFFF",
    glow_alpha=30, frost_alpha=14, frost_border_alpha=26, border_alpha=24,
    placeholder_top=(44, 51, 71), placeholder_bottom=(20, 24, 35),
)

_THEMES["mist"] = _Theme(  # 雾白：极简纸感，去光晕，发丝边框
    gradient_top="#FFFFFF", gradient_bottom="#F7F8FA",
    border="#161B26",
    text_primary="#161B26", text_secondary="#4A5468", text_tertiary="#8E96A8",
    pill_bg="#161B26", quote_bg="#161B26", divider="#161B26",
    shadow_alpha=45, stat_pill_bg="#161B26",
    glow_alpha=0, frost_alpha=7, frost_border_alpha=28, border_alpha=18,
    placeholder_top=(232, 235, 240), placeholder_bottom=(244, 246, 249),
)

_THEMES["neon"] = _Theme(  # 霓虹：深紫黑 + 高强度品牌色光晕
    gradient_top="#1A1230", gradient_bottom="#0A0B12",
    border="#FFFFFF",
    text_primary="#F6F4FF", text_secondary="#B5B0CE", text_tertiary="#7E7899",
    pill_bg="#FFFFFF", quote_bg="#FFFFFF", divider="#FFFFFF",
    shadow_alpha=140, stat_pill_bg="#FFFFFF",
    glow_alpha=62, frost_alpha=18, frost_border_alpha=36, border_alpha=30,
    placeholder_top=(56, 42, 92), placeholder_bottom=(18, 16, 32),
)

_THEMES["cream"] = _Theme(  # 奶油：暖米白，温润浅色系
    gradient_top="#FFFBF4", gradient_bottom="#FAEEDF",
    border="#2E241A",
    text_primary="#2E241A", text_secondary="#6B5D4C", text_tertiary="#9A8C78",
    pill_bg="#2E241A", quote_bg="#2E241A", divider="#2E241A",
    shadow_alpha=50, stat_pill_bg="#2E241A",
    glow_alpha=24, frost_alpha=9, frost_border_alpha=24, border_alpha=16,
    placeholder_top=(240, 228, 210), placeholder_bottom=(247, 238, 226),
)


async def _p(path: Path) -> Path:
    return path


def task(path: Path) -> PathTask:
    return PathTask(_p(path))


async def main() -> None:
    now = int(datetime.now().timestamp())
    sample = ParseResult(
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
    )
    # 无图样例（检验纯文本头部与引用块在各主题下的表现）
    text_sample = ParseResult(
        platform=Platform("weibo", "微博"),
        author=Author("科技圈那点事", avatar=task(ASSET_DIR / "avatar1.png"), description="专注科技资讯"),
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
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for theme in ("obsidian", "mist", "neon", "cream"):
        r = ShareCardRenderer(OUT_DIR, width=800, theme=theme)
        p1 = await r.render(sample, cache_key=f"theme-{theme}-video-v2")
        p2 = await r.render(text_sample, cache_key=f"theme-{theme}-text-v2")
        print(f"[{theme}] {p1.name} / {p2.name}")


if __name__ == "__main__":
    asyncio.run(main())
