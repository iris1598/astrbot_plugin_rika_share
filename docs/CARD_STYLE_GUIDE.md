# 卡片主题（Card Style）开发指南

本文档面向插件开发者，说明如何在 `astrbot_plugin_rika_share` 中新增或定制基于 Pillow 的分享卡片渲染样式（Card Style）。

---

## 一、自动发现与注册机制

### 1.1 目录与发现流程

所有卡片样式模块放置在 [link_parser/services/card_render/styles/](../link_parser/services/card_render/styles) 目录下，扩展模块需遵循以下规则（定义于 [__init__.py](../link_parser/services/card_render/styles/__init__.py) 与 [registry.py](../link_parser/services/card_render/styles/registry.py)）：

- `_discover_styles()` 会自动扫描 `styles/` 下的子模块，自动跳过 `_NON_STYLE_MODULES`（`base`、`registry`）和以下划线 `_` 开头的模块。
- 所有已注册样式名汇总于 `STYLE_NAMES`，WebUI 的「卡片工作室」与配置 Schema 会自动识别新增样式，**无需修改前端硬编码列表**。
- 可直接对照内置实现作为参考模板：
  - [standard.py](../link_parser/services/card_render/styles/standard.py)（经典卡片）
  - [immersive.py](../link_parser/services/card_render/styles/immersive.py)（无封面时自动回退）
  - [feed.py](../link_parser/services/card_render/styles/feed.py)（信息流布局）

### 1.2 命名规范与元数据

- `name` 必须匹配正则 `^[a-z][a-z0-9_]*$`（小写字母开头，仅含小写字母、数字和下划线）。
- `display_name` 为必填非空字符串，将直接展示在 WebUI 样式选择器与预览卡片中。
- `DEFAULT_PRIORITY = 100`，内置样式优先级为 `10`–`40`；数值越小展示排序越靠前。
- `DEFAULT_STYLE = "standard"`。
- 注册查询与遍历函数：`register_style`、`get_style`、`iter_styles`、`style_names`。

---

## 二、`CardStyle` 类结构与核心配置

新样式需继承 [base.py](../link_parser/services/card_render/styles/base.py) 中的 `CardStyle`（继承自 `DrawingKit`），并在模块末尾调用 `register_style(StyleSpec(...))`。

### 2.1 类属性说明

| 属性 | 类型 / 默认值 | 说明 |
| :--- | :--- | :--- |
| `name` | `str` | 唯一标识符，需符合 `^[a-z][a-z0-9_]*$` |
| `display_name` | `str` | 展示名称（必填且非空） |
| `description` | `str` | 样式一句话简介 |
| `version` | `int = 1` | 样式版本号；**每次改动视觉布局都应递增**，使旧缓存底图自动失效重绘 |
| `priority` | `int = 100` | 样式列表排序权重（内置样式 `10`–`40`） |
| `fallback` | `str \| None = None` | 当 `can_render()` 返回 `False` 时的降级样式名（未指定时回退到 `standard`） |
| `palettes` | `tuple[str, ...] \| None = None` | 声明支持的色板（如 `("dark", "light")`），不限可设为 `None` |
| `supports_dynamic_footer` | `bool = True` | 是否支持底图复用 + 动态水印页脚叠加（见 3.2 节） |

### 2.2 最小可运行模板

在 `link_parser/services/card_render/styles/minimal_demo.py` 新建样式示例：

```python
from pathlib import Path
from PIL import Image, ImageDraw

from .base import CardStyle
from .registry import StyleSpec, register_style


class MinimalDemoStyle(CardStyle):
    name = "minimal_demo"
    display_name = "极简演示卡"
    description = "展示 CardStyle 基本渲染流与动态页脚接法"
    version = 1
    priority = 110
    fallback = "standard"
    palettes = ("dark", "light")
    supports_dynamic_footer = True

    def can_render(self) -> bool:
        # 可在此检查必要素材是否存在，例如：return bool(self.data["title"] or self.images.get("hero"))
        return True

    def render(self) -> Path:
        data = self.data
        title = data.get("title") or data.get("platform_text") or "分享内容"

        canvas_w = self.width
        y = self.pad
        title_font = self.font(28, bold=True)

        # 预估画布高度，绘制完正文后由 footer_block 计算页脚位置
        canvas_h = 360
        canvas = Image.new("RGBA", (canvas_w, canvas_h), self.theme.gradient_top)
        draw = ImageDraw.Draw(canvas)

        draw.text((self.pad, y), title[:40], font=title_font, fill=self.theme.text_primary)
        y += 64

        footer_bottom = self.footer_block(
            canvas,
            draw,
            self.theme,
            self.accent,
            self.accent_rgb,
            self.result,
            y,
            self.inner_w,
            on_image=False,
        )
        if footer_bottom < canvas_h:
            canvas = canvas.crop((0, 0, canvas_w, footer_bottom + self.pad))

        # 必须通过 self.save 返回，才能同时兼容磁盘输出和 WebUI in_memory=True 预览
        return self.save(canvas, self.out_path)


STYLE = register_style(StyleSpec(style_cls=MinimalDemoStyle, priority=MinimalDemoStyle.priority))
```

> [!IMPORTANT]
> `render()` 末尾必须返回 `self.save(canvas, self.out_path)`，切勿绕过 `self.save` 直接写文件。`ShareCardRenderer` 在 WebUI 实时预览路径下会传入 `in_memory=True`（`_render_preview_sync`），`self.save` 负责在磁盘写入与内存字节流之间切换。

---

## 三、渲染管线、`Theme` 与 `DrawingKit` 工具箱

### 3.1 渲染调度与自动降级

[renderer.py](../link_parser/services/card_render/renderer.py) 中的 `ShareCardRenderer` 负责协调样式选择、缓存与预览：

- `_instantiate_effective_style` 会检查目标样式的 `can_render()`：若返回 `False`（例如没有封面图），会自动降级到 `fallback` 指定的样式，直至 `DEFAULT_STYLE`（`"standard"`）。
- `self.width` 在管线中会被限制在 `520..1080` 像素区间内，样式代码应全部基于 `self.width`、`self.inner_w` 与 `self.pad` 做相对排版，不要写死宽度。

### 3.2 动态页脚与 `.anchor.json` 底图复用

当 `supports_dynamic_footer = True` 时：

1. 首次生成“底图”阶段，渲染器会将 `self.watermark_text` 设为 `None`，样式调用 `self.footer_block(...)` 预留页脚空间并记录 `_footer_anchor` 锚点。
2. 渲染器会将锚点信息随底图一同写入 `.anchor.json`；后续仅变更页脚水印文案时无需重绘整卡，可直接在缓存底图上叠加新水印。
3. 若你的样式页脚需要叠在封面图片上，可传 `on_image=True`（参见 [immersive.py](../link_parser/services/card_render/styles/immersive.py)）。

### 3.3 `CardStyle` 上下文与 `data` 预处理字段

实例初始化后可直接读取以下属性（详见 [toolkit.py](../link_parser/services/card_render/toolkit.py) 与 [theme.py](../link_parser/services/card_render/theme.py)）：

- **尺寸与边距**：`self.width`、`self.inner_w`、`self.pad`（默认 `L.PAD = 44`）、`self.gap`（默认 `L.GRID_GAP = 12`）、`self.cover_full_size`。
- **配色与色板**：
  - `self.theme_name` 与 `self.theme`（`Theme` 对象，内置 `"dark"` 与 `"light"` 两套，含 `gradient_top`、`gradient_bottom`、`border`、`text_primary`、`text_secondary`、`text_tertiary`、`pill_bg`、`quote_bg`、`divider`、`shadow_alpha`、`stat_pill_bg`、`glow_alpha`、`frost_alpha`、`frost_border_alpha`、`border_alpha`、`placeholder_top`、`placeholder_bottom`、`is_dark`、`divider_alpha`）。
  - `self.accent` / `self.accent_rgb`：按 `PLATFORM_COLORS` 自动映射平台主题色（未收录平台回退 `#8B7CF6`），可搭配 `hex_to_rgb`、`with_alpha`、`mix` 辅助函数。
- **输入结果与预处理缓存 `self.data`**（通过 `prepare()` 生成并缓存）：
  - `self.result`（原始 `ParseResult`）
  - `self.images`（已拉取的 `avatar`、`hero`、`grid` 图片对象）
  - `self.data` 字典常用键：`is_video_hero`、`hero`、`grid`、`platform_text`、`content_type`、`ts`、`title`、`text`、`author`、`name`、`author_desc`、`stats`、`online_text`、`warnings`。

### 3.4 `DrawingKit` 常用绘图组件一览

编写复杂样式时可直接复用以下基类方法（具体参数以各方法签名及内置样式调用为准）：

- **画布与保存**：`base_canvas`、`gradient`、`glass`、`radial_glow`、`scrim`、`save(canvas, self.out_path)`
- **字体与排版**：`font(size, bold=False)`、`text_width`、`wrap`、`fit_lines`、`line_height`、`draw_text`
- **图像裁剪**：`cover_fit`、`rounded_image`、`circle_avatar`
- **业务区块**：`header_badges`、`avatar_block`、`stat_rows_height`、`draw_stat_rows`、`draw_online`、`warning_block_height`、`draw_warning_block`、`hero_aspect_height`、`draw_grid_block`、`draw_quote_block`、`footer_block(canvas, draw, theme, accent, accent_rgb, result, y, inner_w, on_image=False)`

---

## 四、边界降级建议与本地预览

### 4.1 边界处理检查清单

1. **无图场景**：如果样式强依赖 `self.images["hero"]`，请在 `can_render()` 返回 `False` 并配置 `fallback = "standard"`。
2. **长文本与高图**：结合 `fit_lines` / `wrap` 截断超长标题或正文；`cover_full_size` 为 `False` 时使用 `hero_aspect_height` 限制超长图高度。
3. **动态页脚兼容性**：只要渲染了 `footer_block(...)`，系统就能正确记录 `_footer_anchor`；若样式完全自定义页脚且不想走缓存水印叠加，可显式设置 `supports_dynamic_footer = False`。

### 4.2 预览与验收

1. **离线批量渲染脚本**：

```powershell
python scripts/preview_layouts.py
```

输出文件默认保存在 `scripts/.out/layouts/` 下，可一次查看多平台内容在新增样式与深浅色板下的渲染效果。

2. **WebUI 实时预览**：启动插件后打开 WebUI「卡片工作室」，页面会调用 `/preview/styles` 与 `/preview/card` 动态拉取缩略图与实时预览图（`in_memory=True`）。
