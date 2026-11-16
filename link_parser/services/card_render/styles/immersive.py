"""沉浸全屏卡片样式。

封面铺满整卡，文字浮于渐变遮罩上；无图回退 standard
"""

from __future__ import annotations

from pathlib import Path

from ..theme import L, Image, ImageDraw, ImageFilter
from .base import CardStyle
from .registry import StyleSpec, register_style


class ImmersiveStyle(CardStyle):
    name = "immersive"
    display_name = "沉浸全屏"
    description = "封面铺满整卡，文字浮于渐变遮罩上；无图回退 standard"
    version = 1
    priority = 30
    fallback = "standard"
    palettes = ("dark", "light")

    def can_render(self) -> bool:
        return bool(self.data["hero"])

    def render(self) -> Path:
        """沉浸全屏：封面铺满整卡，内容浮于渐变 scrim 上（无图回退标准布局）。"""
        theme = self.theme
        accent = self.accent
        accent_rgb = self.accent_rgb
        pad = L.PAD
        inner_w = self.width - pad * 2
        d = self.data

        title_font = self.font(L.F_TITLE, bold=True)
        title_lines = self.fit_lines(d["title"], title_font, inner_w, 2) if d["title"] else []
        stats_h, stat_rows = self.stat_rows_height(d, inner_w)
        warnings_h = self.warning_block_height(d["warnings"], inner_w)

        # 底部内容栈高度
        stack = 30
        if title_lines:
            stack += len(title_lines) * L.F_TITLE_LINE_H + 18
        if d["author"]:
            stack += 64 + 16
        if stats_h:
            stack += stats_h + 16
        if d["online_text"]:
            stack += 36
        if warnings_h:
            stack += warnings_h + 16
        stack += 96  # 页脚
        full_hero_h = self.hero_aspect_height(d["hero"], self.width, round(self.width * 1.02))
        card_h = max(full_hero_h, L.HERO_BADGE_TOP + L.HERO_BADGE_H + stack + 48)

        total_h = card_h + 14
        canvas = Image.new("RGBA", (self.width, total_h), (0, 0, 0, 0))
        shadow = Image.new("RGBA", (self.width, total_h), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            (L.SHADOW_INSET, L.SHADOW_INSET, self.width - L.SHADOW_INSET, total_h - 2),
            radius=L.RADIUS + 2, fill=(0, 0, 0, theme.shadow_alpha),
        )
        canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(L.SHADOW_BLUR)))

        # 封面铺满整卡
        try:
            img = self.cover_fit(self.open_image(d["hero"]), self.width, card_h)
            img = self.rounded_image(img, L.RADIUS)
            canvas.alpha_composite(img, (0, 0))
        except Exception:
            ph = self.gradient(
                (self.width, card_h), theme.placeholder_top, theme.placeholder_bottom
            ).convert("RGBA")
            ph.alpha_composite(Image.new("RGBA", (self.width, card_h), (*accent_rgb, 40)))
            canvas.alpha_composite(self.rounded_image(ph, L.RADIUS), (0, 0))

        # scrim：顶部徽章 + 底部内容区
        canvas.alpha_composite(
            self.scrim(self.width, card_h, start=0.22, max_alpha=110, power=1.4, invert=True), (0, 0)
        )
        content_top = card_h - stack
        scrim_start = max(0.0, (content_top - 70) / card_h)
        canvas.alpha_composite(
            self.scrim(self.width, card_h, start=scrim_start, max_alpha=225, power=1.5), (0, 0)
        )
        # 全卡极轻 accent 渗透
        tint_mask = self.scrim(self.width, card_h, start=0.0, max_alpha=26, power=1.0)
        tinted = Image.new("RGBA", (self.width, card_h), (*accent_rgb, 255))
        tinted.putalpha(tint_mask.split()[3])
        canvas.alpha_composite(tinted, (0, 0))

        draw = ImageDraw.Draw(canvas)
        # 顶部徽章
        pw = self.platform_pill_width(d["platform_text"])
        badge_y = L.HERO_BADGE_TOP
        self.draw_hero_badge(canvas, pad, badge_y, L.HERO_BADGE_H, pw,
                              text=d["platform_text"], accent_rgb=accent_rgb, dot=True,
                              font_size=L.F_PLATFORM)
        chip_font = self.font(L.F_CHIP, bold=True)
        type_w = self.text_width(d["content_type"], chip_font) + 36
        self.draw_hero_badge(canvas, pad + pw + L.HERO_BADGE_GAP, badge_y, L.HERO_BADGE_H, type_w,
                              text=d["content_type"], accent_rgb=accent_rgb, dot=False,
                              font_size=L.F_CHIP)
        if d["ts"]:
            ts_font = self.font(L.F_TIME)
            ts_w = self.text_width(d["ts"], ts_font) + 32
            self.draw_hero_badge(canvas, self.width - pad - ts_w, badge_y, L.HERO_BADGE_H, ts_w,
                                  text=d["ts"], accent_rgb=accent_rgb, dot=False,
                                  font_size=L.F_TIME, bold=False)

        # 播放按钮
        if d["is_video_hero"]:
            r_ = L.PLAY_R
            cx = self.width // 2
            cy = max(L.HERO_BADGE_TOP + L.HERO_BADGE_H + r_ + 20, content_top // 2 + 30)
            self.glass(canvas, (cx - r_, cy - r_, cx + r_, cy + r_), r_,
                        (255, 255, 255), 34, (255, 255, 255), 110, blur=8)
            ImageDraw.Draw(canvas).polygon(
                [(cx - 12, cy - 18), (cx - 12, cy + 18), (cx + 20, cy)],
                fill=(255, 255, 255, 245),
            )

        # ---- 底部内容栈（白色系文字） ----
        y = content_top + 10
        draw = ImageDraw.Draw(canvas)
        if title_lines:
            tl = Image.new("RGBA", (self.width, card_h), (0, 0, 0, 0))
            td = ImageDraw.Draw(tl)
            sy = y
            for line in title_lines:
                self.draw_text(td, (pad, sy + 2), line, L.F_TITLE,
                                (0, 0, 0, 130), bold=True)
                sy += L.F_TITLE_LINE_H
            canvas.alpha_composite(tl.filter(ImageFilter.GaussianBlur(4)), (0, 0))
            draw = ImageDraw.Draw(canvas)
            for line in title_lines:
                self.draw_text(draw, (pad, y), line, L.F_TITLE,
                                (255, 255, 255, 255), bold=True,
                                stroke_width=1, stroke_fill=(0, 0, 0, 70))
                y += L.F_TITLE_LINE_H
            y += 18
        if d["author"]:
            self.avatar_block(canvas, draw, pad, y, 64, self.images, d, accent_rgb)
            draw = ImageDraw.Draw(canvas)
            name_x = pad + 64 + 18
            self.draw_text(draw, (name_x, y + 6), d["name"], L.F_NAME, (255, 255, 255), bold=True)
            if d["author_desc"]:
                self.draw_text(draw, (name_x, y + 64 - 24), d["author_desc"], L.F_SIGN,
                                (255, 255, 255, 175))
            y += 64 + 16
        if stat_rows:
            label_font = self.font(L.F_STAT_LABEL)
            value_font = self.font(L.F_STAT_VALUE, bold=True)
            for row in stat_rows:
                x = pad
                for label, value in row:
                    w = self.stat_pill_width(label, value)
                    self.glass(canvas, (x, y, x + w, y + L.STAT_H), L.STAT_H // 2,
                                (255, 255, 255), 26, (255, 255, 255), 70, blur=8)
                    draw = ImageDraw.Draw(canvas)
                    label_w = self.text_width(label, label_font)
                    if value:
                        self.draw_text(draw, (x + L.STAT_PAD_X, y + (L.STAT_H - self.line_height(label_font)) // 2),
                                        label, L.F_STAT_LABEL, (255, 255, 255, 185))
                        self.draw_text(draw, (x + L.STAT_PAD_X + label_w + L.STAT_LABEL_VALUE_GAP,
                                               y + (L.STAT_H - self.line_height(value_font)) // 2),
                                        value, L.F_STAT_VALUE, (255, 255, 255), bold=True)
                    x += w + L.STAT_GAP
                y += L.STAT_H + L.STAT_ROW_GAP
            y += 16 - L.STAT_ROW_GAP
        if d["online_text"]:
            y = self.draw_online(draw, d, y, accent) - 2
        if d["warnings"]:
            y = self.draw_warning_block(canvas, draw, theme, d["warnings"], y, inner_w, on_image=True)
            draw = ImageDraw.Draw(canvas)
        self.footer_block(canvas, draw, theme, accent, accent_rgb, self.result, y, inner_w,
                           on_image=True)

        return self.save(canvas, self.out_path)



register_style(StyleSpec(style_cls=ImmersiveStyle, priority=30))
