# -*- coding: utf-8 -*-
"""本地验证：颜文字字体回退渲染效果（无需安装 astrbot，stub 掉其 logger）"""
import sys
import types
import asyncio
import logging
from pathlib import Path

# ---- stub astrbot.api.logger，使 render.py 可独立导入 ----
astrbot = types.ModuleType("astrbot")
api = types.ModuleType("astrbot.api")
api.logger = logging.getLogger("astrbot")
astrbot.api = api
sys.modules["astrbot"] = astrbot
sys.modules["astrbot.api"] = api

PLUGIN_DIR = Path(r"C:\Users\84637\Desktop\code\astrbot_plugin_rika_share")
sys.path.insert(0, str(PLUGIN_DIR.parent))

from astrbot_plugin_rika_share.core.render import ShareCardRenderer  # noqa: E402
from astrbot_plugin_rika_share.core.data import ParseResult, Platform, Author  # noqa: E402

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")


def make_result(title: str, text: str) -> ParseResult:
    return ParseResult(
        platform=Platform("xiaohongshu", "小红书"),
        url="https://www.xiaohongshu.com/explore/abc123",
        title=title,
        text=text,
        timestamp=1755864000,
        author=Author(
            name="散场电影票根",
            description="胶片收藏 / 城市漫游",
        ),
        extra={"stats_line": "❤ 1.2万 💬 856 ⭐ 3200", "content_type": "图文"},
    )


async def main() -> None:
    out_dir = PLUGIN_DIR / "scripts" / "previews"
    out_dir.mkdir(parents=True, exist_ok=True)

    title = "៸៸᳐⦁⩊⦁៸៸᳐ ੭ﾞ 周末治愈日常 ᯠ_ ̫ _ᯄ"
    text = (
        "今天也在好好生活 ៸៸᳐⦁⩊⦁៸៸᳐ ੭ﾞ\n"
        "/ᐠ .⸝⸝⸝⸝⸝ ᐠ\\ﾞ 和猫猫度过的下午 ☕️\n"
        "ᯠ_ ̫ _ᯄ 碎碎念：喜欢的话记得点赞收藏呀 ♡\n"
        "⌯'ㅅ'⌯ (๑˃ᴗ˂)ﻭ ˬˬˊ˗\n"
        "存下口令，前往【小红书】发现惊喜~"
    )

    for theme in ("dark", "light"):
        renderer = ShareCardRenderer(
            out_dir,
            enabled=True,
            width=800,
            theme=theme,
            layout="standard",
        )
        result = make_result(title, text)
        path = await renderer.render(result, cache_key=f"kaomoji_test_{theme}")
        print(f"[{theme}] -> {path}")

    print("\n回退字体链:")
    r = ShareCardRenderer(out_dir, enabled=True)
    r._font(20)  # 触发字体加载
    for p, cmap in r._load_fallbacks():
        print(f"  {p}  ({len(cmap)} 码点)")


if __name__ == "__main__":
    asyncio.run(main())
