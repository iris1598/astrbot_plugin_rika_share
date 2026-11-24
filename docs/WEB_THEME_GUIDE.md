# 网页主题（WebUI Theme）开发指南

本文档面向前端扩展与界面定制开发者，说明如何为 `astrbot_plugin_rika_share` 控制台（`views/rika/`）编写一套**完整独立的前端页面设计**。

在本插件中，网页主题**不是配色变量表或局部 CSS 皮肤**，而是一个**独立的整页前端应用包**：

- 每个主题独立拥有自己的 `manifest.json`、页面入口 `mount(mountEl, ctx)`、整页 DOM 架构、信息布局、交互流与隔离的 CSS 样式文件；
- 宿主仅提供极轻量的启动样式（[boot.css](../views/rika/boot.css)）与纯粹的无头业务运行时（[core/](../views/rika/core)）；
- 切换主题时，主题引擎会彻底卸载旧主题的 DOM、`onDispose` 订阅器、定时器与 `<head>` 中的样式标签，再全新挂载目标主题的页面与样式，主题之间**零 DOM / CSS 耦合与污染**。

---

## 一、架构总览与目录布局

```text
views/rika/
├── index.html                  # 极简挂载入口（仅加载 boot.css 与 app.js）
├── boot.css                    # 启动 Loading / 致命错误面板 / 默认 Toast 通知栈
├── app.js                      # 宿主协调器：拉取后端 /config，调度主题挂载与热切换
├── core/                       # 纯无头运行时 SDK（无任何页面 DOM 与风格假设）
│   ├── store.js                # 配置草稿、分群稀疏覆写作用域、平台开关与保存/重置状态
│   ├── controllers.js          # 异步控制器：B站扫码轮询 / 实时预览防抖 / 调试探针 / 清理缓存
│   ├── node_model.js           # 三模式输出节点编排纯数据模型与序列化工具
│   └── dom.js                  # iframe 沙箱安全 DOM 原语（h / swapContent / preserveScroll 等）
└── themes/
    ├── registry.js             # 整页主题生命周期引擎与 window.RikaWebTheme
    ├── studio/                 # 内置设计 1：工作台分栏（左侧栏 + 4 标签工程台）
    │   ├── manifest.json
    │   ├── index.js
    │   ├── theme.css
    │   ├── widgets.js
    │   └── views/
    └── glass-center/           # 内置设计 2：空间指挥舱（顶部指挥条 + Bento + 聊天真预览）
        ├── manifest.json
        ├── index.js
        └── theme.css
```

> [!TIP]
> 内置的两套主题正是同一无头核心下的两种彻底不同的页面设计：
> - [studio/](../views/rika/themes/studio)：左侧栏 + 独立全局/分群横栏 + 4 页签高密度表单工作台；
> - [glass-center/](../views/rika/themes/glass-center)：悬浮顶栏 + 底部空间 Dock + 驾驶舱 Bento 网格 + 模拟 IM 聊天气泡预览台 + 三泳道节点流水线。

---

## 二、发现与注册机制

### 2.1 目录包自动发现（推荐）

只需要在 `views/rika/themes/<theme_id>/` 下放入 `manifest.json`、入口 JS 及样式文件，**无需修改后端或前端任何注册清单文件**：

1. [webui.py](../link_parser/webui.py) 中的 `_discover_webui_themes()` 会自动扫描 `views/rika/themes/*/manifest.json`（跳过 `.` 或 `_` 开头目录），并校验 `entry` 与 `styles` 路径严格位于该主题目录内。
2. 主题 ID 必须匹配 `WEBUI_THEME` 校验正则 `^[a-z][a-z0-9_-]*$`（定义于 [schema.py](../link_parser/config/schema.py)）。
3. `GET /config` 通过 `webui_themes` 字段下发清单，前端打开设置页时自动列出主题并在选中时按需 `import()` 加载其 `entry` 与 CSS。

### 2.2 运行时动态注册（`window.RikaWebTheme`）

外部脚本也可通过全局 API 直接注册完整整页主题（支持内联 `css` 字符串或 `styles` URL 列表）：

```javascript
window.RikaWebTheme.registerTheme({
  id: "custom_page",
  name: "极简单页",
  subtitle: "Single-Column Editorial",
  description: "单栏长卷流式控制台",
  badge: "外部",
  css: `...`,
  mount(mountEl, ctx) { ... },
});
```

---

## 三、`manifest.json` 与 `mount(mountEl, ctx)` 契约

### 3.1 `manifest.json` 字段规范

```json
{
  "id": "editorial",
  "name": "刊物式单页后台",
  "subtitle": "Editorial Flow · 长卷流式布局",
  "description": "取消多标签切换，以双栏目录索引 + 长页面分组卡片一次性呈现全部调节能力。",
  "badge": "自定义",
  "preview": "editorial",
  "order": 30,
  "entry": "index.js",
  "styles": ["theme.css"]
}
```

| 字段 | 必填 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `id` | 建议 | 目录名 | 小写字母开头，匹配 `^[a-z][a-z0-9_-]*$` |
| `name` | 是 | `id` | 主题展示名 |
| `subtitle` | 否 | `""` | 架构一句话定位 |
| `description` | 否 | `""` | 页面设计差异与适用场景说明 |
| `badge` | 否 | `""` | 角标徽章 |
| `preview` | 否 | `""` | 可选线框提示标识 |
| `order` | 否 | `100` | 展示排序权重（内置 `studio` 为 `10`，`glass-center` 为 `20`） |
| `entry` | 否 | `"index.js"` | 相对于当前主题目录的 ES Module 入口文件 |
| `styles` | 否 | `["theme.css"]` | 相对于当前主题目录的样式文件数组（仅在当前主题激活时挂载到 `<head>`） |

### 3.2 入口模块签名与生命周期

主题入口 `index.js` 通过 `export default` 导出对象（或导出 `mount(mountEl, ctx)`）：

```javascript
export default {
  mount(mountEl, ctx) {
    // 1. 使用 ctx.dom / 原生 DOM 完全接管 mountEl 构建整套页面
    // 2. 使用 ctx.onDispose(...) 注册订阅器清理逻辑
    // 3. 返回生命周期钩子（可选）
    return {
      unmount() {
        // 清理自定义 DOM、事件与资源
      },
      onColorModeChange({ colorMode, resolvedDark, resolvedMode }) {
        // 响应用户或宿主切换 light / dark
      },
      onContextChange(nextContext) {
        // 响应 AstrBot 上下文（如 locale / isDark）更新
      },
    };
  },
};
```

> [!IMPORTANT]
> **完全样式与 DOM 隔离**：
> - `mount(mountEl, ctx)` 挂载时，主题引擎会在 `<html>` 上同步维护 `data-theme="light" | "dark"`、`data-color-mode="auto" | "light" | "dark"` 与 `data-rika-theme="<id>"`。
> - 主题的所有样式请写在自己的 `theme.css`（利用 `[data-theme="dark"]` 适配深色模式），切走主题时引擎会自动卸载之前所有的 `<link data-rika-theme-asset>` 与 `<style>` 标签并调用 `onDispose` / `unmount()`。

---

## 四、`ctx` 无头运行时 API 参考

`mount(mountEl, ctx)` 收到的第二个参数 `ctx` 提供完整、与 UI 无关的业务数据与操作接口：

### 4.1 状态仓库 `ctx.store`

| 成员 / 方法 | 说明 |
| :--- | :--- |
| `meta` / `draft` / `overview` | 后端元信息（`items` / `platforms` / `styles` / `node_schema` / `webui_themes`）、当前草稿及运行概览 |
| `scope` / `scopeLabel` / `groupProfiles` | 当前配置作用域（空串 = 全局默认；非空 = 分群作用域）与已知分群档案列表 |
| `overridableSet` / `overrideKeys` / `pendingUnset` | 允许分群覆写的 18 个键集合、当前群独立覆盖键及待恢复继承键 |
| `itemMap()` / `itemsByGroup()` | 按键或按配置组高效索引配置项元数据 |
| `isOverridable(key)` / `isKeyOverridden(key)` / `isKeyDirty(key)` / `dirtyKeys()` | 作用域权限、覆盖态与未保存脏状态判定 |
| `isPlatformEnabled(name)` / `togglePlatform(name)` / `setAllPlatformsEnabled(bool)` | 读取与修改 `DISABLED_PLATFORMS` 开关集合 |
| `setDraftValue(key, val, { rerender })` / `revertKeyToInherit(key)` / `discardDraft()` | 修改草稿、单键恢复继承全局、放弃未保存改动 |
| `saveDirty()` / `resetConfig()` / `refreshOverview(notify)` | 提交保存并热更新、重置当前作用域、刷新概览状态 |
| `switchScope(scope)` / `createGroupScope(raw, label)` / `deleteGroupScope(scope)` | 切换作用域、新建或删除分群独立配置档案 |
| `showDevKeys` / `setShowDevKeys(bool)` | 控制是否展示配置项底层常量键名 |
| `toast(msg, kind, durationMs)` | 触发非阻塞悬浮通知（`"info"` / `"ok"` / `"warn"` / `"err"`） |
| `subscribe(fn)` | 订阅状态事件（`draft`、`snapshot`、`scope`、`saving`、`overview`、`discard`、`context`、`devkeys`），返回取消订阅函数 |

### 4.2 领域异步控制器

- **`ctx.bili`**（B站账号与扫码控制器）：
  - `.getState()` 返回 `{ busyCheck, busyQr, qrSession, bili }`
  - `.refreshStatus()` / `.checkCookie()` / `.startQrLogin()` / `.cancelQrLogin()` / `.subscribe(fn)`（扫码期间自动 2.5s 轮询状态，取消或成功自动停表）
- **`ctx.preview`**（卡片与样式实时渲染控制器）：
  - `.getState()` 返回 `{ sampleId, personaName, loading, error, data, thumbsLoading, thumbs }`
  - `.fetchStyleThumbs(force)` / `.scheduleCard(delayMs)` / `.setSampleId(id)` / `.setPersonaName(name)` / `.subscribe(fn)`
- **`ctx.debug`**（链接诊断探针控制器）：
  - `.getState()` 返回 `{ url, downloadMedia, renderCard, running, error, report }`
  - `.setUrl(url)` / `.setDownloadMedia(bool)` / `.setRenderCard(bool)` / `.runProbe()` / `.downloadLog(token, logName)` / `.subscribe(fn)`
- **`ctx.cache`**（缓存清理控制器）：
  - `.getState()` 返回 `{ clearing }`；`.clearAll()` 一键清理磁盘与内存缓存。

### 4.3 节点编排数据引擎 `ctx.nodeModel`

提供与 DOM 无关的三模式节点计算能力（详见 [node_model.js](../views/rika/core/node_model.js)）：

- `NODE_ZONES`（`standalone` / `merge` / `disabled` 三去向元信息）
- `normalizeNodeRulesClient(raw, nodeSchema)` / `rulesEqual(a, b, nodeSchema)` / `serializeNodeRules(obj, nodeSchema)`
- `splitNodeBuckets(list, catalog)` / `moveNodeBetweenZones({ rawRules, nodeSchema, mode, nodeId, targetZone, targetIndex })`
- `buildOrderSummary(list, catalog)`（实时计算当前模式合并段与独立消息序列）

### 4.4 主题控制、DOM 工具与生命周期

- `ctx.themes`：`listThemes()` / `getTheme(id)` / `getActiveThemeId()` / `registerTheme(spec)`
- `ctx.setThemePreference(themeId)` / `ctx.setColorModePreference(mode)`：更新 `WEBUI_THEME`（立即触发整页热切换）或 `WEBUI_COLOR_MODE`（`"auto" | "light" | "dark"`）
- `ctx.colorMode` / `ctx.resolvedDark` / `ctx.resolvedMode` / `ctx.systemIsDark`
- `ctx.dom`：`h`、`append`、`clear`、`swapContent`、`preserveScroll`、`icon`、`formatBytes`、`valuesEqual`、`createInlineConfirmButton`
- `ctx.onDispose(cleanupFn)`：注册任意订阅器/清理回调，会在切换主题卸载当前页面时自动调用。

---

## 五、完整自定义主题示例：`views/rika/themes/editorial/`

下面演示如何从零编写一套**与工作台、指挥舱完全不同页面结构的“单栏长卷索引主题”**（只展示核心模式：左侧目录锚点 + 右侧流式分区 + 即时诊断 + 保存条）：

### 5.1 `views/rika/themes/editorial/manifest.json`

```json
{
  "id": "editorial",
  "name": "刊物单页",
  "subtitle": "Editorial Stream · 无页签长卷式控制台",
  "description": "摒弃标签页切换，以极简双栏阅读排版将状态、平台与快捷参数整合在一条长卷流中。",
  "badge": "示例",
  "order": 30,
  "entry": "index.js",
  "styles": ["theme.css"]
}
```

### 5.2 `views/rika/themes/editorial/theme.css`

```css
:root {
  --ed-bg: #faf8f4;
  --ed-paper: #ffffff;
  --ed-ink: #1c1917;
  --ed-muted: #78716c;
  --ed-accent: #0f766e;
  --ed-line: #e7e5e4;
}

[data-theme="dark"] {
  --ed-bg: #141311;
  --ed-paper: #1c1a17;
  --ed-ink: #f5f5f4;
  --ed-muted: #a8a29e;
  --ed-accent: #2dd4bf;
  --ed-line: #292524;
}

body {
  background: var(--ed-bg);
  color: var(--ed-ink);
}

.ed-shell {
  max-width: 1020px;
  margin: 0 auto;
  padding: 28px 20px 64px;
  display: grid;
  grid-template-columns: 200px minmax(0, 1fr);
  gap: 28px;
}

.ed-toc {
  position: sticky;
  top: 24px;
  align-self: start;
  border-right: 1px solid var(--ed-line);
  padding-right: 18px;
}

.ed-article {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.ed-block {
  background: var(--ed-paper);
  border: 1px solid var(--ed-line);
  padding: 22px;
}
```

### 5.3 `views/rika/themes/editorial/index.js`

```javascript
export default {
  mount(mountEl, ctx) {
    const { store, debug, themes, setThemePreference, dom, onDispose } = ctx;
    const { h, swapContent } = dom;

    const mainCol = h("div", { class: "ed-article" });
    const tocStatus = h("div");
    const root = h(
      "div",
      { class: "ed-shell" },
      h(
        "aside",
        { class: "ed-toc" },
        h("h2", null, "莉卡解析 · 刊物视图"),
        tocStatus,
      ),
      mainCol,
    );

    function render() {
      const dirty = store.dirtyKeys().length;
      const dbg = debug.getState();

      swapContent(tocStatus, [
        h("p", null, store.scope ? `分群：${store.scopeLabel}` : "全局配置"),
        dirty > 0
          ? h(
              "button",
              { type: "button", disabled: store.saving, onclick: () => store.saveDirty() },
              store.saving ? "保存中…" : `保存 ${dirty} 项`,
            )
          : h("span", null, "所有更改已同步"),
      ]);

      const probeInp = h("input", {
        type: "url",
        placeholder: "输入链接测试…",
        oninput: (e) => debug.setUrl(e.target.value),
      });
      probeInp.value = dbg.url;

      swapContent(mainCol, [
        h(
          "section",
          { class: "ed-block" },
          h("h3", null, "一、平台启停"),
          h(
            "div",
            { style: { display: "flex", flexWrap: "wrap", gap: "8px" } },
            (store.meta?.platforms || []).map((p) => {
              const on = store.isPlatformEnabled(p.name);
              return h(
                "button",
                {
                  type: "button",
                  onclick: () => {
                    store.togglePlatform(p.name);
                    render();
                  },
                },
                `${p.label || p.name}: ${on ? "开" : "关"}`,
              );
            }),
          ),
        ),
        h(
          "section",
          { class: "ed-block" },
          h("h3", null, "二、链接链路诊断"),
          probeInp,
          h(
            "button",
            { type: "button", disabled: dbg.running, onclick: () => debug.runProbe() },
            dbg.running ? "诊断中…" : "开始诊断",
          ),
          dbg.report ? h("pre", null, dbg.report.text || JSON.stringify(dbg.report.summary)) : null,
        ),
        h(
          "section",
          { class: "ed-block" },
          h("h3", null, "三、切换网页设计主题"),
          h(
            "div",
            { style: { display: "flex", gap: "8px", flexWrap: "wrap" } },
            themes.listThemes().map((t) =>
              h(
                "button",
                { type: "button", onclick: () => setThemePreference(t.id) },
                `切换到「${t.name}」`,
              ),
            ),
          ),
        ),
      ]);
    }

    onDispose(store.subscribe(() => render()));
    onDispose(debug.subscribe(() => render()));
    render();
    mountEl.appendChild(root);

    return {
      unmount() {
        root.remove();
      },
    };
  },
};
```

放好这 3 个文件后重启或重载插件页面，在原有主题的主题切换区即可看到新主题并整页热切换，**无需改任何已有文件**。

---

## 六、受限 iframe 沙箱安全红线

WebUI 运行在 AstrBot `sandbox="allow-scripts allow-forms allow-downloads"` 的受限 iframe 中，开发自定义整页主题时务必遵守：

1. **禁止拼接 HTML**：请使用 `document.createElement` / `ctx.dom.h(...)` 与 `textContent` 构建 DOM，防止 XSS 或 CSP 异常。
2. **表单赋值走属性**：给 `<input>`、`<textarea>`、`<select>` 赋初始值时必须设置 `node.value = ...`（不能用 `setAttribute("value", ...)`）。
3. **禁止浏览器阻塞弹窗**：禁止使用 `alert()` / `confirm()` / `prompt()`，破坏性操作（如清空缓存、删除分群、重置配置）请采用行内二次确认（可使用 `ctx.dom.createInlineConfirmButton`）。
4. **禁止依赖 `localStorage`**：受限沙箱没有 `allow-same-origin`，所有状态持久化请交给 `ctx.store` 或主题内部会话内存。
5. **纯离线 / 无构建运行**：直接输出浏览器原生 ES Modules 与标准 CSS，勿引用需要联网的 CDN 样式或公网字体，以便局域网环境正常渲染。
