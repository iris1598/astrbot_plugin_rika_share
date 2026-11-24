import { h, swapContent } from "../../../core/dom.js";
import { normalizeColorMode } from "../../registry.js";
import { buildControlRow } from "../widgets.js";

const COLOR_MODES = [
  { id: "auto", label: "跟随 AstrBot", hint: "主控切换暗/亮模式时自动同步" },
  { id: "light", label: "强制浅色", hint: "始终呈现明亮清晰背景" },
  { id: "dark", label: "强制深色", hint: "始终呈现沉稳护眼深色背景" },
];

const CF_BASIC_KEYS = [
  "CLOUDFLARE_FALLBACK_ENABLED",
  "CLOUDFLARE_ACCOUNT_ID",
  "CLOUDFLARE_API_TOKEN",
  "CLOUDFLARE_TIMEOUT",
  "CLOUDFLARE_CACHE_TTL",
  "CLOUDFLARE_BLACKLIST",
];

const LOG_KEYS = ["DEBUG_LOG_ENABLED", "SEND_ERROR_MESSAGES"];

function buildLayoutWireframe(theme) {
  if (theme.preview === "cockpit" || theme.id === "glass-center") {
    return h(
      "div",
      { class: "arch-wireframe arch-dock" },
      h(
        "div",
        { class: "aw-ambient" },
        h("div", { class: "aw-glass-cards" }, h("span"), h("span")),
        h("div", { class: "aw-dock-pill" }, h("i"), h("i"), h("i"), h("i")),
      ),
    );
  }
  return h(
    "div",
    { class: "arch-wireframe arch-sidebar" },
    h("div", { class: "aw-side" }, h("i"), h("i"), h("i"), h("i")),
    h("div", { class: "aw-main" }, h("span", { class: "aw-top" }), h("span", { class: "aw-body" })),
  );
}

export function createStudioSystemView(appCtx) {
  const { store, themes, setThemePreference, setColorModePreference } = appCtx;
  const root = h("div", { class: "page-stack" });
  const secrets = new Set();
  let advancedOpen = false;

  function render() {
    const map = store.itemMap();
    const showKey = Boolean(store.showDevKeys);
    const isGroup = Boolean(store.scope);
    const themeList = themes.listThemes();
    const activeThemeId = String(store.draft.WEBUI_THEME || "studio").toLowerCase();
    const colorMode = normalizeColorMode(store.draft.WEBUI_COLOR_MODE);
    const sections = [];

    const themeGridEl = h("div", { class: `layout-theme-grid ${isGroup ? "is-global-locked" : ""}` });
    const colorBarEl = h("div", { class: `colormode-bar ${isGroup ? "is-global-locked" : ""}` });

    for (const t of themeList) {
      const active =
        t.id === activeThemeId || (!themeList.some((x) => x.id === activeThemeId) && t.id === themeList[0]?.id);
      themeGridEl.appendChild(
        h(
          "button",
          {
            type: "button",
            disabled: isGroup,
            class: `layout-theme-card ${active ? "is-active" : ""}`,
            onclick: () => {
              if (!isGroup) setThemePreference(t.id);
            },
          },
          buildLayoutWireframe(t),
          h(
            "div",
            { class: "layout-theme-body" },
            h(
              "div",
              { class: "layout-theme-top" },
              h("strong", null, t.name),
              t.badge ? h("span", { class: "pill pill-neutral" }, t.badge) : null,
            ),
            h("div", { class: "layout-theme-sub" }, t.subtitle || t.id),
            h("p", { class: "layout-theme-desc" }, t.description),
          ),
        ),
      );
    }

    const colorBtns = COLOR_MODES.map((m) => {
      const btn = h(
        "button",
        {
          type: "button",
          disabled: isGroup,
          class: `colormode-opt ${colorMode === m.id ? "is-active" : ""}`,
          onclick: () => {
            if (isGroup) return;
            setColorModePreference(m.id);
            for (const b of colorBtns) b.el.classList.toggle("is-active", b.id === m.id);
          },
        },
        h("strong", null, m.label),
        h("span", null, m.hint),
      );
      colorBarEl.appendChild(btn);
      return { id: m.id, el: btn };
    });

    sections.push(
      h(
        "section",
        { class: "surface-panel" },
        h(
          "div",
          { class: "surface-head" },
          h(
            "div",
            null,
            h("h2", { class: "surface-title" }, "网页设计主题与空间架构"),
            h("p", { class: "surface-desc" }, "每套主题都是一套完整的页面 DOM 设计与独立样式；切换后会卸载旧页面并挂载新设计"),
          ),
          h(
            "div",
            { class: "btn-group" },
            isGroup ? h("span", { class: "pill" }, "网页主题仅全局生效") : null,
            h("span", { class: "pill pill-info" }, `已发现 ${themeList.length} 套页面设计`),
          ),
        ),
        themeGridEl,
        colorBarEl,
        h(
          "details",
          { class: "dev-hint-drawer" },
          h("summary", null, "编写完整自定义网页主题（views/rika/themes/<id>/）"),
          h(
            "pre",
            { class: "code-box" },
            `// 方式 1：新建 views/rika/themes/<id>/manifest.json + index.js，后端自动发现。\n` +
              `// 方式 2：运行时调用 window.RikaWebTheme.registerTheme 注册完整整页应用：\n` +
              `window.RikaWebTheme.registerTheme({\n` +
              `  id: "editorial",\n` +
              `  name: "刊物单页",\n` +
              `  css: ".ed-root { max-width: 960px; margin: 0 auto; padding: 32px; }",\n` +
              `  mount(mountEl, ctx) {\n` +
              `    // ctx 提供 store / bili / preview / debug / cache / nodeModel / onDispose\n` +
              `    const wrap = ctx.dom.h("div", { class: "ed-root" }, ctx.dom.h("h1", null, "自定义页面设计"));\n` +
              `    mountEl.appendChild(wrap);\n` +
              `    return { unmount() { wrap.remove(); } };\n` +
              `  },\n` +
              `});`,
          ),
        ),
      ),
    );

    const cfBasics = CF_BASIC_KEYS.map((k) => map.get(k)).filter(Boolean);
    const cfAdvanced = (store.meta?.items || []).filter((it) => it.tier === "advanced");
    sections.push(
      h(
        "section",
        { class: "surface-panel" },
        h(
          "div",
          { class: "surface-head" },
          h(
            "div",
            null,
            h("h2", { class: "surface-title" }, "未适配网页截图兜底（Cloudflare）"),
            h("p", { class: "surface-desc" }, "对未知网站发送 Cloudflare Browser Rendering 渲染截图；常用项外的高级参数默认收起"),
          ),
          isGroup ? h("span", { class: "pill" }, "兜底开关与黑名单可分群，账号凭据仅全局") : null,
        ),
        h(
          "div",
          { class: "settings-list two-col" },
          cfBasics.map((it) => buildControlRow(store, it, { showKey, secretState: secrets })),
        ),
        cfAdvanced.length > 0
          ? h(
              "details",
              {
                class: "advanced-fold",
                open: advancedOpen,
                ontoggle: (e) => {
                  advancedOpen = Boolean(e.target.open);
                },
              },
              h(
                "summary",
                { class: "advanced-fold-head" },
                h("span", null, `展开 Cloudflare 浏览器高级参数（${cfAdvanced.length} 项）`),
                h("span", { class: "pill pill-neutral" }, "视窗 / 等待 / Cookie / Header"),
              ),
              h(
                "div",
                { class: "settings-list two-col" },
                cfAdvanced.map((it) => buildControlRow(store, it, { showKey, secretState: secrets })),
              ),
            )
          : null,
      ),
    );

    const logItems = LOG_KEYS.map((k) => map.get(k)).filter(Boolean);
    sections.push(
      h(
        "section",
        { class: "surface-panel" },
        h(
          "div",
          { class: "surface-head" },
          h(
            "div",
            null,
            h("h2", { class: "surface-title" }, "异常日志与界面偏好"),
            h("p", { class: "surface-desc" }, "控制错误堆栈记录级别及是否在设置项旁展示底层变量键名"),
          ),
        ),
        h(
          "div",
          { class: "settings-list two-col" },
          logItems.map((it) => buildControlRow(store, it, { showKey })),
          h(
            "div",
            { class: "setting-item" },
            h(
              "div",
              { class: "setting-meta" },
              h("div", { class: "setting-label-row" }, h("span", { class: "setting-label" }, "显示底层配置键名")),
              h("p", { class: "setting-hint" }, "默认隐藏大写常量键名以保持界面简洁；排查配置时可开启"),
            ),
            h(
              "div",
              { class: "setting-ctrl" },
              h(
                "label",
                { class: "switch" },
                h("input", {
                  type: "checkbox",
                  checked: showKey,
                  onchange: (e) => store.setShowDevKeys(Boolean(e.target.checked)),
                }),
                h("span", { class: "switch-track" }),
                h("span", { class: "switch-text" }, showKey ? "显示键名" : "简洁模式"),
              ),
            ),
          ),
        ),
      ),
    );
    swapContent(root, sections);
  }

  render();
  return { element: root, sync: render };
}
