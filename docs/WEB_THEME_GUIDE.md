# 网页主题（WebUI Theme）开发指南

本文档面向前端扩展与界面定制开发者，说明如何为 `astrbot_plugin_rika_share` 的内嵌控制台（WebUI）编写新的结构化布局与配色主题。

本插件的网页主题并非单纯更换色板，而是支持**配色令牌 + 导航形态（Sidebar / Dock）+ CSS 布局覆盖**的完整主题包体系。

---

## 一、文件位置与注册机制

### 1.1 目录结构

WebUI 主题系统位于 [views/rika/themes/](../views/rika/themes)：

- [registry.js](../views/rika/themes/registry.js)：主题注册表、DOM 属性同步与全局 API。
- [index.js](../views/rika/themes/index.js)：导入并导出所有内置主题模块，负责首屏集中注册。
- 内置参考主题：
  - [studio.js](../views/rika/themes/studio.js)（`DEFAULT_THEME_ID = "studio"`，经典侧栏工作台）
  - [glass-center.js](../views/rika/themes/glass-center.js)（居中性/毛玻璃风格 + 底部悬浮 Dock 导航）
- 基础样式表：[style.css](../views/rika/style.css)。

### 1.2 配置校验契约

后端配置项 `WEBUI_THEME`（定义于 [schema.py](../link_parser/config/schema.py)）采用开放正则约束，**无需修改后端白名单即可保存任意新主题 ID**：

- `type: "string"`
- `default: "studio"`
- `pattern: r"^[a-z][a-z0-9_-]*$"`（小写字母开头，可包含小写字母、数字、下划线或连字符）

颜色模式 `WEBUI_COLOR_MODE` 支持 `"auto"`、`"light"`、`"dark"`，对应 `VALID_COLOR_MODES`。

### 1.3 两种注册方式

1. **静态内置主题**：在 `views/rika/themes/<name>.js` 定义并调用 `registerTheme(...)`，随后在 [index.js](../views/rika/themes/index.js) 中引入该模块。
2. **运行时扩展注册**：`installGlobalThemeApi()` 会在全局挂载 `window.RikaWebTheme`，支持在运行时通过 `window.RikaWebTheme.registerTheme(spec)` 动态注册新主题。

注册表提供 `registerTheme`、`getTheme`、`listThemes` 与 `applyTheme` 四个核心函数。

---

## 二、`ThemeSpec` 规范与最小示例

### 2.1 `ThemeSpec` 字段说明

| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| `id` | `string` | 主题唯一 ID（自动转为小写；若需持久化保存需符合 `^[a-z][a-z0-9_-]*$`） |
| `name` | `string` | 主题显示名称（展示于主题切换器卡片） |
| `subtitle` | `string` | 简短副标题 |
| `description` | `string` | 主题特性描述文案 |
| `layout` | `string` | 布局标识（内置 `"studio"`、`"glass-center"`，或自定义标识，挂载到 `data-layout`） |
| `navMode` | `"sidebar" \| "dock"` | 导航结构模式（挂载到 `data-nav`，并决定设置页线框预览图样式） |
| `badge` | `string` | 角标文案 |
| `light` | `Record<string, string>` | 浅色模式下的 CSS 自定义属性映射 |
| `dark` | `Record<string, string>` | 深色模式下的 CSS 自定义属性映射 |
| `css` | `string` | 主题专属布局样式字符串，切换主题时动态注入 `<style id="rika-theme-layout-css">` |

> [!NOTE]
> WebUI「系统与外观」设置页中的主题预览卡片会根据 `navMode` 自动生成线框示意图：当 `navMode === "dock"` 时绘制底部悬浮导航栏线框，其余值默认绘制左侧边栏线框。

### 2.2 最小主题模块示例

在 `views/rika/themes/minimal-paper.js` 新建主题：

```javascript
import { registerTheme } from "./registry.js";

const COMMON_LAYOUT_CSS = `
[data-layout="minimal-paper"] .surface-panel {
  border-width: 1.5px;
}
[data-layout="minimal-paper"][data-nav="sidebar"] .shell-nav {
  backdrop-filter: var(--blur);
}
`;

export const minimalPaperTheme = {
  id: "minimal-paper",
  name: "素纸工作台",
  subtitle: "高对比留白 · 侧栏布局",
  description: "以纸面高对比排版与清爽边框为核心的轻量管理视图。",
  layout: "minimal-paper",
  navMode: "sidebar",
  badge: "自定义",
  light: {
    "--bg": "#f7f6f2",
    "--ambient": "radial-gradient(circle at 20% 0%, rgba(79, 70, 229, 0.08), transparent 48%)",
    "--surface": "#ffffff",
    "--surface-alt": "#f1efe9",
    "--surface-hover": "#eae7df",
    "--ink": "#18181b",
    "--ink-2": "#3f3f46",
    "--ink-muted": "#71717a",
    "--border": "rgba(24, 24, 27, 0.10)",
    "--border-strong": "rgba(24, 24, 27, 0.20)",
    "--accent": "#4f46e5",
    "--accent-hover": "#4338ca",
    "--accent-soft": "rgba(79, 70, 229, 0.12)",
    "--accent-ink": "#ffffff",
    "--ok": "#16a34a",
    "--warn": "#d97706",
    "--err": "#dc2626",
    "--radius": "10px",
    "--radius-lg": "16px",
    "--shadow": "0 8px 24px rgba(15, 23, 42, 0.06)",
    "--blur": "blur(12px)",
  },
  dark: {
    "--bg": "#121316",
    "--ambient": "radial-gradient(circle at 20% 0%, rgba(129, 140, 248, 0.14), transparent 50%)",
    "--surface": "#1a1c21",
    "--surface-alt": "#22252c",
    "--surface-hover": "#2a2e37",
    "--ink": "#f4f4f5",
    "--ink-2": "#d4d4d8",
    "--ink-muted": "#a1a1aa",
    "--border": "rgba(255, 255, 255, 0.09)",
    "--border-strong": "rgba(255, 255, 255, 0.18)",
    "--accent": "#818cf8",
    "--accent-hover": "#a5b4fc",
    "--accent-soft": "rgba(129, 140, 248, 0.16)",
    "--accent-ink": "#0f172a",
    "--ok": "#4ade80",
    "--warn": "#fbbf24",
    "--err": "#f87171",
    "--radius": "10px",
    "--radius-lg": "16px",
    "--shadow": "0 12px 30px rgba(0, 0, 0, 0.38)",
    "--blur": "blur(14px)",
  },
  css: COMMON_LAYOUT_CSS,
};

registerTheme(minimalPaperTheme);
```

随后在 [views/rika/themes/index.js](../views/rika/themes/index.js) 中导入 `./minimal-paper.js` 即可出现在主题列表中。

---

## 三、CSS 设计令牌（Tokens）参考表

基础样式表 [style.css](../views/rika/style.css) 与内置主题使用同一套 CSS 变量体系，建议在 `light` 与 `dark` 中保持完整定义：

| 分类 | CSS 变量名 | 用途 |
| :--- | :--- | :--- |
| **背景与表面** | `--bg`、`--ambient`、`--surface`、`--surface-alt`、`--surface-hover` | 页面底色、环境光晕、卡片表面及交互悬停态 |
| **文字与边框** | `--ink`、`--ink-2`、`--ink-muted`、`--border`、`--border-strong` | 主标题、二级正文、说明文字及常规/强调描边 |
| **品牌主色** | `--accent`、`--accent-hover`、`--accent-soft`、`--accent-ink` | 主按钮、激活态、浅底标签与主按钮反白字色 |
| **语义状态** | `--ok`、`--warn`、`--err` | 成功、警告、错误提示与状态徽章 |
| **圆角阴影字体** | `--radius`、`--radius-lg`、`--shadow`、`--blur`、`--font-sans`、`--font-mono` | 圆角半径、投影、毛玻璃模糊度与无衬线/等宽字体栈 |

---

## 四、DOM 契约与关键结构类名

### 4.1 根节点动态属性

调用 `applyTheme` 时，系统会在 `document.documentElement` 写入以下属性，主题的 `css` 字符串推荐以 `[data-layout="..."]` 与 `[data-nav="..."]` 作为作用域前缀：

- `data-theme="light" | "dark"`（当前生效明暗态）
- `data-color-mode="auto" | "light" | "dark"`（用户选择的模式）
- `data-rika-theme="<id>"`（当前主题 ID）
- `data-layout="<layout>"`（结构布局标识）
- `data-nav="<navMode>"`（导航栏形态）

### 4.2 编写自定义 `css` 时需兼顾的业务组件

在调整布局、边距或重构 Dock/Sidebar 时，请确保以下现有页面结构保持清晰可读与正常交互：

- **应用框架与导航**：`.app-shell`、`.shell-nav`、`.nav-brand`、`.nav-menu`、`.nav-btn`、`.nav-ico`、`.nav-label`、`.nav-foot`、`.theme-badge-btn`
- **主舞台与顶栏**：`.shell-content`、`.stage-header`、`.stage-heading`、`.dock-brand-mini`、`.topbar-theme-btn`、`.save-strip`、`.stage-body`、`.tab-panel`、`.page-stack`
- **作用域切换条（全局 / 分群管理）**：`.scope-bar`、`.scope-bar.is-group-scope`、`.scope-add-form`
- **面板与卡片工作室**：`.surface-panel`、`.kpi-grid`、`.studio-split`
- **三区域拖拽节点编排板**：`.node-zones-board`、`.node-zone`、`.node-drag-card`、`.node-quick-bar`
- **提示弹窗栈**：`.toast-stack`（若采用底部 Dock 布局，请注意配合 `[data-nav="dock"] .toast-stack` 避免底部提示条与悬浮 Dock 重叠）

---

## 五、沙箱与运行环境约束

1. **Iframe 沙箱限制**：WebUI 运行在 `sandbox="allow-scripts allow-forms allow-downloads"` 的 iframe 内，**不要依赖 `localStorage` 等同源持久存储 API**；主题选择与颜色模式通过宿主配置下发和保存。
2. **离线与内网可用性**：请避免在主题 `css` 中通过 `@import` 或外链加载公网字体或远程样式表，优先使用 CSS 变量、Flex/Grid 与本地系统字体栈，保证离线或纯局域网环境下正常加载。
3. **无构建依赖**：前端源码直接以原生 ES Modules 提供服务，改动主题文件后刷新控制台即可生效。
