"""西格莉卡（Sigrika）专属角色主题卡片样式。

灵感源自《鸣潮》角色「西格莉卡」与伴生「日灵」：
- 浅色「浮光林昼」：暖白羊皮纸底 + 活力橘金长辫色 + 浮光堇紫流苏渐变；
- 深色「星憩暮云」：深邃暮云靛紫底 + 浮光暖阳金辉 + 日灵青玉微光；
- 专属视觉纹样：机械四角风车星芒发饰徽记、日灵（Soliskin）小徽章、
  符文几何折线暗纹，以及「• • • ◇ ── ✦」星轨荆棘内框。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from astrbot.api import logger

from ..theme import (
    L,
    LANCZOS,
    Image,
    ImageDraw,
    ImageFilter,
    Theme,
    hex_to_rgb,
    mix,
    with_alpha,
)
from .base import CardStyle
from .registry import StyleSpec, register_style


# ============================ 西格莉卡专属双色板 ============================

_SIGRIKA_THEMES: dict[str, Theme] = {
    # 星憩暮云（Dark）：呼应小憩插画中的深邃暮云靛紫、暖橙发丝与日灵青玉荧光
    "dark": Theme(
        gradient_top="#241D3D",
        gradient_bottom="#130F24",
        border="#F6C86E",
        text_primary="#FAF6F0",
        text_secondary="#CBC2E0",
        text_tertiary="#9287B0",
        pill_bg="#E9E0FF",
        quote_bg="#E9E0FF",
        divider="#E8C06B",
        shadow_alpha=135,
        stat_pill_bg="#E9E0FF",
        glow_alpha=38,
        frost_alpha=18,
        frost_border_alpha=36,
        border_alpha=46,
        placeholder_top=(52, 41, 84),
        placeholder_bottom=(24, 19, 44),
        is_dark=True,
        divider_alpha=0,
    ),
    # 浮光林昼（Light）：呼应浮光林插画中的暖阳白兜帽、橘金星芒与浅堇紫织带
    "light": Theme(
        gradient_top="#FFFDF8",
        gradient_bottom="#F6EFE4",
        border="#8A6AD6",
        text_primary="#2A2038",
        text_secondary="#5B4D70",
        text_tertiary="#8D7EA3",
        pill_bg="#6B4FB8",
        quote_bg="#6B4FB8",
        divider="#C89B4B",
        shadow_alpha=58,
        stat_pill_bg="#6B4FB8",
        glow_alpha=24,
        frost_alpha=13,
        frost_border_alpha=30,
        border_alpha=38,
        placeholder_top=(246, 233, 214),
        placeholder_bottom=(235, 226, 246),
        is_dark=False,
        divider_alpha=0,
    ),
}

# 角色标志性辅色：(主橘金, 星芒暖金, 暮堇紫, 日灵青玉)
_SIGRIKA_PALETTE: dict[str, dict[str, str]] = {
    "dark": {
        "marigold": "#FF943D",
        "gold": "#F6C458",
        "wisteria": "#9E7FF0",
        "soliskin": "#67E4CF",
        "rail": "#8E72DF",
        "cardlet": "#FFFFFF",
    },
    "light": {
        "marigold": "#EC7B24",
        "gold": "#DDA032",
        "wisteria": "#7B5AC8",
        "soliskin": "#38B8A6",
        "rail": "#7D5ECF",
        "cardlet": "#5E43A3",
    },
}


# ============================ 角色几何纹样绘制辅助 ============================


def _concave_star_points(
    cx: float,
    cy: float,
    r_outer: float,
    r_inner: float,
    angle_deg: float = 0.0,
    points: int = 4,
) -> list[tuple[float, float]]:
    """生成凹四角星芒（✦）顶点序列。"""
    pts: list[tuple[float, float]] = []
    step = math.pi / points
    base = math.radians(angle_deg)
    for i in range(points * 2):
        r = r_outer if i % 2 == 0 else r_inner
        ang = base + i * step - math.pi / 2
        pts.append((cx + math.cos(ang) * r, cy + math.sin(ang) * r))
    return pts


def _diamond_points(cx: float, cy: float, rx: float, ry: float) -> list[tuple[float, float]]:
    return [(cx, cy - ry), (cx + rx, cy), (cx, cy + ry), (cx - rx, cy)]


def _render_pinwheel_hairpin(size: int, is_dark: bool) -> Image.Image:
    """超采样绘制西格莉卡标志性的「机械四角风车星芒发饰」徽记。"""
    ss = 3
    S = size * ss
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = S / 2.0

    blade_light = (250, 250, 255, 250) if is_dark else (255, 253, 250, 255)
    blade_shade = (206, 214, 236, 245) if is_dark else (218, 222, 240, 250)
    blade_edge = (118, 102, 168, 210) if is_dark else (106, 88, 156, 220)
    gold_core = (240, 192, 92, 255) if is_dark else (222, 165, 58, 255)
    cyan_tip = (103, 228, 207, 245)
    hub_dark = (58, 48, 82, 255)

    # 柔和光晕衬底
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    r_glow = S * 0.40
    gd.ellipse(
        (cx - r_glow, cy - r_glow, cx + r_glow, cy + r_glow),
        fill=(255, 168, 76, 56 if is_dark else 40),
    )
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(ss * 2)))
    d = ImageDraw.Draw(img)

    # 四片风车斜翼（微旋 18° 还原立绘发饰姿态）
    r_tip = S * 0.47
    r_root = S * 0.09
    r_wing = S * 0.19
    for idx in range(4):
        ang = math.radians(18 + idx * 90)
        ux, uy = math.cos(ang), math.sin(ang)
        px, py = -uy, ux  # 垂直法向

        tip = (cx + ux * r_tip, cy + uy * r_tip)
        root = (cx + ux * r_root, cy + uy * r_root)
        # 不对称风车折角：一侧宽展，一侧利落收束
        side_a = (
            cx + ux * (S * 0.22) + px * r_wing,
            cy + uy * (S * 0.22) + py * r_wing,
        )
        side_b = (
            cx + ux * (S * 0.25) - px * (r_wing * 0.62),
            cy + uy * (S * 0.25) - py * (r_wing * 0.62),
        )

        # 亮面与暗面分片刻画机械立体棱面
        d.polygon([root, side_a, tip], fill=blade_light)
        d.polygon([root, tip, side_b], fill=blade_shade)
        d.line([root, side_a, tip, side_b, root], fill=blade_edge, width=max(1, ss // 2))

        # 翼片内嵌香槟金菱芯
        c_in = (cx + ux * (S * 0.16), cy + uy * (S * 0.16))
        c_out = (cx + ux * (S * 0.34), cy + uy * (S * 0.34))
        c_l = (cx + ux * (S * 0.24) + px * (S * 0.045), cy + uy * (S * 0.24) + py * (S * 0.045))
        c_r = (cx + ux * (S * 0.24) - px * (S * 0.038), cy + uy * (S * 0.24) - py * (S * 0.038))
        d.polygon([c_in, c_l, c_out, c_r], fill=gold_core)

        # 翼尖青玉微光点（还原头像发饰尖端荧光刻线）
        tip_dot = (cx + ux * (S * 0.41), cy + uy * (S * 0.41))
        tr = S * 0.018
        d.ellipse((tip_dot[0] - tr, tip_dot[1] - tr, tip_dot[0] + tr, tip_dot[1] + tr), fill=cyan_tip)

    # 中心金属十字星枢
    hub_outer = _concave_star_points(cx, cy, S * 0.145, S * 0.068, angle_deg=18)
    d.polygon(hub_outer, fill=hub_dark)
    hub_gold = _concave_star_points(cx, cy, S * 0.115, S * 0.050, angle_deg=18)
    d.polygon(hub_gold, fill=gold_core)

    return img.resize((size, size), LANCZOS)


def _render_soliskin_mascot(size: int, is_dark: bool) -> Image.Image:
    """超采样绘制伴生「日灵（Soliskin）」圆润青玉小精灵徽章。"""
    ss = 3
    S = size * ss
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cx, cy = S * 0.50, S * 0.58

    body_top = (168, 248, 232) if is_dark else (142, 238, 220)
    body_bot = (84, 206, 194) if is_dark else (66, 190, 178)
    outline = (46, 128, 126, 215) if not is_dark else (196, 255, 245, 210)
    mark_col = (54, 152, 146, 205) if not is_dark else (38, 124, 122, 215)

    # 柔和青玉荧光外晕
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        (S * 0.12, S * 0.18, S * 0.88, S * 0.94),
        fill=(103, 228, 207, 72 if is_dark else 46),
    )
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(ss * 2)))
    d = ImageDraw.Draw(img)

    # 两枚灵动叶片长耳（左微倾、右舒展）
    left_ear = [
        (cx - S * 0.10, cy - S * 0.18),
        (cx - S * 0.26, cy - S * 0.44),
        (cx - S * 0.22, cy - S * 0.52),
        (cx - S * 0.02, cy - S * 0.26),
    ]
    right_ear = [
        (cx + S * 0.04, cy - S * 0.24),
        (cx + S * 0.24, cy - S * 0.50),
        (cx + S * 0.30, cy - S * 0.40),
        (cx + S * 0.13, cy - S * 0.16),
    ]
    d.polygon(left_ear, fill=(*body_top, 240))
    d.polygon(right_ear, fill=(*body_top, 240))
    d.line([*left_ear, left_ear[0]], fill=outline, width=max(2, ss - 1))
    d.line([*right_ear, right_ear[0]], fill=outline, width=max(2, ss - 1))

    # 两侧小巧翼芽
    d.polygon(
        [(cx - S * 0.28, cy + S * 0.02), (cx - S * 0.42, cy - S * 0.04), (cx - S * 0.31, cy + S * 0.14)],
        fill=(*body_bot, 230),
    )
    d.polygon(
        [(cx + S * 0.28, cy + S * 0.02), (cx + S * 0.42, cy - S * 0.04), (cx + S * 0.31, cy + S * 0.14)],
        fill=(*body_bot, 230),
    )

    # 圆润团子身体（垂直柔光渐变）
    rx, ry = int(S * 0.31), int(S * 0.28)
    body_box = (int(cx - rx), int(cy - ry), int(cx + rx), int(cy + ry))
    bw, bh = rx * 2, ry * 2
    grad = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    for yy in range(bh):
        t = yy / max(bh - 1, 1)
        col = mix(body_top, body_bot, t)
        ImageDraw.Draw(grad).line([(0, yy), (bw, yy)], fill=(*col, 245))
    bmask = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(bmask).ellipse((0, 0, bw - 1, bh - 1), fill=255)
    grad.putalpha(bmask)
    img.alpha_composite(grad, (body_box[0], body_box[1]))

    d = ImageDraw.Draw(img)
    # 顶部高光月牙
    d.ellipse(
        (cx - rx * 0.58, cy - ry * 0.78, cx + rx * 0.22, cy - ry * 0.28),
        fill=(255, 255, 255, 110),
    )
    d.ellipse(body_box, outline=outline, width=max(2, ss - 1))

    # 日灵标志性的同心圆日轮纹与小憩弯眼（呼应插画二怀抱日灵特写）
    ring_r = S * 0.145
    d.ellipse(
        (cx - ring_r, cy - ring_r + S * 0.02, cx + ring_r, cy + ring_r + S * 0.02),
        outline=mark_col,
        width=max(2, ss - 1),
    )
    eye_r = S * 0.065
    d.arc(
        (cx - eye_r, cy - eye_r + S * 0.01, cx + eye_r, cy + eye_r + S * 0.03),
        start=20,
        end=160,
        fill=mark_col,
        width=max(2, ss),
    )

    return img.resize((size, size), LANCZOS)


class SigrikaStyle(CardStyle):
    """西格莉卡（浮光莉卡）专属主题卡片。"""

    name = "sigrika"
    display_name = "浮光莉卡"
    description = "西格莉卡专属主题：浮光暖金与暮堇符文星轨、风车星芒与日灵徽记"
    version = 1
    priority = 50
    palettes = ("dark", "light")
    supports_dynamic_footer = True

    # ---------- 视觉底层与符文星轨框 ----------

    def _sigrika_canvas(
        self,
        theme: Theme,
        pal: dict[str, str],
        card_h: int,
    ) -> tuple[Any, Any]:
        """绘制浮光/暮云定制渐变底、三色柔和光晕、符文暗纹与星轨内框。"""
        marigold_rgb = hex_to_rgb(pal["marigold"])
        gold_rgb = hex_to_rgb(pal["gold"])
        wisteria_rgb = hex_to_rgb(pal["wisteria"])
        soliskin_rgb = hex_to_rgb(pal["soliskin"])
        rail_rgb = hex_to_rgb(pal["rail"])

        total_h = card_h + 14
        canvas = Image.new("RGBA", (self.width, total_h), (0, 0, 0, 0))

        # 柔和卡片外投影
        shadow = Image.new("RGBA", (self.width, total_h), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            (L.SHADOW_INSET, L.SHADOW_INSET, self.width - L.SHADOW_INSET, total_h - 2),
            radius=L.RADIUS + 2,
            fill=(0, 0, 0, theme.shadow_alpha),
        )
        canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(L.SHADOW_BLUR)))

        # 主体渐变 + 角色三色氛围光晕（左上暖阳金、右侧暮堇紫、左下日灵青玉）
        grad_rgba = self.gradient(
            (self.width, card_h), theme.gradient_top, theme.gradient_bottom
        ).convert("RGBA")

        glow_layer = Image.new("RGBA", (self.width, card_h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow_layer)
        gw = self.width
        gd.ellipse(
            (-gw // 3, -gw // 3, round(gw * 0.62), round(gw * 0.48)),
            fill=(*marigold_rgb, 50 if theme.is_dark else 32),
        )
        gd.ellipse(
            (round(gw * 0.42), round(card_h * 0.12), round(gw * 1.28), round(card_h * 0.78)),
            fill=(*wisteria_rgb, 46 if theme.is_dark else 26),
        )
        gd.ellipse(
            (-gw // 4, round(card_h * 0.58), round(gw * 0.52), round(card_h * 1.18)),
            fill=(*soliskin_rgb, 30 if theme.is_dark else 20),
        )
        grad_rgba.alpha_composite(
            glow_layer.filter(ImageFilter.GaussianBlur(max(64, gw // 6)))
        )

        # 背景浮光符文几何暗纹（低透明度，增添角色神秘感而不干扰正文阅读）
        self._draw_background_runes(grad_rgba, theme, gold_rgb, wisteria_rgb, soliskin_rgb)

        # 圆角裁切主体卡片
        mask = Image.new("L", (self.width, card_h), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, self.width - 1, card_h - 1), radius=L.RADIUS, fill=255
        )
        grad_rgba.putalpha(mask)
        canvas.alpha_composite(grad_rgba, (0, 0))

        # 外框暖金描边 + 内嵌「星轨符文装饰框」
        frame_layer = Image.new("RGBA", (self.width, card_h), (0, 0, 0, 0))
        fd = ImageDraw.Draw(frame_layer)
        fd.rounded_rectangle(
            (0, 0, self.width - 1, card_h - 1),
            radius=L.RADIUS,
            outline=with_alpha(theme.border, theme.border_alpha),
            width=1,
        )
        self._draw_star_rail_frame(
            fd,
            self.width,
            card_h,
            theme=theme,
            gold_rgb=gold_rgb,
            rail_rgb=rail_rgb,
            marigold_rgb=marigold_rgb,
        )
        canvas.alpha_composite(frame_layer, (0, 0))
        return canvas, ImageDraw.Draw(canvas)

    def _draw_background_runes(
        self,
        layer: Any,
        theme: Theme,
        gold_rgb: tuple[int, int, int],
        wisteria_rgb: tuple[int, int, int],
        soliskin_rgb: tuple[int, int, int],
    ) -> None:
        """绘制背景中的西格莉卡符文三角回纹、暖金虚线轨迹与四角星砾。"""
        w, h = layer.size
        deco = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(deco)

        rune_alpha = 26 if theme.is_dark else 22
        star_alpha = 46 if theme.is_dark else 36

        # 右上角星环与四角星芒（致敬插画一左上角金星轨环）
        orb_cx, orb_cy = w - 78, 86
        d.arc(
            (orb_cx - 56, orb_cy - 56, orb_cx + 56, orb_cy + 56),
            start=115,
            end=325,
            fill=(*gold_rgb, rune_alpha + 8),
            width=2,
        )
        d.arc(
            (orb_cx - 38, orb_cy - 38, orb_cx + 38, orb_cy + 38),
            start=20,
            end=210,
            fill=(*wisteria_rgb, rune_alpha + 6),
            width=1,
        )

        # 散落的几何折线符文（还原插画一挥刃开辟道路时的三角螺旋符文）
        rune_centers = [
            (w - 138, min(h - 150, 230), 22, 18),
            (72, max(180, h - 190), 20, -24),
            (w - 86, max(240, h - 155), 16, 42),
        ]
        for rcx, rcy, rs, rot in rune_centers:
            if rcy >= h - 70:
                continue
            ang = math.radians(rot)
            tri = [
                (rcx + math.cos(ang + i * 2.094) * rs, rcy + math.sin(ang + i * 2.094) * rs)
                for i in range(3)
            ]
            d.line([*tri, tri[0]], fill=(*wisteria_rgb, rune_alpha), width=2)
            inner_tri = [
                (
                    rcx + math.cos(ang + 0.45 + i * 2.094) * (rs * 0.52),
                    rcy + math.sin(ang + 0.45 + i * 2.094) * (rs * 0.52),
                )
                for i in range(3)
            ]
            d.line(inner_tri, fill=(*gold_rgb, rune_alpha + 6), width=2)

        # 细小四角星烁点缀
        sparkles = [
            (58, 118, 8, gold_rgb),
            (w - 54, 156, 7, soliskin_rgb),
            (w - 112, h - 112, 8, gold_rgb),
            (96, h - 104, 6, wisteria_rgb),
        ]
        for sx, sy, sr, scol in sparkles:
            if 36 < sy < h - 36:
                d.polygon(
                    _concave_star_points(sx, sy, sr, sr * 0.32),
                    fill=(*scol, star_alpha),
                )

        # 顶部衣摆几何编织纹暗带（呼应西格莉卡披肩与衣摆的三角织纹）
        weave_y = 18
        step = 18
        weave_col = (*wisteria_rgb, 20 if theme.is_dark else 16)
        for xx in range(56, w - 56, step):
            d.polygon(
                [(xx, weave_y + 5), (xx + 5, weave_y), (xx + 10, weave_y + 5)],
                fill=weave_col,
            )

        layer.alpha_composite(deco)

    def _draw_star_rail_frame(
        self,
        d: Any,
        w: int,
        h: int,
        *,
        theme: Theme,
        gold_rgb: tuple[int, int, int],
        rail_rgb: tuple[int, int, int],
        marigold_rgb: tuple[int, int, int],
    ) -> None:
        """绘制立绘同款「• • • ◇ ── ✦」四角星轨装饰框。"""
        inset = 13
        line_a = 68 if theme.is_dark else 58
        accent_a = 155 if theme.is_dark else 145
        gold_a = 185 if theme.is_dark else 170

        # 纤细内衬圆角框
        d.rounded_rectangle(
            (inset, inset, w - 1 - inset, h - 1 - inset),
            radius=max(16, L.RADIUS - inset),
            outline=(*rail_rgb, line_a),
            width=1,
        )

        # 右上角星轨：• • • • • ◇ ── ✦（向下延伸星链）
        tr_x, tr_y = w - inset - 10, inset + 10
        d.polygon(
            _concave_star_points(tr_x, tr_y, 9, 3.2),
            fill=(*rail_rgb, accent_a),
        )
        d.line([(tr_x - 36, tr_y), (tr_x - 11, tr_y)], fill=(*rail_rgb, accent_a), width=2)
        d.polygon(_diamond_points(tr_x - 42, tr_y, 5, 4), outline=(*gold_rgb, gold_a))
        for i in range(6):
            dx = tr_x - 56 - i * 11
            if dx > w // 2:
                d.ellipse((dx - 2, tr_y - 2, dx + 2, tr_y + 2), fill=(*rail_rgb, accent_a - i * 14))
        # 右侧竖向短轨
        if h > 220:
            d.line([(tr_x, tr_y + 12), (tr_x, tr_y + 48)], fill=(*rail_rgb, accent_a), width=2)
            d.polygon(_diamond_points(tr_x, tr_y + 55, 4, 5), outline=(*gold_rgb, gold_a))
            for i in range(3):
                dy = tr_y + 68 + i * 11
                d.ellipse((tr_x - 2, dy - 2, tr_x + 2, dy + 2), fill=(*rail_rgb, accent_a - i * 20))

        # 左下角星轨：竖向星芒 + 底部圆珠虚线（呼应两张插画左下角 L 形装饰轨）
        bl_x, bl_y = inset + 10, h - inset - 10
        d.polygon(
            _concave_star_points(bl_x, bl_y, 8, 2.8),
            fill=(*gold_rgb, gold_a),
        )
        d.line([(bl_x + 10, bl_y), (bl_x + 44, bl_y)], fill=(*rail_rgb, accent_a), width=2)
        d.polygon(_diamond_points(bl_x + 51, bl_y, 5, 4), outline=(*marigold_rgb, gold_a))
        for i in range(5):
            dx = bl_x + 65 + i * 11
            if dx < w - 80:
                d.ellipse((dx - 2, bl_y - 2, dx + 2, bl_y + 2), fill=(*gold_rgb, gold_a - i * 22))
        if h > 220:
            d.line([(bl_x, bl_y - 42), (bl_x, bl_y - 10)], fill=(*rail_rgb, accent_a), width=2)
            d.ellipse((bl_x - 3, bl_y - 50, bl_x + 3, bl_y - 44), outline=(*gold_rgb, gold_a))

    # ---------- 局部组件 ----------

    def _draw_sigrika_header(
        self,
        canvas: Any,
        theme: Theme,
        pal: dict[str, str],
        d: dict[str, Any],
        y: int,
    ) -> int:
        """顶部角色徽记栏：四角风车发饰 + 平台徽章 + 类型符文签 + 时间/日灵印记。"""
        pad = self.pad
        marigold_rgb = hex_to_rgb(pal["marigold"])
        gold_rgb = hex_to_rgb(pal["gold"])
        wisteria_rgb = hex_to_rgb(pal["wisteria"])
        soliskin_rgb = hex_to_rgb(pal["soliskin"])

        row_h = 44
        # 1) 左侧：西格莉卡机械四角风车星芒发饰
        pinwheel_sz = 40
        pinwheel = _render_pinwheel_hairpin(pinwheel_sz, theme.is_dark)
        canvas.alpha_composite(pinwheel, (pad - 2, y + (row_h - pinwheel_sz) // 2))
        cur_x = pad + pinwheel_sz + 8

        # 2) 平台胶囊（融合暖橘金星点与角色玻璃质感）
        plat_text = d["platform_text"]
        plat_font = self.font(21, bold=True)
        plat_w = 16 + 12 + 8 + self.text_width(plat_text, plat_font) + 18
        self.glass(
            canvas,
            (cur_x, y + 2, cur_x + plat_w, y + row_h - 2),
            (row_h - 4) // 2,
            tint_rgb=marigold_rgb if theme.is_dark else wisteria_rgb,
            tint_alpha=34 if theme.is_dark else 16,
            border_rgb=gold_rgb if theme.is_dark else wisteria_rgb,
            border_alpha=95 if theme.is_dark else 58,
            blur=6,
        )
        draw = ImageDraw.Draw(canvas)
        star_cx = cur_x + 21
        star_cy = y + row_h // 2
        draw.polygon(
            _concave_star_points(star_cx, star_cy, 6.5, 2.4),
            fill=(*marigold_rgb, 255),
        )
        self.draw_text(
            draw,
            (cur_x + 34, y + (row_h - self.line_height(plat_font)) // 2),
            plat_text,
            21,
            theme.text_primary,
            bold=True,
        )
        cur_x += plat_w + 10

        # 3) 内容类型符文小签
        ctype = d["content_type"]
        chip_font = self.font(19, bold=True)
        chip_w = self.text_width(ctype, chip_font) + 28
        if cur_x + chip_w <= self.width - pad:
            self.glass(
                canvas,
                (cur_x, y + 4, cur_x + chip_w, y + row_h - 4),
                (row_h - 8) // 2,
                tint_rgb=theme.pill_bg,
                tint_alpha=theme.frost_alpha,
                border_rgb=theme.pill_bg,
                border_alpha=theme.frost_border_alpha,
                blur=6,
            )
            draw = ImageDraw.Draw(canvas)
            self.draw_text(
                draw,
                (cur_x + 14, y + (row_h - self.line_height(chip_font)) // 2),
                ctype,
                19,
                pal["wisteria"] if not theme.is_dark else pal["gold"],
                bold=True,
            )
            cur_x += chip_w + 12

        # 4) 右侧：时间戳（窄屏自适应防重叠）+ 无封面时在右上附一枚日灵小徽章
        right_edge = self.width - pad
        if not d["hero"] and right_edge - cur_x >= 44:
            mascot_sz = 36
            mascot = _render_soliskin_mascot(mascot_sz, theme.is_dark)
            canvas.alpha_composite(
                mascot, (right_edge - mascot_sz, y + (row_h - mascot_sz) // 2)
            )
            right_edge -= mascot_sz + 10
            draw = ImageDraw.Draw(canvas)

        if d["ts"]:
            ts_font = self.font(L.F_TIME)
            ts_text = d["ts"]
            ts_w = self.text_width(ts_text, ts_font)
            if right_edge - ts_w < cur_x and " " in ts_text:
                # 极窄画布下仅保留日期部分，彻底避免与左侧药丸碰撞
                ts_text = ts_text.split(" ")[0]
                ts_w = self.text_width(ts_text, ts_font)
            if right_edge - ts_w >= cur_x:
                dot_x = right_edge - ts_w - 12
                if dot_x >= cur_x:
                    draw.polygon(
                        _diamond_points(dot_x, y + row_h // 2, 3.5, 3.5),
                        fill=(*soliskin_rgb, 210),
                    )
                self.draw_text(
                    draw,
                    (right_edge - ts_w, y + (row_h - self.line_height(ts_font)) // 2),
                    ts_text,
                    L.F_TIME,
                    theme.text_tertiary,
                )

        return y + row_h

    def _draw_rune_divider_strip(
        self,
        draw: Any,
        pal: dict[str, str],
        is_dark: bool,
        y: int,
    ) -> int:
        """无封面模式下绘制「浮光符文星链」装饰分隔条（呼应插画一底部金紫符号带）。"""
        pad = self.pad
        cy = y + 8
        gold = (*hex_to_rgb(pal["gold"]), 195 if is_dark else 175)
        wisteria = (*hex_to_rgb(pal["wisteria"]), 150 if is_dark else 130)
        soliskin = (*hex_to_rgb(pal["soliskin"]), 190 if is_dark else 165)

        # 左端双十字星号 + 渐变双轨线 + 右侧日灵三圆符「○ ‿ ○ ‿ ○」
        x = pad + 4
        for _ in range(2):
            draw.line([(x - 4, cy), (x + 4, cy)], fill=gold, width=2)
            draw.line([(x, cy - 4), (x, cy + 4)], fill=gold, width=2)
            x += 14

        line_end = max(x + 40, self.width - pad - 88)
        draw.line([(x + 4, cy - 2), (line_end, cy - 2)], fill=gold, width=2)
        draw.line([(x + 4, cy + 2), (min(line_end - 28, x + 150), cy + 2)], fill=wisteria, width=1)

        rx = self.width - pad - 58
        if rx > line_end + 8:
            for i in range(3):
                ox = rx + i * 22
                draw.ellipse((ox - 4, cy - 4, ox + 4, cy + 4), outline=gold, width=2)
                draw.ellipse((ox - 1, cy - 9, ox + 1, cy - 7), fill=soliskin)
                if i < 2:
                    draw.arc((ox + 6, cy - 3, ox + 16, cy + 5), start=15, end=165, fill=wisteria, width=2)

        return y + 20

    def _draw_hero_stage(
        self,
        canvas: Any,
        theme: Theme,
        pal: dict[str, str],
        d: dict[str, Any],
        y: int,
        media_h: int,
    ) -> int:
        """绘制带双色符文镶边、菱角卡扣与日灵伴生徽章的封面画卷框。"""
        pad = self.pad
        inner_w = self.inner_w
        radius = 22
        marigold_rgb = hex_to_rgb(pal["marigold"])
        gold_rgb = hex_to_rgb(pal["gold"])
        wisteria_rgb = hex_to_rgb(pal["wisteria"])

        try:
            raw_hero = self.cover_fit(self.open_image(d["hero"]), inner_w, media_h).convert("RGBA")
        except Exception:
            logger.warning("封面图片渲染失败，使用浮光占位渐变", exc_info=True)
            raw_hero = self.gradient(
                (inner_w, media_h), theme.placeholder_top, theme.placeholder_bottom
            ).convert("RGBA")
            raw_hero.alpha_composite(Image.new("RGBA", (inner_w, media_h), (*marigold_rgb, 34)))

        # 先在矩形 RGBA 封面上合成极柔和顶/底暗角，再统一裁切圆角（避免覆盖 scrim 透明通道）
        raw_hero.alpha_composite(
            self.scrim(inner_w, media_h, start=0.20, max_alpha=36, power=1.5, invert=True)
        )
        raw_hero.alpha_composite(
            self.scrim(inner_w, media_h, start=0.72, max_alpha=68, power=1.5)
        )
        hero_img = self.rounded_image(raw_hero, radius)
        canvas.alpha_composite(hero_img, (pad, y))

        # 画卷双色细镶边 + 三角菱形金属扣（右下角留给日灵伴生徽章）
        border_layer = Image.new("RGBA", (inner_w, media_h), (0, 0, 0, 0))
        bd = ImageDraw.Draw(border_layer)
        bd.rounded_rectangle(
            (0, 0, inner_w - 1, media_h - 1),
            radius=radius,
            outline=(*gold_rgb, 155 if theme.is_dark else 135),
            width=2,
        )
        bd.rounded_rectangle(
            (4, 4, inner_w - 5, media_h - 5),
            radius=max(14, radius - 4),
            outline=(255, 255, 255, 64 if theme.is_dark else 110),
            width=1,
        )
        for cx_, cy_ in ((14, 14), (inner_w - 15, 14), (14, media_h - 15)):
            bd.polygon(_diamond_points(cx_, cy_, 4, 4), fill=(*gold_rgb, 220))
        canvas.alpha_composite(border_layer, (pad, y))

        # 视频播放按钮：星芒轨环毛玻璃按钮
        if d["is_video_hero"]:
            r_ = L.PLAY_R
            cx, cy = self.width // 2, y + media_h // 2
            self.glass(
                canvas,
                (cx - r_, cy - r_, cx + r_, cy + r_),
                r_,
                tint_rgb=(28, 22, 48),
                tint_alpha=88,
                border_rgb=gold_rgb,
                border_alpha=190,
                blur=8,
            )
            pd = ImageDraw.Draw(canvas)
            orb_r = r_ - 6
            pd.arc(
                (cx - orb_r, cy - orb_r, cx + orb_r, cy + orb_r),
                start=25,
                end=155,
                fill=(*gold_rgb, 215),
                width=2,
            )
            pd.arc(
                (cx - orb_r, cy - orb_r, cx + orb_r, cy + orb_r),
                start=205,
                end=335,
                fill=(*wisteria_rgb, 215),
                width=2,
            )
            pd.polygon(
                [(cx - 11, cy - 17), (cx - 11, cy + 17), (cx + 19, cy)],
                fill=(255, 252, 245, 248),
            )

        # 右下角栖息一枚可爱的「日灵（Soliskin）」伴生小精灵印记
        mascot_sz = 48
        mascot = _render_soliskin_mascot(mascot_sz, theme.is_dark)
        canvas.alpha_composite(
            mascot,
            (pad + inner_w - mascot_sz - 12, y + media_h - mascot_sz - 10),
        )

        return y + media_h

    def _draw_author_cardlet(
        self,
        canvas: Any,
        theme: Theme,
        pal: dict[str, str],
        d: dict[str, Any],
        y: int,
    ) -> int:
        """绘制带双色星环头像与符文角标的作者名片槽。"""
        pad = self.pad
        inner_w = self.inner_w
        box_h = 84
        avatar_sz = 62
        marigold_rgb = hex_to_rgb(pal["marigold"])
        gold_rgb = hex_to_rgb(pal["gold"])
        wisteria_rgb = hex_to_rgb(pal["wisteria"])
        soliskin_rgb = hex_to_rgb(pal["soliskin"])
        cardlet_rgb = hex_to_rgb(pal["cardlet"])

        self.glass(
            canvas,
            (pad, y, pad + inner_w, y + box_h),
            20,
            tint_rgb=cardlet_rgb,
            tint_alpha=18 if theme.is_dark else 11,
            border_rgb=gold_rgb if theme.is_dark else wisteria_rgb,
            border_alpha=52 if theme.is_dark else 36,
            blur=6,
        )

        ax = pad + 14
        ay = y + (box_h - avatar_sz) // 2
        draw = ImageDraw.Draw(canvas)
        self.avatar_block(canvas, draw, ax, ay, avatar_sz, self.images, d, marigold_rgb)

        # 双色偏心星环 + 珍珠发夹/星芒小挂坠（致敬头像中的双珍珠发卡与星饰）
        ring = Image.new("RGBA", (avatar_sz + 8, avatar_sz + 8), (0, 0, 0, 0))
        rd = ImageDraw.Draw(ring)
        rd.arc(
            (1, 1, avatar_sz + 6, avatar_sz + 6),
            start=200,
            end=50,
            fill=(*gold_rgb, 220),
            width=2,
        )
        rd.arc(
            (1, 1, avatar_sz + 6, avatar_sz + 6),
            start=65,
            end=185,
            fill=(*wisteria_rgb, 200),
            width=2,
        )
        rd.polygon(
            _concave_star_points(avatar_sz + 1, avatar_sz + 1, 6.5, 2.3),
            fill=(*gold_rgb, 245),
        )
        canvas.alpha_composite(ring, (ax - 4, ay - 4))

        draw = ImageDraw.Draw(canvas)
        name_x = ax + avatar_sz + 16
        right_limit = pad + inner_w - 18

        # 右侧浮光符文装饰签（宽裕时展示，绝不挤压作者名）
        tag_text = "SOLISKIN · 浮光同途"
        tag_font = self.font(16, bold=True)
        tag_w = self.text_width(tag_text, tag_font) + 38
        if inner_w >= 540 and right_limit - tag_w - name_x >= 180:
            tx0 = right_limit - tag_w
            ty0 = y + (box_h - 30) // 2
            self.glass(
                canvas,
                (tx0, ty0, tx0 + tag_w, ty0 + 30),
                15,
                tint_rgb=soliskin_rgb,
                tint_alpha=24 if theme.is_dark else 16,
                border_rgb=soliskin_rgb,
                border_alpha=72 if theme.is_dark else 58,
                blur=4,
            )
            draw = ImageDraw.Draw(canvas)
            draw.polygon(
                _concave_star_points(tx0 + 15, ty0 + 15, 5.2, 1.9),
                fill=(*soliskin_rgb, 240),
            )
            self.draw_text(
                draw,
                (tx0 + 25, ty0 + (30 - self.line_height(tag_font)) // 2),
                tag_text,
                16,
                pal["soliskin"],
                bold=True,
            )
            right_limit = tx0 - 14

        max_text_w = max(80, right_limit - name_x)
        name_font = self.font(25, bold=True)
        shown_name = self.fit_lines(d["name"], name_font, max_text_w, 1)[0] if d["name"] else ""
        if d["author_desc"]:
            self.draw_text(draw, (name_x, ay + 4), shown_name, 25, theme.text_primary, bold=True)
            desc_font = self.font(18)
            shown_desc = self.fit_lines(d["author_desc"], desc_font, max_text_w, 1)[0]
            self.draw_text(draw, (name_x, ay + avatar_sz - 24), shown_desc, 18, theme.text_tertiary)
        else:
            self.draw_text(
                draw,
                (name_x, ay + (avatar_sz - self.line_height(name_font)) // 2),
                shown_name,
                25,
                theme.text_primary,
                bold=True,
            )

        return y + box_h

    def _draw_sigrika_stats(
        self,
        canvas: Any,
        theme: Theme,
        pal: dict[str, str],
        rows: list[list[tuple[str, str]]],
        y: int,
    ) -> int:
        """绘制带暖金/暮堇微边框的统计胶囊组。"""
        pad = self.pad
        gold_rgb = hex_to_rgb(pal["gold"])
        wisteria_rgb = hex_to_rgb(pal["wisteria"])
        marigold_hex = pal["marigold"]
        label_font = self.font(L.F_STAT_LABEL)
        value_font = self.font(L.F_STAT_VALUE, bold=True)

        for row in rows:
            x = pad
            for idx, (label, value) in enumerate(row):
                w = self.stat_pill_width(label, value)
                tint = wisteria_rgb if idx % 2 else gold_rgb
                self.glass(
                    canvas,
                    (x, y, x + w, y + L.STAT_H),
                    L.STAT_H // 2,
                    tint_rgb=theme.stat_pill_bg,
                    tint_alpha=theme.frost_alpha,
                    border_rgb=tint,
                    border_alpha=58 if theme.is_dark else 44,
                    blur=6,
                )
                draw = ImageDraw.Draw(canvas)
                label_w = self.text_width(label, label_font)
                tx = x + L.STAT_PAD_X
                if value:
                    self.draw_text(
                        draw,
                        (tx, y + (L.STAT_H - self.line_height(label_font)) // 2),
                        label,
                        L.F_STAT_LABEL,
                        theme.text_tertiary,
                    )
                    val_color = pal["gold"] if theme.is_dark and idx == 0 else (
                        marigold_hex if not theme.is_dark and idx == 0 else theme.text_primary
                    )
                    self.draw_text(
                        draw,
                        (
                            tx + label_w + L.STAT_LABEL_VALUE_GAP,
                            y + (L.STAT_H - self.line_height(value_font)) // 2,
                        ),
                        value,
                        L.F_STAT_VALUE,
                        val_color,
                        bold=True,
                    )
                else:
                    self.draw_text(
                        draw,
                        (tx, y + (L.STAT_H - self.line_height(label_font)) // 2),
                        label,
                        L.F_STAT_LABEL,
                        theme.text_secondary,
                    )
                x += w + L.STAT_GAP
            y += L.STAT_H + L.STAT_ROW_GAP
        return y - L.STAT_ROW_GAP

    def _draw_sigrika_quote(
        self,
        canvas: Any,
        theme: Theme,
        pal: dict[str, str],
        quote_h: int,
        y: int,
    ) -> int:
        """绘制带橘金→暮堇双色渐变符文竖条的转发引用块。"""
        if not self.result.repost or not quote_h:
            return y
        pad = self.pad
        inner_w = self.inner_w
        marigold_rgb = hex_to_rgb(pal["marigold"])
        wisteria_rgb = hex_to_rgb(pal["wisteria"])
        gold_rgb = hex_to_rgb(pal["gold"])

        self.glass(
            canvas,
            (pad, y, pad + inner_w, y + quote_h),
            L.QUOTE_RADIUS,
            tint_rgb=theme.quote_bg,
            tint_alpha=theme.frost_alpha,
            border_rgb=wisteria_rgb,
            border_alpha=54 if theme.is_dark else 40,
            blur=6,
        )

        bar_h = max(16, quote_h - 32)
        bar_grad = self.gradient((L.QUOTE_BAR_W, bar_h), marigold_rgb, wisteria_rgb).convert("RGBA")
        bar_grad = self.rounded_image(bar_grad, L.QUOTE_BAR_W // 2)
        canvas.alpha_composite(bar_grad, (pad + 18, y + 16))

        draw = ImageDraw.Draw(canvas)
        draw.polygon(
            _concave_star_points(pad + inner_w - 20, y + 18, 6, 2.2),
            fill=(*gold_rgb, 150),
        )
        self.draw_quote_text(
            draw,
            self.result.repost,
            pad + 18 + L.QUOTE_BAR_W + 16,
            y + 16,
            inner_w - 18 * 2 - L.QUOTE_BAR_W - 16,
            theme,
        )
        return y + quote_h

    # ---------- 主渲染流程 ----------

    def render(self) -> Path:
        mode = "dark" if self.theme.is_dark else "light"
        theme = _SIGRIKA_THEMES[mode]
        pal = _SIGRIKA_PALETTE[mode]
        sig_accent = pal["marigold"]
        sig_accent_rgb = hex_to_rgb(sig_accent)
        gold_rgb = hex_to_rgb(pal["gold"])
        wisteria_rgb = hex_to_rgb(pal["wisteria"])

        pad = self.pad
        inner_w = self.inner_w
        gap = self.gap
        d = self.data

        # 1) 媒体与排版尺寸预计算
        media_h = round(inner_w * 9 / 16) if d["hero"] else 0
        if d["hero"] and self.cover_full_size:
            media_h = self.hero_aspect_height(d["hero"], inner_w, media_h)

        title_bar_offset = 20
        title_max_w = inner_w - title_bar_offset
        title_font = self.font(34, bold=True)
        title_line_h = 48
        title_lines = (
            self.fit_lines(d["title"], title_font, title_max_w, 3)
            if d["title"]
            else []
        )

        desc_font = self.font(L.F_DESC)
        desc_lines = (
            self.fit_lines(d["text"], desc_font, inner_w, 6)
            if d["text"]
            else []
        )

        stats_h, stat_rows = self.stat_rows_height(d, inner_w)
        warnings_h = self.warning_block_height(d["warnings"], inner_w)
        grid_h = self.grid_metrics(len(d["grid"]), inner_w, gap)[0]
        quote_h = (
            self.measure_quote(self.result.repost, inner_w)
            if self.result.repost
            else 0
        )

        # 2) 精确累加卡片总高度（与下方绘制 y 严格一一对应）
        y = 32
        y += 44 + 16  # 顶部角色徽记栏
        if d["hero"]:
            y += media_h + 20
        else:
            y += 20 + 14  # 无封面符文星链分隔带
        if d["author"]:
            y += 84 + 18
        if title_lines:
            y += len(title_lines) * title_line_h + 14
        if desc_lines:
            y += len(desc_lines) * L.F_DESC_LINE_H + 16
        if grid_h:
            y += grid_h + 20
        if stats_h:
            y += stats_h + 18
        if d["online_text"]:
            y += 38
        if warnings_h:
            y += warnings_h + 16
        if quote_h:
            y += quote_h + 20
        y += L.FOOTER_H
        card_h = y

        # 3) 绘制定制画布与装饰边框
        canvas, draw = self._sigrika_canvas(theme, pal, card_h)

        y = 32
        y = self._draw_sigrika_header(canvas, theme, pal, d, y) + 16
        draw = ImageDraw.Draw(canvas)

        if d["hero"]:
            y = self._draw_hero_stage(canvas, theme, pal, d, y, media_h) + 20
            draw = ImageDraw.Draw(canvas)
        else:
            y = self._draw_rune_divider_strip(draw, pal, theme.is_dark, y) + 14

        if d["author"]:
            y = self._draw_author_cardlet(canvas, theme, pal, d, y) + 18
            draw = ImageDraw.Draw(canvas)

        # 标题（左侧配暖橘金→暮堇紫符文竖杖与菱星顶饰）
        if title_lines:
            total_th = len(title_lines) * title_line_h
            bar_h = max(24, total_th - 12)
            bar_img = self.gradient((6, bar_h), sig_accent_rgb, wisteria_rgb).convert("RGBA")
            canvas.alpha_composite(self.rounded_image(bar_img, 3), (pad + 2, y + 6))
            draw = ImageDraw.Draw(canvas)
            draw.polygon(
                _diamond_points(pad + 5, y + 3, 4.5, 4.5),
                fill=(*gold_rgb, 235),
            )
            for line in title_lines:
                self.draw_text(
                    draw,
                    (pad + title_bar_offset, y),
                    line,
                    34,
                    theme.text_primary,
                    bold=True,
                )
                y += title_line_h
            y += 14

        # 正文简介
        if desc_lines:
            for line in desc_lines:
                self.draw_text(draw, (pad, y), line, L.F_DESC, theme.text_secondary)
                y += L.F_DESC_LINE_H
            y += 16

        # 图集网格（为每个单元格叠加淡淡暖金细边，融入整体画风）
        if d["grid"]:
            grid_start_y = y
            y = self.draw_grid_block(canvas, draw, theme, d["grid"], y, inner_w, gap)
            if y > grid_start_y:
                _, cols, rows, cell_h = self.grid_metrics(len(d["grid"]), inner_w, gap)
                show = min(len(d["grid"]), cols * rows)
                cell_border = Image.new("RGBA", (cell_h, cell_h), (0, 0, 0, 0))
                ImageDraw.Draw(cell_border).rounded_rectangle(
                    (0, 0, cell_h - 1, cell_h - 1),
                    radius=L.GRID_RADIUS,
                    outline=(*gold_rgb, 76 if theme.is_dark else 64),
                    width=1,
                )
                for idx in range(show):
                    r, c = divmod(idx, cols)
                    canvas.alpha_composite(
                        cell_border,
                        (pad + c * (cell_h + gap), grid_start_y + r * (cell_h + gap)),
                    )
            draw = ImageDraw.Draw(canvas)

        # 统计胶囊
        if stat_rows:
            y = self._draw_sigrika_stats(canvas, theme, pal, stat_rows, y) + 18
            draw = ImageDraw.Draw(canvas)

        # 在线人数
        if d["online_text"]:
            y = self.draw_online(draw, d, y, pal["soliskin"])

        # 时长限制等警告块
        if d["warnings"]:
            y = self.draw_warning_block(canvas, draw, theme, d["warnings"], y, inner_w) + 16
            draw = ImageDraw.Draw(canvas)

        # 转发引用
        if quote_h:
            y = self._draw_sigrika_quote(canvas, theme, pal, quote_h, y) + 20
            draw = ImageDraw.Draw(canvas)

        # 页脚（兼容 .anchor.json 底卡复用与动态人格署名，采用中央自然留空的双段星芒分隔线）
        div_y = y + 12
        mid_x = self.width // 2
        div_layer = Image.new("RGBA", (self.width, 16), (0, 0, 0, 0))
        dd = ImageDraw.Draw(div_layer)
        div_col = (*gold_rgb, 56 if theme.is_dark else 64)
        if mid_x - 24 > pad:
            dd.line([(pad, 8), (mid_x - 24, 8)], fill=div_col, width=1)
        if pad + inner_w - 1 > mid_x + 24:
            dd.line([(mid_x + 24, 8), (pad + inner_w - 1, 8)], fill=div_col, width=1)
        dd.polygon(
            _concave_star_points(mid_x, 8, 6.5, 2.3),
            fill=(*gold_rgb, 200 if theme.is_dark else 180),
        )
        dd.polygon(_diamond_points(mid_x - 13, 8, 2.5, 2.5), fill=(*wisteria_rgb, 175))
        dd.polygon(_diamond_points(mid_x + 13, 8, 2.5, 2.5), fill=(*wisteria_rgb, 175))
        canvas.alpha_composite(div_layer, (0, div_y - 8))

        draw = ImageDraw.Draw(canvas)
        self.footer_block(
            canvas,
            draw,
            theme,
            sig_accent,
            sig_accent_rgb,
            self.result,
            y,
            inner_w,
        )

        return self.save(canvas, self.out_path)


STYLE = register_style(StyleSpec(style_cls=SigrikaStyle, priority=SigrikaStyle.priority))
