"""双栏杂志卡片样式。

封面左置、标题作者右置，适合长文本与文章
"""

from __future__ import annotations

from pathlib import Path

from ..theme import L, Image, ImageDraw
from .base import CardStyle
from .registry import StyleSpec, register_style


class MagazineStyle(CardStyle):
    name = "magazine"
    display_name = "双栏杂志"
    description = "封面左置、标题作者右置，适合长文本与文章"
    version = 1
    priority = 20
    palettes = ("dark", "light")

    def render(self) -> Path:
        """双栏杂志：封面缩为左侧方块，标题/作者在右侧栏。"""
        theme = self.theme
        accent = self.accent
        accent_rgb = self.accent_rgb
        pad = L.PAD
        inner_w = self.width - pad * 2
        gap = L.GRID_GAP
        d = self.data

        cover_w = round(inner_w * 0.42) if d["hero"] else 0
        cover_h = self.hero_aspect_height(d["hero"], cover_w, cover_w) if d["hero"] else 0
        right_x = pad + cover_w + 26
        right_w = inner_w - cover_w - 26 if d["hero"] else inner_w

        title_font = self.font(33, bold=True)
        title_lines = (
            self.fit_lines(d["title"], title_font, right_w, 4 if d["hero"] else 3)
            if d["title"] else []
        )
        desc_font = self.font(L.F_DESC)
        desc_lines = self.fit_lines(d["text"], desc_font, inner_w, 4) if d["text"] else []
        stats_h, stat_rows = self.stat_rows_height(d, inner_w)
        warnings_h = self.warning_block_height(d["warnings"], inner_w)
        grid_h = self.grid_metrics(len(d["grid"]), inner_w, gap)[0]
        quote_h = self.measure_quote(self.result.repost, inner_w) if self.result.repost else 0

        # ---- 高度 ----
        y = L.HEAD_BAR_TOP + L.HEAD_BAR_H + 18 + L.HEAD_PILL_H + 20
        if d["hero"]:
            right_h = len(title_lines) * 46 + (18 + 56 if d["author"] else 0)
            y += max(cover_h, right_h) + 22
        else:
            y += len(title_lines) * L.F_TITLE_LINE_H + 14
            if d["author"]:
                y += L.AVATAR + 20
        if desc_lines:
            y += len(desc_lines) * L.F_DESC_LINE_H + 16
        if stats_h:
            y += stats_h + 18
        if d["online_text"]:
            y += 38
        if warnings_h:
            y += warnings_h + 16
        if grid_h:
            y += grid_h + 20
        if quote_h:
            y += quote_h + 20
        y += L.FOOTER_H
        card_h = y

        canvas, draw = self.base_canvas(theme, accent_rgb, card_h)
        y = self.header_badges(canvas, theme, accent_rgb, d) + 2

        if d["hero"]:
            # 左侧封面方块
            try:
                img = self.cover_fit(self.open_image(d["hero"]), cover_w, cover_h)
                img = self.rounded_image(img, 20)
                canvas.alpha_composite(img, (pad, y))
            except Exception:
                ph = self.gradient(
                    (cover_w, cover_h), theme.placeholder_top, theme.placeholder_bottom
                ).convert("RGBA")
                ph.alpha_composite(Image.new("RGBA", (cover_w, cover_h), (*accent_rgb, 40)))
                canvas.alpha_composite(self.rounded_image(ph, 20), (pad, y))
            if d["is_video_hero"]:
                r_ = 38
                cx, cy = pad + cover_w // 2, y + cover_h // 2
                self.glass(canvas, (cx - r_, cy - r_, cx + r_, cy + r_), r_,
                            (255, 255, 255), 34, (255, 255, 255), 110, blur=8)
                ImageDraw.Draw(canvas).polygon(
                    [(cx - 10, cy - 15), (cx - 10, cy + 15), (cx + 17, cy)],
                    fill=(255, 255, 255, 245),
                )
            # 右栏：标题 + 作者
            ry = y + 4
            draw = ImageDraw.Draw(canvas)
            for line in title_lines:
                self.draw_text(draw, (right_x, ry), line, 33, theme.text_primary, bold=True)
                ry += 46
            if d["author"]:
                ry += 18
                self.avatar_block(canvas, draw, right_x, ry, 56, self.images, d, accent_rgb)
                draw = ImageDraw.Draw(canvas)
                self.draw_text(draw, (right_x + 72, ry + 2), d["name"], 24, theme.text_primary, bold=True)
                if d["author_desc"]:
                    self.draw_text(draw, (right_x + 72, ry + 56 - 22), d["author_desc"], 18, theme.text_tertiary)
            y += max(cover_h, len(title_lines) * 46 + (18 + 56 if d["author"] else 0)) + 22
        else:
            for line in title_lines:
                self.draw_text(draw, (pad, y), line, L.F_TITLE, theme.text_primary, bold=True)
                y += L.F_TITLE_LINE_H
            y += 14
            if d["author"]:
                self.avatar_block(canvas, draw, pad, y, L.AVATAR, self.images, d, accent_rgb)
                draw = ImageDraw.Draw(canvas)
                name_x = pad + L.AVATAR + 20
                self.draw_text(draw, (name_x, y + 6), d["name"], L.F_NAME, theme.text_primary, bold=True)
                if d["author_desc"]:
                    self.draw_text(draw, (name_x, y + L.AVATAR - 26), d["author_desc"], L.F_SIGN, theme.text_tertiary)
                y += L.AVATAR + 20

        if desc_lines:
            for line in desc_lines:
                self.draw_text(draw, (pad, y), line, L.F_DESC, theme.text_secondary)
                y += L.F_DESC_LINE_H
            y += 16
        if stat_rows:
            y = self.draw_stat_rows(canvas, theme, stat_rows, pad, y) + 18
            draw = ImageDraw.Draw(canvas)
        if d["online_text"]:
            y = self.draw_online(draw, d, y, accent)
        if d["warnings"]:
            y = self.draw_warning_block(canvas, draw, theme, d["warnings"], y, inner_w) + 16
            draw = ImageDraw.Draw(canvas)
        y = self.draw_grid_block(canvas, draw, theme, d["grid"], y, inner_w, gap)
        y = self.draw_quote_block(canvas, ImageDraw.Draw(canvas), theme, accent_rgb, self.result, y, inner_w)
        self.footer_block(canvas, ImageDraw.Draw(canvas), theme, accent, accent_rgb, self.result, y, inner_w)

        return self.save(canvas, self.out_path)



register_style(StyleSpec(style_cls=MagazineStyle, priority=20))
