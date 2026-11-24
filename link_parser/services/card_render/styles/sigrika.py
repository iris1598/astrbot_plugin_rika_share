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


def _cubic_bezier(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    steps: int = 16,
) -> list[tuple[float, float]]:
    """采样三次贝塞尔曲线顶点序列，用于绘制圆润自然的鳍手与叶耳轮廓。"""
    pts: list[tuple[float, float]] = []
    for i in range(steps + 1):
        t = i / steps
        mt = 1.0 - t
        x = (
            mt**3 * p0[0]
            + 3 * mt**2 * t * p1[0]
            + 3 * mt * t**2 * p2[0]
            + t**3 * p3[0]
        )
        y = (
            mt**3 * p0[1]
            + 3 * mt**2 * t * p1[1]
            + 3 * mt * t**2 * p2[1]
            + t**3 * p3[1]
        )
        pts.append((x, y))
    return pts


def _render_soliskin_mascot(size: int, is_dark: bool) -> Image.Image:
    """4x 超采样绘制伴生「日灵（小哆 / Soliskin）」徽标。

    忠实还原设定细节：头顶双环金色圣辉光轮、直立晶叶长耳与耳根小圆苞、
    两侧圆润微翘的白纹宽展长鳍手、奶白青瓷绿梨形躯干，以及正中
    「朝霞金粉渐变 + 八芒太阳纹」核心与腹部荧光绿回路纹。
    """
    ss = 4
    S = size * ss
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cx = S * 0.50
    cy = S * 0.615

    # 奶白青瓷绿实色色阶（全程使用不透明混合色或 alpha_composite，杜绝半透明多边形掏空 Alpha）
    jade_hi = (234, 250, 232)
    jade_mid = (198, 236, 206)
    jade_low = (152, 210, 178)
    arm_tip_col = (228, 246, 224)
    ear_tip_col = (255, 251, 214)
    jade_edge = (72, 138, 114, 230) if not is_dark else (112, 182, 154, 235)
    neon_mint = (176, 255, 214, 250)

    # 1) 柔和背光外晕 + 头顶圣辉金晕
    aura = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ad = ImageDraw.Draw(aura)
    ad.ellipse(
        (S * 0.16, S * 0.26, S * 0.84, S * 0.94),
        fill=(18, 26, 34, 95) if is_dark else (86, 158, 132, 46),
    )
    ad.ellipse(
        (S * 0.22, S * 0.01, S * 0.78, S * 0.17),
        fill=(255, 240, 156, 115 if is_dark else 85),
    )
    img.alpha_composite(aura.filter(ImageFilter.GaussianBlur(round(ss * 2.2))))

    # 2) 头顶悬浮双环金色符文光轮（绘制在独立层，带清亮白金高光）
    halo_layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo_layer)
    hy0, hy1 = S * 0.032, S * 0.132
    hd.ellipse(
        (S * 0.24, hy0, S * 0.76, hy1),
        outline=(255, 244, 178, 245),
        width=max(2, round(ss * 0.75)),
    )
    hd.ellipse(
        (S * 0.31, hy0 + S * 0.020, S * 0.69, hy1 - S * 0.020),
        outline=(255, 252, 220, 230),
        width=max(1, round(ss * 0.50)),
    )
    # 光轮内十字刻度短线
    hd.line([(cx - S * 0.06, (hy0 + hy1) / 2), (cx + S * 0.06, (hy0 + hy1) / 2)], fill=(255, 250, 210, 210), width=max(1, ss // 2))
    img.alpha_composite(halo_layer)

    # 3) 两侧圆润微翘的宽展长鳍手（贝塞尔平滑曲线 + 白色回路弧带）
    arms_layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ard = ImageDraw.Draw(arms_layer)
    for sign in (-1, 1):
        # 上沿：从肩侧向下微垂后在末端优雅上翘
        upper = _cubic_bezier(
            (cx + sign * S * 0.20, cy - S * 0.04),
            (cx + sign * S * 0.31, cy + S * 0.03),
            (cx + sign * S * 0.41, cy + S * 0.04),
            (cx + sign * S * 0.475, cy + S * 0.005),
            steps=14,
        )
        # 鳍尖圆弧包回下沿
        tip_curve = _cubic_bezier(
            (cx + sign * S * 0.475, cy + S * 0.005),
            (cx + sign * S * 0.505, cy + S * 0.055),
            (cx + sign * S * 0.455, cy + S * 0.165),
            (cx + sign * S * 0.355, cy + S * 0.185),
            steps=12,
        )
        # 下沿圆润收回腰侧
        lower = _cubic_bezier(
            (cx + sign * S * 0.355, cy + S * 0.185),
            (cx + sign * S * 0.285, cy + S * 0.195),
            (cx + sign * S * 0.235, cy + S * 0.160),
            (cx + sign * S * 0.195, cy + S * 0.125),
            steps=12,
        )
        arm_poly = upper + tip_curve[1:] + lower[1:]
        ard.polygon(arm_poly, fill=(*jade_mid, 255))

        # 鳍端柔白渐变亮区（使用蒙版限制在鳍手内部，绝不污染透明通道）
        tip_poly = upper[7:] + tip_curve[1:] + lower[:5]
        ard.polygon(tip_poly, fill=(*arm_tip_col, 255))

        # 鳍手白色双弧纹与发光小圆节点
        band1 = _cubic_bezier(
            (cx + sign * S * 0.335, cy + S * 0.032),
            (cx + sign * S * 0.355, cy + S * 0.095),
            (cx + sign * S * 0.340, cy + S * 0.145),
            (cx + sign * S * 0.310, cy + S * 0.182),
            steps=10,
        )
        band2 = _cubic_bezier(
            (cx + sign * S * 0.400, cy + S * 0.030),
            (cx + sign * S * 0.420, cy + S * 0.085),
            (cx + sign * S * 0.405, cy + S * 0.130),
            (cx + sign * S * 0.375, cy + S * 0.172),
            steps=10,
        )
        ard.line(band1, fill=(255, 253, 236, 240), width=max(2, round(ss * 0.6)))
        ard.line(band2, fill=(255, 253, 236, 215), width=max(1, round(ss * 0.45)))
        dot_x, dot_y = cx + sign * S * 0.352, cy + S * 0.112
        dr = S * 0.015
        ard.ellipse((dot_x - dr, dot_y - dr, dot_x + dr, dot_y + dr), fill=(255, 253, 232, 255))
        ard.line([*arm_poly, arm_poly[0]], fill=jade_edge, width=max(2, round(ss * 0.55)))
    img.alpha_composite(arms_layer)

    d = ImageDraw.Draw(img)

    # 4) 底部两只短圆小脚
    for sign in (-1, 1):
        fx = cx + sign * S * 0.090
        fy = cy + S * 0.248
        frx, fry = S * 0.048, S * 0.042
        d.ellipse(
            (fx - frx, fy - fry, fx + frx, fy + fry),
            fill=(*jade_low, 255),
            outline=jade_edge,
            width=max(1, ss // 2),
        )

    # 5) 直立晶叶长耳（不透明暖金白耳尖渐变 + 折线叶脉）
    ears_layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ed = ImageDraw.Draw(ears_layer)
    for sign in (-1, 1):
        ear_in = _cubic_bezier(
            (cx + sign * S * 0.055, cy - S * 0.22),
            (cx + sign * S * 0.068, cy - S * 0.34),
            (cx + sign * S * 0.112, S * 0.18),
            (cx + sign * S * 0.158, S * 0.058),
            steps=12,
        )
        ear_out = _cubic_bezier(
            (cx + sign * S * 0.158, S * 0.058),
            (cx + sign * S * 0.205, S * 0.19),
            (cx + sign * S * 0.208, cy - S * 0.31),
            (cx + sign * S * 0.152, cy - S * 0.195),
            steps=12,
        )
        ear_poly = ear_in + ear_out[1:]
        ed.polygon(ear_poly, fill=(*jade_mid, 255))

        # 耳尖金白高光渐变（通过蒙版合成，保持 255 满不透明度）
        ear_mask = Image.new("L", (S, S), 0)
        ImageDraw.Draw(ear_mask).polygon(ear_poly, fill=255)
        ear_grad = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        egd = ImageDraw.Draw(ear_grad)
        y_top_e = int(S * 0.055)
        y_bot_e = int(cy - S * 0.19)
        for yy in range(y_top_e, y_bot_e + 1):
            t = (yy - y_top_e) / max(y_bot_e - y_top_e, 1)
            col = mix(ear_tip_col, jade_hi, min(1.0, t / 0.48)) if t < 0.48 else mix(jade_hi, jade_mid, (t - 0.48) / 0.52)
            egd.line([(0, yy), (S, yy)], fill=(*col, 255))
        ears_layer.paste(ear_grad, (0, 0), ear_mask)

        ed = ImageDraw.Draw(ears_layer)
        # 耳内几何白色叶脉与小圆点
        vein = [
            (cx + sign * S * 0.108, cy - S * 0.22),
            (cx + sign * S * 0.146, cy - S * 0.33),
            (cx + sign * S * 0.132, S * 0.20),
            (cx + sign * S * 0.158, S * 0.075),
        ]
        ed.line(vein, fill=(255, 254, 240, 235), width=max(1, round(ss * 0.48)))
        vx, vy = vein[1]
        ed.ellipse((vx - ss, vy - ss, vx + ss, vy + ss), fill=(255, 254, 240, 245))
        ed.line([*ear_poly, ear_poly[0]], fill=jade_edge, width=max(2, round(ss * 0.55)))
    img.alpha_composite(ears_layer)

    # 6) 圆润梨形躯干（上窄下微丰满的蛋梨形轮廓 + 脸侧小绒尖 + 耳根小圆苞）
    rx_top, rx_bot = S * 0.222, S * 0.254
    ry = int(S * 0.265)
    by0, by1 = int(cy - ry), int(cy + ry)
    bh = max(1, by1 - by0)
    body_layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    body_mask = Image.new("L", (S, S), 0)
    bmd = ImageDraw.Draw(body_mask)
    left_side = _cubic_bezier(
        (cx, by0),
        (cx - rx_top * 1.18, by0),
        (cx - rx_bot * 1.12, cy + ry * 0.15),
        (cx - rx_bot * 0.72, by1 - ry * 0.14),
        steps=18,
    )
    bottom_arc = _cubic_bezier(
        (cx - rx_bot * 0.72, by1 - ry * 0.14),
        (cx - rx_bot * 0.36, by1 + ry * 0.04),
        (cx + rx_bot * 0.36, by1 + ry * 0.04),
        (cx + rx_bot * 0.72, by1 - ry * 0.14),
        steps=14,
    )
    right_side = _cubic_bezier(
        (cx + rx_bot * 0.72, by1 - ry * 0.14),
        (cx + rx_bot * 1.12, cy + ry * 0.15),
        (cx + rx_top * 1.18, by0),
        (cx, by0),
        steps=18,
    )
    body_poly = left_side + bottom_arc[1:] + right_side[1:]
    bmd.polygon(body_poly, fill=255)

    body_grad = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    bgd = ImageDraw.Draw(body_grad)
    for yy in range(by0 - 4, by1 + 8):
        t = max(0.0, min(1.0, (yy - by0) / bh))
        col = mix(jade_hi, jade_mid, t / 0.58) if t < 0.58 else mix(jade_mid, jade_low, (t - 0.58) / 0.42)
        bgd.line([(0, yy), (S, yy)], fill=(*col, 255))
    body_layer.paste(body_grad, (0, 0), body_mask)

    bld = ImageDraw.Draw(body_layer)
    # 脸颊两侧小巧绒毛尖（紧贴上半脸颊）
    for sign in (-1, 1):
        tuft = [
            (cx + sign * S * 0.205, cy - S * 0.105),
            (cx + sign * S * 0.258, cy - S * 0.130),
            (cx + sign * S * 0.220, cy - S * 0.055),
        ]
        bld.polygon(tuft, fill=(*jade_hi, 255))
        bld.line([tuft[0], tuft[1], tuft[2]], fill=jade_edge, width=max(1, round(ss * 0.5)))

    bld.line([*body_poly, body_poly[0]], fill=jade_edge, width=max(2, round(ss * 0.58)))

    # 耳根外侧两枚可爱小圆苞（紧贴头侧耳根）
    for sign in (-1, 1):
        bud_x = cx + sign * S * 0.178
        bud_y = cy - S * 0.202
        br = S * 0.036
        bld.ellipse(
            (bud_x - br, bud_y - br * 0.86, bud_x + br, bud_y + br * 0.86),
            fill=(*jade_hi, 255),
            outline=jade_edge,
            width=max(1, round(ss * 0.5)),
        )
    img.alpha_composite(body_layer)

    # 7) 腹部荧光绿回路纹（先画一层柔光外晕再叠清亮荧光线，还原游戏内自发光纹路）
    core_cy = cy - S * 0.048
    core_r = int(S * 0.126)
    arc_r = core_r + S * 0.034

    circuit_glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cgd_line = ImageDraw.Draw(circuit_glow)
    cgd_line.arc(
        (cx - arc_r, core_cy - arc_r, cx + arc_r, core_cy + arc_r),
        start=26,
        end=154,
        fill=(120, 255, 190, 150),
        width=max(3, round(ss * 1.1)),
    )
    for sign in (-1, 1):
        stem = _cubic_bezier(
            (cx + sign * S * 0.135, cy + S * 0.105),
            (cx + sign * S * 0.075, cy + S * 0.150),
            (cx + sign * S * 0.028, cy + S * 0.175),
            (cx + sign * S * 0.022, cy + S * 0.240),
            steps=10,
        )
        cgd_line.line(stem, fill=(120, 255, 190, 145), width=max(3, round(ss * 1.0)))
    img.alpha_composite(circuit_glow.filter(ImageFilter.GaussianBlur(ss)))

    circuit_sharp = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    csd = ImageDraw.Draw(circuit_sharp)
    csd.arc(
        (cx - arc_r, core_cy - arc_r, cx + arc_r, core_cy + arc_r),
        start=26,
        end=154,
        fill=neon_mint,
        width=max(2, round(ss * 0.55)),
    )
    for sign in (-1, 1):
        ang = math.radians(90 - sign * 64)
        nx = cx + math.cos(ang) * arc_r
        ny = core_cy + math.sin(ang) * arc_r
        nr = S * 0.015
        csd.ellipse((nx - nr, ny - nr, nx + nr, ny + nr), outline=neon_mint, width=max(1, ss // 2))
        stem = _cubic_bezier(
            (cx + sign * S * 0.135, cy + S * 0.105),
            (cx + sign * S * 0.075, cy + S * 0.150),
            (cx + sign * S * 0.028, cy + S * 0.175),
            (cx + sign * S * 0.022, cy + S * 0.240),
            steps=10,
        )
        csd.line(stem, fill=neon_mint, width=max(2, round(ss * 0.52)))
        # 轻巧柔和的浅嫩叶芽斑纹（低对比度融于青玉肌肤）
        leaf_col = (*mix(jade_mid, (152, 198, 138), 0.48), 230)
        lx, ly = cx + sign * S * 0.152, cy + S * 0.070
        leaf_pts = [
            (lx, ly - S * 0.022),
            (lx + sign * S * 0.014, ly),
            (lx, ly + S * 0.022),
            (lx - sign * S * 0.014, ly),
        ]
        csd.polygon(leaf_pts, fill=leaf_col)
    img.alpha_composite(circuit_sharp)

    # 8) 核心特征：朝霞渐变圆盘 + 白色八芒太阳纹（「是红色，是太阳，是朝霞的颜色」）
    core_layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cld = ImageDraw.Draw(core_layer)
    rim_r = core_r + round(S * 0.020)
    cld.ellipse(
        (cx - rim_r, core_cy - rim_r, cx + rim_r, core_cy + rim_r),
        fill=(242, 251, 238, 255),
        outline=(168, 210, 180, 235),
        width=max(1, round(ss * 0.45)),
    )

    cd = core_r * 2
    core_grad = Image.new("RGBA", (cd, cd), (0, 0, 0, 0))
    cgd = ImageDraw.Draw(core_grad)
    sun_top = (255, 226, 96)     # 暖阳金黄
    sun_mid = (255, 198, 132)    # 柔和杏橘
    sun_bot = (255, 168, 186)    # 朝霞粉红
    for yy in range(cd):
        t = yy / max(cd - 1, 1)
        col = mix(sun_top, sun_mid, t / 0.52) if t < 0.52 else mix(sun_mid, sun_bot, (t - 0.52) / 0.48)
        cgd.line([(0, yy), (cd, yy)], fill=(*col, 255))
    cmask = Image.new("L", (cd, cd), 0)
    ImageDraw.Draw(cmask).ellipse((0, 0, cd - 1, cd - 1), fill=255)
    core_grad.putalpha(cmask)
    core_layer.alpha_composite(core_grad, (int(cx - core_r), int(core_cy - core_r)))

    cld = ImageDraw.Draw(core_layer)
    cld.ellipse(
        (cx - core_r, core_cy - core_r, cx + core_r, core_cy + core_r),
        outline=(238, 192, 126, 225),
        width=max(1, round(ss * 0.45)),
    )

    # 中央白色太阳圆心 + 8 枚放射菱瓣光芒
    sun_white = (255, 253, 245, 255)
    disc_r = core_r * 0.34
    cld.ellipse((cx - disc_r, core_cy - disc_r, cx + disc_r, core_cy + disc_r), fill=sun_white)
    r_in = core_r * 0.45
    r_mid = core_r * 0.61
    r_out = core_r * 0.81
    ray_half_w = core_r * 0.125
    for i in range(8):
        ang = i * (math.pi / 4.0)
        ux, uy = math.cos(ang), math.sin(ang)
        px, py = -uy, ux
        ray_pts = [
            (cx + ux * r_in, core_cy + uy * r_in),
            (cx + ux * r_mid + px * ray_half_w, core_cy + uy * r_mid + py * ray_half_w),
            (cx + ux * r_out, core_cy + uy * r_out),
            (cx + ux * r_mid - px * ray_half_w, core_cy + uy * r_mid - py * ray_half_w),
        ]
        cld.polygon(ray_pts, fill=sun_white)

    img.alpha_composite(core_layer)
    return img.resize((size, size), LANCZOS)


class SigrikaStyle(CardStyle):
    """西格莉卡（浮光莉卡）专属主题卡片。"""

    name = "sigrika"
    display_name = "浮光莉卡"
    description = "西格莉卡专属主题：浮光暖金与暮堇符文星轨、风车星芒与日灵徽记"
    version = 2
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
        if not d["hero"] and right_edge - cur_x >= 50:
            mascot_sz = 44
            mascot = _render_soliskin_mascot(mascot_sz, theme.is_dark)
            canvas.alpha_composite(
                mascot, (right_edge - mascot_sz + 2, y + (row_h - mascot_sz) // 2)
            )
            right_edge -= mascot_sz + 8
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

        # 右下角栖息一枚可爱的「日灵（小哆 / Soliskin）」伴生小精灵印记
        mascot_sz = 60
        mascot = _render_soliskin_mascot(mascot_sz, theme.is_dark)
        canvas.alpha_composite(
            mascot,
            (pad + inner_w - mascot_sz - 10, y + media_h - mascot_sz - 8),
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
