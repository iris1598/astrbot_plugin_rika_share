"""卡片渲染基础：Pillow 可用性探测、布局尺寸常量、配色主题与颜色工具。"""

from __future__ import annotations

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
except ImportError:  # pragma: no cover - Pillow 为必需依赖，缺失时渲染自动降级
    Image = ImageDraw = ImageFilter = ImageFont = ImageOps = None

if Image is not None:
    # Pillow >= 9.1 使用 Image.Resampling，更早版本直接挂在 Image 上
    LANCZOS = getattr(Image, "Resampling", Image).LANCZOS
else:  # pragma: no cover
    LANCZOS = None


class L:
    """布局 / 字号 / 圆角 / 透明度常量表（重设计后所有魔法数字集中于此）"""

    # --- 画布 ---
    PAD = 44                  # 卡片左右内边距
    RADIUS = 30               # 卡片圆角
    GRID_GAP = 12             # 图集网格间距
    SHADOW_BLUR = 16          # 投影高斯半径
    SHADOW_INSET = 10         # 投影内缩

    # --- 顶部横幅 ---
    HERO_RATIO = 9 / 16       # 横幅宽高比
    HERO_BADGE_TOP = 24       # 悬浮徽章距顶
    HERO_BADGE_H = 42         # 悬浮徽章高度
    HERO_BADGE_GAP = 10       # 徽章间距
    HERO_TITLE_BOTTOM = 30    # 标题距横幅底部
    SCRIM_START = 0.38        # 底部 scrim 起始位置（高度比例）
    SCRIM_POWER = 1.6         # 底部 scrim 缓动指数
    SCRIM_ALPHA = 205         # 底部 scrim 最大透明度
    TOP_SCRIM_ALPHA = 90      # 顶部 scrim 最大透明度（徽章可读性）
    TOP_SCRIM_END = 0.30      # 顶部 scrim 结束位置
    PLAY_R = 46               # 播放按钮半径

    # --- 纯文本头部 ---
    HEAD_BAR_W = 64           # accent 短横条宽度
    HEAD_BAR_H = 6            # accent 短横条高度
    HEAD_BAR_TOP = 24         # accent 短横条距顶
    HEAD_PILL_H = 42          # 平台徽章高度

    # --- 作者行 ---
    AVATAR = 72               # 头像直径
    AVATAR_RING_W = 2         # 头像描边环宽

    # --- 统计徽章 ---
    STAT_H = 40               # 统计药丸高度
    STAT_PAD_X = 18           # 统计药丸水平内边距
    STAT_GAP = 10             # 药丸间距
    STAT_ROW_GAP = 12         # 药丸行距
    STAT_LABEL_VALUE_GAP = 6  # 标签与数值间距

    # --- 图集 ---
    GRID_RADIUS = 18          # 图集圆角
    GRID_SINGLE_MAX = 460     # 单图最大边长

    # --- 引用 ---
    QUOTE_RADIUS = 18
    QUOTE_BAR_W = 6

    # --- 页脚 ---
    FOOTER_H = 108
    WM_DOT = 10               # 水印圆点直径
    WM_DOT_GAP = 8            # 水印圆点与文字间距

    # --- 毛玻璃 ---
    GLASS_BLUR = 10           # 毛玻璃背景模糊半径
    HERO_GLASS_TINT = (12, 15, 24)      # 横幅上毛玻璃底色
    HERO_GLASS_TINT_ALPHA = 105
    HERO_GLASS_BORDER_ALPHA = 64

    # --- 字号 ---
    F_PLATFORM = 22
    F_CHIP = 20
    F_TIME = 19
    F_TITLE = 36
    F_TITLE_LINE_H = 52
    F_DESC = 25
    F_DESC_LINE_H = 40
    F_STAT_LABEL = 20
    F_STAT_VALUE = 21
    F_NAME = 26
    F_SIGN = 19
    F_ONLINE = 21
    F_QUOTE = 24
    F_QUOTE_LINE_H = 36
    F_FOOT = 20
    F_PLUS = 36
    F_INITIAL = 26


# ============================ 主题与平台配色 ============================

PLATFORM_COLORS = {
    "bilibili": "#FB7299",
    "douyin": "#2EF2EE",
    "kuaishou": "#FF7E00",
    "weibo": "#FF8200",
    "xiaohongshu": "#FF2442",
    "twitter": "#55ACEE",
    "acfun": "#FD4C5D",
    "nga": "#66C0F4",
    "youtube": "#FF4E45",
    "tiktok": "#2EF2EE",
    "website": "#8B7CF6",
    "default": "#8B7CF6",
}


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def with_alpha(rgb: tuple[int, int, int], alpha: int) -> tuple[int, int, int, int]:
    return (rgb[0], rgb[1], rgb[2], alpha)


def mix(
    a: tuple[int, int, int], b: tuple[int, int, int], ratio: float
) -> tuple[int, int, int]:
    """按 ratio 将颜色 a 向 b 混合。"""
    return tuple(round(a[i] + (b[i] - a[i]) * ratio) for i in range(3))  # type: ignore[return-value]


class Theme:
    """一套卡片配色方案"""

    def __init__(
        self,
        *,
        gradient_top: str,
        gradient_bottom: str,
        border: str,
        text_primary: str,
        text_secondary: str,
        text_tertiary: str,
        pill_bg: str,
        quote_bg: str,
        divider: str,
        shadow_alpha: int,
        stat_pill_bg: str,
        glow_alpha: int,
        frost_alpha: int,
        frost_border_alpha: int,
        border_alpha: int,
        placeholder_top: tuple[int, int, int],
        placeholder_bottom: tuple[int, int, int],
    ):
        self.gradient_top = hex_to_rgb(gradient_top)
        self.gradient_bottom = hex_to_rgb(gradient_bottom)
        self.border = hex_to_rgb(border)
        self.text_primary = hex_to_rgb(text_primary)
        self.text_secondary = hex_to_rgb(text_secondary)
        self.text_tertiary = hex_to_rgb(text_tertiary)
        self.pill_bg = hex_to_rgb(pill_bg)
        self.quote_bg = hex_to_rgb(quote_bg)
        self.divider = hex_to_rgb(divider)
        self.shadow_alpha = shadow_alpha
        self.stat_pill_bg = hex_to_rgb(stat_pill_bg)
        self.glow_alpha = glow_alpha
        self.frost_alpha = frost_alpha
        self.frost_border_alpha = frost_border_alpha
        self.border_alpha = border_alpha
        self.placeholder_top = placeholder_top
        self.placeholder_bottom = placeholder_bottom


THEMES = {
    # 深色：深海军蓝层次渐变 + 低饱和品牌色渗透光晕
    "dark": Theme(
        gradient_top="#242B3F",
        gradient_bottom="#12161F",
        border="#FFFFFF",
        text_primary="#F5F7FC",
        text_secondary="#AEB6C8",
        text_tertiary="#7B8598",
        pill_bg="#FFFFFF",
        quote_bg="#FFFFFF",
        divider="#FFFFFF",
        shadow_alpha=130,
        stat_pill_bg="#FFFFFF",
        glow_alpha=30,
        frost_alpha=14,
        frost_border_alpha=26,
        border_alpha=24,
        placeholder_top=(44, 51, 71),
        placeholder_bottom=(20, 24, 35),
    ),
    # 浅色：干净近白底 + 极轻品牌色光晕
    "light": Theme(
        gradient_top="#FFFFFF",
        gradient_bottom="#F1F4F9",
        border="#1B2233",
        text_primary="#1A2130",
        text_secondary="#55607A",
        text_tertiary="#8C95A9",
        pill_bg="#1B2233",
        quote_bg="#1B2233",
        divider="#1B2233",
        shadow_alpha=55,
        stat_pill_bg="#1B2233",
        glow_alpha=16,
        frost_alpha=10,
        frost_border_alpha=20,
        border_alpha=14,
        placeholder_top=(228, 233, 242),
        placeholder_bottom=(243, 246, 251),
    ),
}

# 可选卡片布局：standard 标准横幅 / magazine 双栏杂志 /
# immersive 沉浸全屏 / feed 社交动态流
LAYOUT_NAMES = ("standard", "magazine", "immersive", "feed")
