"""社交动态卡片样式。

作者行置顶，媒体内嵌为圆角块，原生 App 社交流
"""

from __future__ import annotations

from pathlib import Path

from ..theme import L, Image, ImageDraw
from .base import CardStyle
from .registry import StyleSpec, register_style


class FeedStyle(CardStyle):
    name = "feed"
    display_name = "社交动态"
    description = "作者行置顶，媒体内嵌为圆角块，原生 App 社交流"
    version = 1
    priority = 40
    palettes = ("dark", "light")

    def render(self) -> Path:
        """社交动态：作者行最前，媒体为内嵌圆角块。"""
        theme = self.theme
        accent = self.accent
        accent_rgb = self.accent_rgb
        pad = L.PAD
        inner_w = self.width - pad * 2
        gap = L.GRID_GAP
        d = self.data

        title_font = self.font(34, bold=True)
        title_lines = self.fit_lines(d["title"], title_font, inner_w, 3) if d["title"] else []
        desc_font = self.font(L.F_DESC)
        desc_lines = self.fit_lines(d["text"], desc_font, inner_w, 5) if d["text"] else []
        media_h = round(inner_w * 9 / 16) if d["hero"] else 0
        if d["hero"] and self.cover_full_size:
            media_h = self.hero_aspect_height(d["hero"], inner_w, media_h)
        stats_h, stat_rows = self.stat_rows_height(d, inner_w)
        warnings_h = self.warning_block_height(d["warnings"], inner_w)
        grid_h = self.grid_metrics(len(d["grid"]), inner_w, gap)[0]
        quote_h = self.measure_quote(self.result.repost, inner_w) if self.result.repost else 0

        # ---- 高度 ----
        y = 38
        if d["author"]:
            y += 68 + 20
        y += len(title_lines) * 48 + (12 if title_lines else 0)
        if desc_lines:
            y += len(desc_lines) * L.F_DESC_LINE_H + 16
        if media_h:
            y += media_h + 20
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

        canvas, draw = self.base_canvas(theme, accent_rgb, card_h)

        # 作者行最前（无顶部 accent 条/头部徽章）
        y = 38
        if d["author"]:
            self.avatar_block(canvas, draw, pad, y, 68, self.images, d, accent_rgb)
            draw = ImageDraw.Draw(canvas)
            name_x = pad + 68 + 20
            name_font = self.font(26, bold=True)
            name_w = self.text_width(d["name"], name_font)
            self.draw_text(draw, (name_x, y + 8), d["name"], 26, theme.text_primary, bold=True)
            # 平台小药丸跟在昵称后
            pill_font = self.font(17, bold=True)
            pill_w = 12 + 8 + 6 + self.text_width(d["platform_text"], pill_font) + 12
            pill_h = 30
            pill_y = y + 8 + (self.line_height(name_font) - pill_h) // 2
            self.glass(canvas, (name_x + name_w + 12, pill_y,
                                 name_x + name_w + 12 + pill_w, pill_y + pill_h),
                        pill_h // 2, theme.pill_bg, theme.frost_alpha,
                        theme.pill_bg, theme.frost_border_alpha, blur=6)
            draw = ImageDraw.Draw(canvas)
            dot_cy = pill_y + pill_h // 2
            draw.ellipse((name_x + name_w + 24, dot_cy - 4, name_x + name_w + 32, dot_cy + 4),
                         fill=(*accent_rgb, 255))
            self.draw_text(draw, (name_x + name_w + 24 + 14,
                                   pill_y + (pill_h - self.line_height(pill_font)) // 2),
                            d["platform_text"], 17, theme.text_secondary, bold=True)
            if d["author_desc"]:
                self.draw_text(draw, (name_x, y + 68 - 26), d["author_desc"], L.F_SIGN,
                                theme.text_tertiary)
            if d["ts"]:
                ts_font = self.font(L.F_TIME)
                ts_w = self.text_width(d["ts"], ts_font)
                self.draw_text(draw, (self.width - pad - ts_w, y + 12), d["ts"], L.F_TIME,
                                theme.text_tertiary)
            y += 68 + 20

        for line in title_lines:
            self.draw_text(draw, (pad, y), line, 34, theme.text_primary, bold=True)
            y += 48
        if title_lines:
            y += 12
        for line in desc_lines:
            self.draw_text(draw, (pad, y), line, L.F_DESC, theme.text_secondary)
            y += L.F_DESC_LINE_H
        if desc_lines:
            y += 16

        # 媒体内嵌圆角块（类型 chip 浮在媒体角上）
        if d["hero"]:
            try:
                img = self.cover_fit(self.open_image(d["hero"]), inner_w, media_h)
                img = self.rounded_image(img, 20)
                canvas.alpha_composite(img, (pad, y))
            except Exception:
                ph = self.gradient(
                    (inner_w, media_h), theme.placeholder_top, theme.placeholder_bottom
                ).convert("RGBA")
                ph.alpha_composite(Image.new("RGBA", (inner_w, media_h), (*accent_rgb, 40)))
                canvas.alpha_composite(self.rounded_image(ph, 20), (pad, y))
            chip_font = self.font(18, bold=True)
            chip_w = self.text_width(d["content_type"], chip_font) + 28
            self.draw_hero_badge(canvas, pad + 14, y + 14, 34, chip_w,
                                  text=d["content_type"], accent_rgb=accent_rgb, dot=False,
                                  font_size=18)
            if d["is_video_hero"]:
                r_ = L.PLAY_R
                cx, cy = self.width // 2, y + media_h // 2
                self.glass(canvas, (cx - r_, cy - r_, cx + r_, cy + r_), r_,
                            (255, 255, 255), 34, (255, 255, 255), 110, blur=8)
                ImageDraw.Draw(canvas).polygon(
                    [(cx - 12, cy - 18), (cx - 12, cy + 18), (cx + 20, cy)],
                    fill=(255, 255, 255, 245),
                )
            y += media_h + 20
            draw = ImageDraw.Draw(canvas)

        # 图集紧跟媒体块，统计徽章垫底（与原生社交流一致：正文 → 媒体 → 点赞评论）
        y = self.draw_grid_block(canvas, draw, theme, d["grid"], y, inner_w, gap)
        if stat_rows:
            y = self.draw_stat_rows(canvas, theme, stat_rows, pad, y) + 18
            draw = ImageDraw.Draw(canvas)
        if d["online_text"]:
            y = self.draw_online(draw, d, y, accent)
        if d["warnings"]:
            y = self.draw_warning_block(canvas, draw, theme, d["warnings"], y, inner_w) + 16
            draw = ImageDraw.Draw(canvas)
        y = self.draw_quote_block(canvas, ImageDraw.Draw(canvas), theme, accent_rgb, self.result, y, inner_w)
        self.footer_block(canvas, ImageDraw.Draw(canvas), theme, accent, accent_rgb, self.result, y, inner_w)

        return self.save(canvas, self.out_path)


register_style(StyleSpec(style_cls=FeedStyle, priority=40))
