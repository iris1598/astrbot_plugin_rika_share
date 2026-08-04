"""水印样式对比预览（一次性脚本）

在 dark / light 两种卡片底色上渲染 6 种「莉卡解析」页脚水印方案，
输出一张对比图供挑选。A 为当前 render.py 默认（小圆点）。
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

if "astrbot" not in sys.modules:
    import logging

    logging.basicConfig(level=logging.CRITICAL)
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api.logger = logging.getLogger("wm")
    astrbot.api = api
    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from core.render import ShareCardRenderer, _THEMES, _hex_to_rgb  # noqa: E402

OUT = PLUGIN_ROOT / "scripts" / "preview_out" / "watermark_variants.png"
ACCENT = _hex_to_rgb("#FB7299")  # 以哔哩哔哩粉为示例强调色
TEXT = "莉卡解析"
W = 800
ROW_H = 64
VARIANTS = ["A", "B", "C", "D", "E", "F"]


def draw_variant(r: ShareCardRenderer, canvas: Image.Image, draw: ImageDraw.ImageDraw,
                 variant: str, cx_right: int, cy: int, theme) -> None:
    """在 (cx_right 右对齐, cy 垂直居中) 处绘制一种水印方案。"""
    font = r._font(20, bold=True)
    text_w = r._text_width(TEXT, font)
    lh = r._line_height(font)
    top = cy - lh // 2

    if variant == "A":  # 小圆点 + 文字（当前默认）
        d = 10
        x = cx_right - (d + 8 + text_w)
        draw.ellipse((x, cy - d // 2, x + d, cy + d // 2), fill=(*ACCENT, 255))
        r._draw_text(draw, (x + d + 8, top), TEXT, 20, ACCENT, bold=True)

    elif variant == "B":  # 圆环 + 文字
        d = 12
        x = cx_right - (d + 8 + text_w)
        draw.ellipse((x, cy - d // 2, x + d, cy + d // 2),
                     outline=(*ACCENT, 255), width=2)
        r._draw_text(draw, (x + d + 8, top), TEXT, 20, ACCENT, bold=True)

    elif variant == "C":  # 文字 + accent 短下划线
        x = cx_right - text_w
        r._draw_text(draw, (x, top), TEXT, 20, theme.text_primary, bold=True)
        bar_y = top + lh + 2
        draw.rounded_rectangle((x, bar_y, x + text_w, bar_y + 4), radius=2,
                               fill=(*ACCENT, 255))

    elif variant == "D":  # accent 描边药丸
        pad_x, pad_y = 14, 6
        tw, th = text_w + pad_x * 2, lh + pad_y * 2
        x = cx_right - tw
        draw.rounded_rectangle((x, cy - th // 2, x + tw, cy + th // 2),
                               radius=th // 2, outline=(*ACCENT, 220), width=2)
        r._draw_text(draw, (x + pad_x, cy - lh // 2), TEXT, 20, ACCENT, bold=True)

    elif variant == "E":  # 四角星 + 文字
        rr = 9
        x = cx_right - (rr * 2 + 8 + text_w)
        cx, cyc = x + rr, cy
        k = 0.30
        draw.polygon(
            [(cx, cyc - rr), (cx + rr * k, cyc - rr * k), (cx + rr, cyc),
             (cx + rr * k, cyc + rr * k), (cx, cyc + rr), (cx - rr * k, cyc + rr * k),
             (cx - rr, cyc), (cx - rr * k, cyc - rr * k)],
            fill=(*ACCENT, 255),
        )
        r._draw_text(draw, (x + rr * 2 + 8, top), TEXT, 20, ACCENT, bold=True)

    elif variant == "F":  # 双色文字：「莉卡」accent + 「解析」弱化
        w1 = r._text_width("莉卡", font)
        x = cx_right - (w1 + r._text_width("解析", font))
        r._draw_text(draw, (x, top), "莉卡", 20, ACCENT, bold=True)
        r._draw_text(draw, (x + w1, top), "解析", 20, theme.text_tertiary, bold=True)


def main() -> None:
    r = ShareCardRenderer(PLUGIN_ROOT / "scripts" / "preview_out", width=800)
    label_font = r._font(18, bold=True)
    sec_font = r._font(22, bold=True)

    section_h = 40 + len(VARIANTS) * ROW_H + 20
    H = section_h * 2
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))

    for si, theme_name in enumerate(("dark", "light")):
        theme = _THEMES[theme_name]
        y0 = si * section_h
        # 模拟卡片底：垂直渐变 + 品牌色光晕
        bg = r._gradient((W, section_h), theme.gradient_top, theme.gradient_bottom)
        canvas.paste(bg, (0, y0))
        glow = r._radial_glow(W, round(W * 0.9), ACCENT, theme.glow_alpha)
        canvas.alpha_composite(glow, (0, y0))
        draw = ImageDraw.Draw(canvas)
        r._draw_text(draw, (44, y0 + 16), theme_name.upper(), 22,
                     theme.text_tertiary, bold=True)
        for vi, v in enumerate(VARIANTS):
            cy = y0 + 40 + vi * ROW_H + ROW_H // 2
            # 分隔线
            line = Image.new("RGBA", (W - 88, 1), (0, 0, 0, 0))
            ImageDraw.Draw(line).line(
                (0, 0, W - 89, 0),
                fill=(*theme.divider, 14 if theme_name == "dark" else 12), width=1,
            )
            canvas.alpha_composite(line, (44, y0 + 40 + vi * ROW_H))
            r._draw_text(draw, (44, cy - r._line_height(label_font) // 2),
                         f"方案 {v}", 18, theme.text_tertiary, bold=True)
            draw_variant(r, canvas, draw, v, W - 44, cy, theme)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUT, "PNG", optimize=True)
    print(OUT)


if __name__ == "__main__":
    main()
