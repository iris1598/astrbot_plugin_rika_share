import {
  clear,
  createInlineConfirmButton,
  createToaster,
  h,
  icon,
  valuesEqual,
} from "./ui.js";
import { applyTheme, getTheme } from "./themes/index.js";
import { createWorkbenchView } from "./views/workbench.js";
import { createPlatformsView } from "./views/platforms.js";
import { createCardStudioView } from "./views/card_studio.js";
import { createSystemView } from "./views/system.js";

const TABS = [
  { id: "workbench", label: "总览与诊断", icon: "dashboard", desc: "状态监控与链接测试" },
  { id: "platforms", label: "平台与账号", icon: "platforms", desc: "开关矩阵、凭据与代理" },
  { id: "studio", label: "卡片工作室", icon: "studio", desc: "样式、人格署名与实时预览" },
  { id: "system", label: "主题与兜底", icon: "sliders", desc: "布局主题与 Cloudflare 兜底" },
];

function cloneValues(values) {
  const out = {};
  for (const [k, v] of Object.entries(values || {})) {
    out[k] = Array.isArray(v) ? [...v] : v;
  }
  return out;
}

function resolveBridge() {
  const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
  if (!bridge) {
    throw new Error("未检测到 window.AstrBotPluginView，请在 AstrBot 控制台中打开插件页面");
  }
  return bridge;
}

async function boot() {
  const mount = document.getElementById("app");
  const toast = createToaster();

  try {
    const bridge = resolveBridge();
    const ctx = await bridge.ready();

    const [configPayload, overviewPayload] = await Promise.all([
      bridge.apiGet("config"),
      bridge.apiGet("overview").catch(() => null),
    ]);

    const tabButtons = new Map();
    const viewHosts = new Map();
    const themePills = [];
    let activeTitleEl = null;
    let activeDescEl = null;
    let saveStripEl = null;
    let saving = false;

    const store = {
      bridge,
      toast,
      context: ctx || {},
      systemIsDark: Boolean(ctx?.isDark),
      meta: configPayload,
      draft: cloneValues(configPayload.values),
      overview: overviewPayload,
      activeTab: "workbench",
      showDevKeys: false,
      views: {},

      dirtyKeys() {
        const saved = store.meta?.values || {};
        const changed = [];
        for (const item of store.meta?.items || []) {
          if (!valuesEqual(store.draft[item.key], saved[item.key])) {
            changed.push(item.key);
          }
        }
        return changed;
      },

      setShowDevKeys(enabled) {
        store.showDevKeys = Boolean(enabled);
        syncAllViews();
      },

      applyCurrentTheme() {
        const applied = applyTheme(store.draft.WEBUI_THEME, {
          systemIsDark: store.systemIsDark,
          colorMode: store.draft.WEBUI_COLOR_MODE,
        });
        const label = applied.theme ? applied.theme.name : store.draft.WEBUI_THEME;
        for (const pill of themePills) {
          pill.textContent = label;
        }
      },

      setDraftValue(key, val, { rerender = true } = {}) {
        store.draft[key] = val;
        if (key === "WEBUI_THEME" || key === "WEBUI_COLOR_MODE") {
          store.applyCurrentTheme();
        }
        // 就地更新行脏状态，不摧毁正在输入的 DOM 节点
        const savedVal = store.meta?.values?.[key];
        const isDirty = !valuesEqual(val, savedVal);
        if (typeof document.querySelectorAll === "function") {
          for (const row of document.querySelectorAll(`.setting-item[data-key="${key}"]`)) {
            row.classList.toggle("is-dirty", isDirty);
          }
        }
        renderSaveStrip();
        if (rerender && key === "RENDER_PERSONA_WATERMARK") {
          store.views.workbench?.sync?.();
        }
      },

      async refreshOverview(notify = false) {
        try {
          store.overview = await bridge.apiGet("overview");
          store.views.workbench?.sync?.();
          if (notify) toast("运行状态已刷新", "ok");
        } catch (err) {
          if (notify) toast(`刷新失败：${err.message || err}`, "err");
        }
      },

      discardDraft() {
        store.draft = cloneValues(store.meta.values);
        store.applyCurrentTheme();
        syncAllViews();
        renderSaveStrip();
        store.views.studio?.refreshPreview?.();
        toast("已放弃未保存改动", "info");
      },

      async saveDirty() {
        const changed = store.dirtyKeys();
        if (changed.length === 0 || saving) return;
        saving = true;
        renderSaveStrip();
        try {
          const payload = {};
          for (const k of changed) payload[k] = store.draft[k];
          const res = await bridge.apiPost("config", { values: payload });
          if (res?.values) {
            store.meta.values = res.values;
            store.draft = cloneValues(res.values);
            if (Array.isArray(store.meta.platforms)) {
              const disabledSet = new Set(
                String(res.values.DISABLED_PLATFORMS || "")
                  .split(",")
                  .map((s) => s.trim().toLowerCase())
                  .filter(Boolean),
              );
              store.meta.platforms = store.meta.platforms.map((p) => ({
                ...p,
                enabled: !disabledSet.has(p.name.toLowerCase()),
              }));
            }
          }
          store.applyCurrentTheme();
          syncAllViews();
          store.refreshOverview(false);
          const errs = res?.errors || [];
          if (errs.length > 0) {
            toast(`保存提醒：${errs[0]}`, "warn", 4800);
          } else {
            toast(`已保存 ${res?.changed?.length ?? changed.length} 项设置并热更新`, "ok");
          }
        } catch (err) {
          toast(`保存失败：${err.message || err}`, "err");
        } finally {
          saving = false;
          renderSaveStrip();
        }
      },

      async resetConfig() {
        saving = true;
        renderSaveStrip();
        try {
          const res = await bridge.apiPost("config/reset", {});
          if (res?.values) {
            store.meta.values = res.values;
            store.draft = cloneValues(res.values);
          }
          store.applyCurrentTheme();
          syncAllViews();
          store.refreshOverview(false);
          store.views.studio?.refreshPreview?.();
          toast("已恢复全部默认设置", "ok");
        } catch (err) {
          toast(`恢复默认失败：${err.message || err}`, "err");
        } finally {
          saving = false;
          renderSaveStrip();
        }
      },

      navigate(tabId) {
        switchTab(tabId);
      },
    };

    store.applyCurrentTheme();

    if (typeof bridge.onContext === "function") {
      bridge.onContext((nextCtx) => {
        store.context = nextCtx || {};
        store.systemIsDark = Boolean(nextCtx?.isDark);
        store.applyCurrentTheme();
      });
    }

    function syncAllViews() {
      for (const view of Object.values(store.views)) {
        view?.sync?.();
      }
    }

    function renderSaveStrip() {
      if (!saveStripEl) return;
      clear(saveStripEl);
      const changed = store.dirtyKeys();
      saveStripEl.classList.toggle("has-dirty", changed.length > 0);

      if (changed.length > 0) {
        saveStripEl.appendChild(
          h(
            "div",
            { class: "save-info" },
            h("span", { class: "dirty-dot" }),
            h("strong", null, `${changed.length} 项待保存`),
          ),
        );
        saveStripEl.appendChild(
          h(
            "button",
            {
              type: "button",
              class: "btn btn-ghost btn-sm",
              disabled: saving,
              onclick: () => store.discardDraft(),
            },
            "放弃",
          ),
        );
      }

      saveStripEl.appendChild(
        createInlineConfirmButton({
          label: "恢复默认",
          confirmLabel: "确认重置",
          variant: "ghost",
          size: "sm",
          onConfirm: () => store.resetConfig(),
        }),
      );

      saveStripEl.appendChild(
        h(
          "button",
          {
            type: "button",
            class: "btn btn-primary btn-sm",
            disabled: saving || changed.length === 0,
            onclick: () => store.saveDirty(),
          },
          saving ? "保存中…" : changed.length > 0 ? "保存并生效" : "已同步",
        ),
      );
    }

    const sidebarThemePill = h("button", {
      type: "button",
      class: "theme-badge-btn",
      onclick: () => switchTab("system"),
    });
    const topbarThemePill = h("button", {
      type: "button",
      class: "theme-badge-btn topbar-theme-btn",
      onclick: () => switchTab("system"),
    });
    themePills.push(sidebarThemePill, topbarThemePill);

    const sidebar = h(
      "aside",
      { class: "shell-nav" },
      h(
        "div",
        { class: "nav-brand" },
        h("span", { class: "brand-badge" }, icon("logo", 20)),
        h(
          "div",
          { class: "brand-text" },
          h("strong", null, "莉卡解析"),
          h("span", null, configPayload.version || "v3.5.0"),
        ),
      ),
      h(
        "nav",
        { class: "nav-menu", role: "tablist" },
        TABS.map((t) => {
          const btn = h(
            "button",
            {
              type: "button",
              role: "tab",
              class: `nav-btn ${t.id === store.activeTab ? "is-active" : ""}`,
              onclick: () => switchTab(t.id),
            },
            h("span", { class: "nav-ico" }, icon(t.icon, 18)),
            h("span", { class: "nav-label" }, t.label),
          );
          tabButtons.set(t.id, btn);
          return btn;
        }),
      ),
      h(
        "div",
        { class: "nav-foot" },
        h("span", { class: "nav-foot-label" }, "当前布局主题"),
        sidebarThemePill,
      ),
    );

    activeTitleEl = h("h1", { class: "stage-title" }, TABS[0].label);
    activeDescEl = h("p", { class: "stage-sub" }, TABS[0].desc);
    saveStripEl = h("div", { class: "save-strip" });

    const topHeader = h(
      "header",
      { class: "stage-header" },
      h(
        "div",
        { class: "stage-heading" },
        h(
          "div",
          { class: "dock-brand-mini" },
          h("span", { class: "brand-badge sm" }, icon("logo", 16)),
        ),
        h("div", null, activeTitleEl, activeDescEl),
      ),
      h("div", { class: "stage-actions" }, topbarThemePill, saveStripEl),
    );

    store.views = {
      workbench: createWorkbenchView(store),
      platforms: createPlatformsView(store),
      studio: createCardStudioView(store),
      system: createSystemView(store),
    };

    const mainStage = h("main", { class: "stage-body" });
    for (const t of TABS) {
      const holder = h(
        "div",
        { class: `tab-panel ${t.id === store.activeTab ? "" : "is-hidden"}` },
        store.views[t.id].element,
      );
      viewHosts.set(t.id, holder);
      mainStage.appendChild(holder);
    }

    function switchTab(tabId) {
      if (!viewHosts.has(tabId)) return;
      store.activeTab = tabId;
      const tabDef = TABS.find((t) => t.id === tabId) || TABS[0];
      activeTitleEl.textContent = tabDef.label;
      activeDescEl.textContent = tabDef.desc;
      for (const [id, holder] of viewHosts.entries()) {
        holder.classList.toggle("is-hidden", id !== tabId);
      }
      for (const [id, btn] of tabButtons.entries()) {
        btn.classList.toggle("is-active", id === tabId);
      }
      store.views[tabId]?.onActivated?.();
      store.views[tabId]?.sync?.();
    }

    const shell = h(
      "div",
      { class: "app-shell" },
      sidebar,
      h("div", { class: "shell-content" }, topHeader, mainStage),
    );

    store.applyCurrentTheme();
    renderSaveStrip();
    clear(mount);
    mount.appendChild(shell);
  } catch (err) {
    clear(mount);
    mount.appendChild(
      h(
        "div",
        { class: "fatal-panel" },
        h("h2", null, "控制中心启动失败"),
        h("p", null, err?.message || String(err)),
        h(
          "button",
          {
            type: "button",
            class: "btn btn-primary",
            onclick: () => window.location.reload(),
          },
          "刷新页面",
        ),
      ),
    );
  }
}

boot();
