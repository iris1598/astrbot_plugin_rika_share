"""全部卡片样式 × 全类型 渲染回归与文档预览图生成脚本。

默认把所有样式 × dark/light × 全尺寸 × 6 类样例输出到 ``scripts/.out/layouts/``；
传入 ``--export-docs`` 时额外导出清晰无缺字的展示图到 ``docs/previews/``。
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path
import shutil
import sys
import types

if "astrbot" not in sys.modules:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from dev_logger import StubLogger

    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api.logger = StubLogger("layouts", level="WARNING")
    astrbot.api = api
    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))

from link_parser.models import Author, ImageContent, ParseResult, Platform, VideoContent  # noqa: E402
from link_parser.services.card_render import ShareCardRenderer, iter_styles, style_names  # noqa: E402
from link_parser.services.card_render.preview import (  # noqa: E402
    _StaticPathTask,
    build_preview_sample,
    ensure_preview_assets,
)
from link_parser.services.card_render.theme import Image, ImageDraw, LANCZOS  # noqa: E402
from link_parser.services.card_render.toolkit import FontBook  # noqa: E402

OUT_DIR = PLUGIN_ROOT / "scripts" / ".out" / "layouts"
ASSET_DIR = PLUGIN_ROOT / "scripts" / ".out" / "assets"
DOCS_PREVIEW_DIR = PLUGIN_ROOT / "docs" / "previews"


def task(path: Path) -> _StaticPathTask:
    return _StaticPathTask(path)


def build_samples() -> list[tuple[str, ParseResult]]:
    ensure_preview_assets(ASSET_DIR)
    now = int(datetime.now().timestamp())
    return [
        build_preview_sample("video", ASSET_DIR),
        build_preview_sample("gallery", ASSET_DIR),
        build_preview_sample("repost", ASSET_DIR),
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


def _compose_overview(panels: list[tuple[str, str, Path]], target: Path) -> None:
    """将 4 张样式示例图拼接为带清晰中文字体标注的 2×2 总览图。"""
    if Image is None:
        return
    fonts = FontBook()
    col_w = 560
    pad_x = 32
    pad_y = 32
    gap = 28
    label_h = 36

    thumbs: list[tuple[str, Image.Image]] = []
    for key, title, path in panels[:4]:
        with Image.open(path) as im:
            im.load()
            rgba = im.convert("RGBA")
        scale = col_w / rgba.width
        resized = rgba.resize((col_w, round(rgba.height * scale)), LANCZOS)
        thumbs.append((f"{key} · {title}", resized))

    left_h = max(thumbs[0][1].height, thumbs[1][1].height) + label_h
    right_h = max(thumbs[2][1].height, thumbs[3][1].height) + label_h
    canvas_w = pad_x * 2 + col_w * 2 + gap
    canvas_h = pad_y * 2 + left_h + gap + right_h
    canvas = Image.new("RGB", (canvas_w, canvas_h), (16, 19, 27))
    draw = ImageDraw.Draw(canvas)

    for idx, (caption, img) in enumerate(thumbs):
        r, c = divmod(idx, 2)
        x = pad_x + c * (col_w + gap)
        y = pad_y + (0 if r == 0 else left_h + gap)
        canvas.paste(img.convert("RGB"), (x, y), img.split()[3])
        fonts.draw_text(
            draw,
            (x + 8, y + img.height + 10),
            caption,
            size=20,
            fill="#cbd5e1",
            bold=True,
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, "PNG", optimize=True)


async def export_docs_previews() -> None:
    """导出清晰、无缺字的 docs/previews/ 示例与总览图。"""
    ensure_preview_assets(ASSET_DIR)
    DOCS_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    _, video_res = build_preview_sample("video", ASSET_DIR)
    tmp_dir = PLUGIN_ROOT / "scripts" / ".out" / "docs_tmp"
    shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    panels: list[tuple[str, str, Path]] = []
    for spec in iter_styles():
        renderer = ShareCardRenderer(tmp_dir, width=800, theme="dark", style=spec.name)
        rendered = await renderer.render(video_res, cache_key=f"doc-{spec.name}-dark")
        assert rendered and rendered.exists(), spec.name
        dest = DOCS_PREVIEW_DIR / f"layout-{spec.name}-dark.png"
        shutil.copy2(rendered, dest)
        panels.append((spec.name, spec.display_name, dest))
        print(f"[docs/previews] 导出 {dest.name}")

    light_renderer = ShareCardRenderer(tmp_dir, width=800, theme="light", style="standard")
    light_rendered = await light_renderer.render(video_res, cache_key="doc-standard-light")
    assert light_rendered and light_rendered.exists()
    light_dest = DOCS_PREVIEW_DIR / "layout-standard-light.png"
    shutil.copy2(light_rendered, light_dest)
    print(f"[docs/previews] 导出 {light_dest.name}")

    overview_dest = DOCS_PREVIEW_DIR / "overview-layouts.png"
    _compose_overview(panels, overview_dest)
    print(f"[docs/previews] 合成 {overview_dest.name}")


async def run_matrix() -> None:
    ensure_preview_assets(ASSET_DIR)
    samples = build_samples()
    total = 0
    for style in style_names():
        for theme in ("dark", "light"):
            for full_size in (False, True):
                renderer = ShareCardRenderer(
                    OUT_DIR,
                    width=800,
                    theme=theme,
                    style=style,
                    cover_full_size=full_size,
                )
                for slug, res in samples:
                    out = await renderer.render(
                        res, cache_key=f"style-{style}-{theme}-full{full_size}-{slug}"
                    )
                    assert out and out.exists(), (style, theme, full_size, slug)
                    total += 1
                    print(f"[{style}/{theme}/full={full_size}] {slug}: {out.name}")
    print(f"\n共渲染 {total} 张，全部成功")


async def main() -> None:
    parser = argparse.ArgumentParser(description="卡片渲染回归与文档预览导出")
    parser.add_argument(
        "--export-docs",
        action="store_true",
        help="仅生成 docs/previews/ 下的最新样式预览与总览图",
    )
    args = parser.parse_args()
    if args.export_docs:
        await export_docs_previews()
    else:
        await run_matrix()


if __name__ == "__main__":
    asyncio.run(main())
