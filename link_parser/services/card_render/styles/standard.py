"""标准横幅卡片样式。

顶部全宽封面 + 纵向信息流，适合大多数视频与动态
"""

from __future__ import annotations

from pathlib import Path

from astrbot.api import logger

from ..text import (
    format_timestamp,
    one_line,
    parse_stats_line,
    short_url,
    strip_emoji,
)
from ..theme import L, Image, ImageDraw, ImageFilter, mix, with_alpha
from .base import CardStyle
from .registry import StyleSpec, register_style


class StandardStyle(CardStyle):
    name = "standard"
    display_name = "标准横幅"
    description = "顶部全宽封面 + 纵向信息流，适合大多数视频与动态"
    version = 1
    priority = 10
    palettes = ("dark", "light")

    def render(self) -> Path:
        """标准布局：顶部全宽横幅 + 纵向信息流。"""
        theme = self.theme
        accent = self.accent
        accent_rgb = self.accent_rgb

        pad = L.PAD
        inner_w = self.width - pad * 2
        gap = L.GRID_GAP

        # ================= 数据准备 =================
        is_video_hero = self.images.get("hero") is not None
        hero = self.images.get("hero")
        grid = list(self.images.get("grid") or [])
        if hero is None and grid:
            # 没有视频封面时，用图集首图作为顶部横幅
            hero = grid.pop(0)
        hero_h = round(self.width * L.HERO_RATIO) if hero else 0
        if hero and self.cover_full_size:
            hero_h = self.hero_aspect_height(hero, self.width, hero_h)

        grid_h, cols, rows, cell_h = self.grid_metrics(len(grid), inner_w, gap)

        # 头部文字
        platform_text = self.result.platform.display_name
        platform_pill_w = self.platform_pill_width(platform_text)

        content_type = self.result.content_type or "动态"
        chip_font = self.font(L.F_CHIP, bold=True)
        type_pill_w = self.text_width(content_type, chip_font) + 36

        ts = format_timestamp(self.result.timestamp)
        ts_font = self.font(L.F_TIME)

        # 标题
        title_font = self.font(L.F_TITLE, bold=True)
        title = strip_emoji(self.result.title)
        title_lines: list[str] = []
        if title:
            title_lines = self.fit_lines(
                title, title_font, inner_w, 2 if hero else 3
            )

        # 简介
        desc_font = self.font(L.F_DESC)
        text = strip_emoji(self.result.text)
        desc_lines: list[str] = []
        if text:
            desc_lines = self.fit_lines(text, desc_font, inner_w, 6)

        # 作者
        author = self.result.author
        avatar_size = L.AVATAR
        name = strip_emoji(author.name) or "未知作者" if author else ""
        author_desc = one_line(author.description)[:40] if author else ""

        # 统计（时长并入统计徽章）
        stats = parse_stats_line(self.result.extra.get("stats_line"))
        if dur := self.result.extra.get("duration"):
            stats.insert(0, ("时长", str(dur)))
        online_text = strip_emoji(self.result.extra.get("online") or "")
        limit_warnings = self.result.extra.get("limit_warnings") or []
        warnings_h = self.warning_block_height(limit_warnings, inner_w)
        stat_rows = self.build_stat_rows(stats, inner_w)

        quote_h = self.measure_quote(self.result.repost, inner_w) if self.result.repost else 0

        # ================= 高度计算 =================
        if hero:
            y = hero_h + 20
        else:
            y = L.HEAD_BAR_TOP + L.HEAD_BAR_H + 18 + L.HEAD_PILL_H + 18
        if author:
            y += avatar_size + 20
        else:
            y += 12
        if not hero and title_lines:
            y += len(title_lines) * L.F_TITLE_LINE_H + 14
        if desc_lines:
            y += len(desc_lines) * L.F_DESC_LINE_H + 16
        if stat_rows:
            y += len(stat_rows) * (L.STAT_H + L.STAT_ROW_GAP) - L.STAT_ROW_GAP + 18
        if online_text:
            y += 38
        if warnings_h:
            y += warnings_h + 16
        if grid:
            y += grid_h + 16
        if quote_h:
            y += quote_h + 16
        y += L.FOOTER_H
        card_h = y
        total_h = card_h + 14

        # ================= 绘制底层 =================
        canvas = Image.new("RGBA", (self.width, total_h), (0, 0, 0, 0))

        # 阴影
        shadow = Image.new("RGBA", (self.width, total_h), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            (L.SHADOW_INSET, L.SHADOW_INSET, self.width - L.SHADOW_INSET, total_h - 2),
            radius=L.RADIUS + 2,
            fill=(0, 0, 0, theme.shadow_alpha),
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(L.SHADOW_BLUR))
        canvas.alpha_composite(shadow)

        # 卡片主体（垂直渐变 + 品牌色渗透光晕 + 圆角）
        grad = self.gradient(
            (self.width, card_h), theme.gradient_top, theme.gradient_bottom
        )
        glow = self.radial_glow(self.width, round(self.width * 0.9), accent_rgb, theme.glow_alpha)
        grad_rgba = grad.convert("RGBA")
        # 光晕与卡片同宽并从 (0,0) 覆盖，避免图层左缘产生内部接缝
        grad_rgba.alpha_composite(glow, (0, 0))
        mask = Image.new("L", (self.width, card_h), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, self.width - 1, card_h - 1), radius=L.RADIUS, fill=255
        )
        card = grad_rgba
        card.putalpha(mask)
        canvas.alpha_composite(card, (0, 0))

        draw = ImageDraw.Draw(canvas)
        # 卡片描边同样先画到透明层再混合，保证输出像素不透明
        border_layer = Image.new("RGBA", (self.width, card_h), (0, 0, 0, 0))
        ImageDraw.Draw(border_layer).rounded_rectangle(
            (0, 0, self.width - 1, card_h - 1), radius=L.RADIUS,
            outline=with_alpha(theme.border, theme.border_alpha), width=1,
        )
        canvas.alpha_composite(border_layer, (0, 0))

        y = 0
        if hero:
            # ============ 顶部横幅 ============
            hero_img = None
            try:
                hero_img = self.cover_fit(self.open_image(hero), self.width, hero_h)
                hero_img = self.rounded_image_top(hero_img, L.RADIUS)
            except Exception:
                hero_img = None
                logger.warning("横幅图片渲染失败，使用占位背景", exc_info=True)
            if hero_img is not None:
                canvas.alpha_composite(hero_img, (0, 0))
            else:
                ph = self.gradient(
                    (self.width, hero_h),
                    theme.placeholder_top, theme.placeholder_bottom,
                ).convert("RGBA")
                tint = Image.new(
                    "RGBA", (self.width, hero_h), (*accent_rgb, 40)
                )
                ph.alpha_composite(tint)
                ph = self.rounded_image_top(ph, L.RADIUS)
                canvas.alpha_composite(ph, (0, 0))

            # 柔和渐变 scrim：顶部保证徽章可读，底部保证标题可读
            canvas.alpha_composite(
                self.scrim(
                    self.width, hero_h,
                    start=L.TOP_SCRIM_END, max_alpha=L.TOP_SCRIM_ALPHA,
                    power=1.4, invert=True,
                ),
                (0, 0),
            )
            canvas.alpha_composite(
                self.scrim(
                    self.width, hero_h,
                    start=L.SCRIM_START, max_alpha=L.SCRIM_ALPHA,
                    power=L.SCRIM_POWER,
                ),
                (0, 0),
            )

            # 悬浮徽章组：平台徽标 + 类型 chip（毛玻璃）
            badge_y = L.HERO_BADGE_TOP
            badge_h = L.HERO_BADGE_H
            self.draw_hero_badge(
                canvas, pad, badge_y, badge_h, platform_pill_w,
                text=platform_text, accent_rgb=accent_rgb, dot=True,
                font_size=L.F_PLATFORM,
            )
            chip_x = pad + platform_pill_w + L.HERO_BADGE_GAP
            self.draw_hero_badge(
                canvas, chip_x, badge_y, badge_h, type_pill_w,
                text=content_type, accent_rgb=accent_rgb, dot=False,
                font_size=L.F_CHIP,
            )
            if ts:
                ts_w = self.text_width(ts, ts_font) + 32
                ts_x = self.width - pad - ts_w
                self.draw_hero_badge(
                    canvas, ts_x, badge_y, badge_h, ts_w,
                    text=ts, accent_rgb=accent_rgb, dot=False,
                    font_size=L.F_TIME, bold=False,
                )

            # 视频播放按钮（毛玻璃圆环）
            if is_video_hero:
                play_r = L.PLAY_R
                cx, cy = self.width // 2, hero_h // 2
                box = (cx - play_r, cy - play_r, cx + play_r, cy + play_r)
                self.glass(
                    canvas, box, play_r,
                    tint_rgb=(255, 255, 255), tint_alpha=34,
                    border_rgb=(255, 255, 255), border_alpha=110,
                    blur=8,
                )
                pd = ImageDraw.Draw(canvas)
                pd.polygon(
                    [
                        (cx - 12, cy - 18),
                        (cx - 12, cy + 18),
                        (cx + 20, cy),
                    ],
                    fill=(255, 255, 255, 245),
                )

            # 标题白色浮层（柔和投影 + 轻描边）
            if title_lines:
                ty = hero_h - len(title_lines) * L.F_TITLE_LINE_H - L.HERO_TITLE_BOTTOM
                shadow_layer = Image.new("RGBA", (self.width, hero_h), (0, 0, 0, 0))
                sd = ImageDraw.Draw(shadow_layer)
                sy = ty
                for line in title_lines:
                    self.draw_text(
                        sd, (pad, sy + 2), line, L.F_TITLE,
                        (0, 0, 0, 140), bold=True,
                    )
                    sy += L.F_TITLE_LINE_H
                canvas.alpha_composite(
                    shadow_layer.filter(ImageFilter.GaussianBlur(4)), (0, 0)
                )
                # 标题与描边画到独立层后整体混合，避免半透明描边像素直接替换
                text_layer = Image.new("RGBA", (self.width, hero_h), (0, 0, 0, 0))
                td = ImageDraw.Draw(text_layer)
                for line in title_lines:
                    self.draw_text(
                        td, (pad, ty), line, L.F_TITLE,
                        (255, 255, 255, 255), bold=True,
                        stroke_width=1, stroke_fill=(0, 0, 0, 80),
                    )
                    ty += L.F_TITLE_LINE_H
                canvas.alpha_composite(text_layer, (0, 0))
                draw = ImageDraw.Draw(canvas)
            y = hero_h + 20
        else:
            # ============ 纯文本卡片头部 ============
            # accent 短横条（品牌色渐变淡出）
            bar = Image.new("RGBA", (L.HEAD_BAR_W, L.HEAD_BAR_H), (0, 0, 0, 0))
            for xx in range(L.HEAD_BAR_W):
                a = int(230 * (1 - xx / max(L.HEAD_BAR_W - 1, 1)) ** 1.3)
                ImageDraw.Draw(bar).line(
                    [(xx, 0), (xx, L.HEAD_BAR_H)], fill=(*accent_rgb, a)
                )
            bar = self.rounded_image(bar, L.HEAD_BAR_H // 2)
            canvas.alpha_composite(bar, (pad, L.HEAD_BAR_TOP))

            y = L.HEAD_BAR_TOP + L.HEAD_BAR_H + 18
            # 平台徽标（毛玻璃 + accent 圆点）
            self.draw_flat_badge(
                canvas, theme, pad, y, L.HEAD_PILL_H, platform_pill_w,
                text=platform_text, accent_rgb=accent_rgb, dot=True,
                font_size=L.F_PLATFORM, bold=True, text_rgb=theme.text_primary,
            )
            # 类型与时间弱化为辅助文字
            type_x = pad + platform_pill_w + 16
            type_lh = self.line_height(chip_font)
            self.draw_text(
                draw,
                (type_x, y + (L.HEAD_PILL_H - type_lh) // 2),
                content_type, L.F_CHIP, theme.text_tertiary, bold=True,
            )
            if ts:
                ts_w = self.text_width(ts, ts_font)
                ts_lh = self.line_height(ts_font)
                self.draw_text(
                    draw,
                    (self.width - pad - ts_w, y + (L.HEAD_PILL_H - ts_lh) // 2),
                    ts, L.F_TIME, theme.text_tertiary,
                )
            y += L.HEAD_PILL_H + 18

        # ============ 作者行 ============
        if author:
            avatar_path = self.images.get("avatar")
            avatar = None
            if avatar_path:
                try:
                    avatar = self.circle_avatar(
                        self.open_image(avatar_path), avatar_size
                    )
                except Exception:
                    avatar = None
            if avatar is not None:
                canvas.alpha_composite(avatar, (pad, y))
                ring = Image.new("RGBA", (avatar_size, avatar_size), (0, 0, 0, 0))
                ImageDraw.Draw(ring).ellipse(
                    (1, 1, avatar_size - 2, avatar_size - 2),
                    outline=with_alpha(accent_rgb, 170), width=L.AVATAR_RING_W,
                )
                canvas.alpha_composite(ring, (pad, y))
            else:
                # 无头像时绘制 accent 渐变首字母占位圆
                placeholder = self.gradient(
                    (avatar_size, avatar_size),
                    accent_rgb, mix(accent_rgb, (0, 0, 0), 0.35),
                ).convert("RGBA")
                pmask = Image.new("L", (avatar_size, avatar_size), 0)
                ImageDraw.Draw(pmask).ellipse(
                    (0, 0, avatar_size - 1, avatar_size - 1), fill=255
                )
                placeholder.putalpha(pmask)
                canvas.alpha_composite(placeholder, (pad, y))
                first = name[:1].upper()
                f_font = self.font(L.F_INITIAL, bold=True)
                fw = self.text_width(first, f_font)
                self.draw_text(
                    draw,
                    (pad + (avatar_size - fw) // 2, y + (avatar_size - self.line_height(f_font)) // 2),
                    first, L.F_INITIAL, "#FFFFFF", bold=True,
                )
            name_x = pad + avatar_size + 20
            self.draw_text(
                draw, (name_x, y + 6), name, L.F_NAME, theme.text_primary, bold=True
            )
            if author_desc:
                self.draw_text(
                    draw, (name_x, y + avatar_size - 26),
                    author_desc, L.F_SIGN, theme.text_tertiary,
                )
            y += avatar_size + 20
        else:
            y += 12

        # ============ 标题（非横幅模式） ============
        if not hero and title_lines:
            for line in title_lines:
                self.draw_text(
                    draw, (pad, y), line, L.F_TITLE, theme.text_primary, bold=True
                )
                y += L.F_TITLE_LINE_H
            y += 14

        # ============ 简介 ============
        if desc_lines:
            for line in desc_lines:
                self.draw_text(draw, (pad, y), line, L.F_DESC, theme.text_secondary)
                y += L.F_DESC_LINE_H
            y += 16

        # ============ 统计徽章（毛玻璃药丸：标签弱化 + 数值强调） ============
        if stat_rows:
            label_font = self.font(L.F_STAT_LABEL)
            value_font = self.font(L.F_STAT_VALUE, bold=True)
            for row in stat_rows:
                x = pad
                for label, value in row:
                    w = self.stat_pill_width(label, value)
                    self.glass(
                        canvas, (x, y, x + w, y + L.STAT_H), L.STAT_H // 2,
                        tint_rgb=theme.stat_pill_bg, tint_alpha=theme.frost_alpha,
                        border_rgb=theme.stat_pill_bg,
                        border_alpha=theme.frost_border_alpha,
                        blur=6,
                    )
                    label_w = self.text_width(label, label_font)
                    tx = x + L.STAT_PAD_X
                    if value:
                        self.draw_text(
                            draw,
                            (tx, y + (L.STAT_H - self.line_height(label_font)) // 2),
                            label, L.F_STAT_LABEL, theme.text_tertiary,
                        )
                        self.draw_text(
                            draw,
                            (tx + label_w + L.STAT_LABEL_VALUE_GAP,
                             y + (L.STAT_H - self.line_height(value_font)) // 2),
                            value, L.F_STAT_VALUE, theme.text_primary, bold=True,
                        )
                    else:
                        self.draw_text(
                            draw,
                            (tx, y + (L.STAT_H - self.line_height(label_font)) // 2),
                            label, L.F_STAT_LABEL, theme.text_secondary,
                        )
                    x += w + L.STAT_GAP
                y += L.STAT_H + L.STAT_ROW_GAP
            y += 18 - L.STAT_ROW_GAP

        # ============ 在线人数（accent 圆点 + 文字） ============
        if online_text:
            online_font = self.font(L.F_ONLINE)
            if self.text_width(online_text, online_font) <= inner_w - 18:
                dot_r = 4
                dot_cy = y + self.line_height(online_font) // 2
                draw.ellipse(
                    (pad, dot_cy - dot_r, pad + dot_r * 2, dot_cy + dot_r),
                    fill=accent,
                )
                self.draw_text(
                    draw, (pad + 18, y), online_text, L.F_ONLINE, accent
                )
            y += 38

        # ============ 警告提示块 ============
        if limit_warnings:
            y = self.draw_warning_block(canvas, draw, theme, limit_warnings, y, inner_w) + 16
            draw = ImageDraw.Draw(canvas)

        # ============ 图集网格 ============
        if grid:
            try:
                show = cols * rows
                over = len(grid) - show if len(grid) > show else 0
                for idx, path in enumerate(grid[:show]):
                    r, c = divmod(idx, cols)
                    x = pad + c * (cell_h + gap)
                    yy = y + r * (cell_h + gap)
                    try:
                        img = self.cover_fit(self.open_image(path), cell_h, cell_h)
                        img = self.rounded_image(img, L.GRID_RADIUS)
                        canvas.alpha_composite(img, (x, yy))
                    except Exception:
                        ph_layer = Image.new(
                            "RGBA", (cell_h, cell_h), (0, 0, 0, 0)
                        )
                        ImageDraw.Draw(ph_layer).rounded_rectangle(
                            (0, 0, cell_h - 1, cell_h - 1), radius=L.GRID_RADIUS,
                            fill=with_alpha(theme.pill_bg, 14),
                        )
                        canvas.alpha_composite(ph_layer, (x, yy))
                    if idx == show - 1 and over > 0:
                        canvas.alpha_composite(
                            self.scrim(
                                cell_h, cell_h, start=0.0, max_alpha=150, power=1.2
                            ),
                            (x, yy),
                        )
                        plus_font = self.font(L.F_PLUS, bold=True)
                        plus_text = f"+{over}"
                        pw = self.text_width(plus_text, plus_font)
                        self.draw_text(
                            draw,
                            (x + (cell_h - pw) // 2, yy + (cell_h - self.line_height(plus_font)) // 2),
                            plus_text, L.F_PLUS, "#FFFFFF", bold=True,
                        )
                y += grid_h + 20
            except Exception:
                logger.warning("图集渲染失败，已跳过", exc_info=True)
                y -= grid_h + 20

        # ============ 转发引用（毛玻璃容器 + accent 竖条） ============
        if self.result.repost and quote_h:
            qy = y
            self.glass(
                canvas, (pad, qy, pad + inner_w, qy + quote_h), L.QUOTE_RADIUS,
                tint_rgb=theme.quote_bg, tint_alpha=theme.frost_alpha,
                border_rgb=theme.quote_bg, border_alpha=theme.frost_border_alpha,
                blur=6,
            )
            bar_layer = Image.new(
                "RGBA", (L.QUOTE_BAR_W + 2, quote_h - 32), (0, 0, 0, 0)
            )
            ImageDraw.Draw(bar_layer).rounded_rectangle(
                (0, 0, L.QUOTE_BAR_W + 1, quote_h - 33),
                radius=L.QUOTE_BAR_W // 2,
                fill=with_alpha(accent_rgb, 230),
            )
            canvas.alpha_composite(bar_layer, (pad + 18, qy + 16))
            self.draw_quote_text(
                draw, self.result.repost, pad + 18 + L.QUOTE_BAR_W + 16, qy + 16,
                inner_w - 18 * 2 - L.QUOTE_BAR_W - 16, theme,
            )
            y += quote_h + 20

        # ============ 页脚（链接 + 「莉卡解析」徽标水印） ============
        divider_layer = Image.new("RGBA", (inner_w, 1), (0, 0, 0, 0))
        ImageDraw.Draw(divider_layer).line(
            (0, 0, inner_w - 1, 0),
            fill=with_alpha(theme.divider, theme.divider_alpha),
            width=1,
        )
        canvas.alpha_composite(divider_layer, (pad, y + 12))
        foot_y = y + 28

        wm_text = "莉卡解析"
        wm_font = self.font(L.F_FOOT, bold=True)
        wm_text_w = self.text_width(wm_text, wm_font)
        wm_lh = self.line_height(wm_font)
        dot_d = L.WM_DOT
        wm_group_w = dot_d + L.WM_DOT_GAP + wm_text_w
        wm_x = self.width - pad - wm_group_w
        # 水印：accent 小圆点 + 文字
        dot_cy = foot_y + wm_lh // 2
        draw.ellipse(
            (wm_x, dot_cy - dot_d // 2, wm_x + dot_d, dot_cy + dot_d // 2),
            fill=(*accent_rgb, 255),
        )
        self.draw_text(
            draw, (wm_x + dot_d + L.WM_DOT_GAP, foot_y),
            wm_text, L.F_FOOT, accent, bold=True,
        )

        url_text = short_url(self.result.url)
        if url_text:
            url_font = self.font(L.F_FOOT)
            avail_w = wm_x - pad - 20
            while url_text and self.text_width(url_text, url_font) > avail_w:
                url_text = url_text[:-1]
            if url_text:
                self.draw_text(
                    draw, (pad, foot_y), url_text, L.F_FOOT, theme.text_tertiary
                )

        # ---------- 保存 ----------
        return self.save(canvas, self.out_path)



register_style(StyleSpec(style_cls=StandardStyle, priority=10))
