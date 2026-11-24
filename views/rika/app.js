import {
  clear,
  createInlineConfirmButton,
  createToaster,
  h,
  icon,
  preserveScroll,
  swapContent,
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
  { id: "studio", label: "卡片工作室", icon: "studio", desc: "样式、节点编排、署名与实时预览" },
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
      bridge.apiGet("config", { scope: "" }),
      bridge.apiGet("overview", { scope: "" }).catch(() => null),
    ]);

    const tabButtons = new Map();
    const viewHosts = new Map();
    const themePills = [];
    let activeTitleEl = null;
    let activeDescEl = null;
    let saveStripEl = null;
    let scopeBarEl = null;
    let addingGroup = false;
    let newGroupInput = "";
    let newGroupLabel = "";
    let scopeBusy = false;
    let saving = false;

    const store = {
      bridge,
      toast,
      context: ctx || {},
      systemIsDark: Boolean(ctx?.isDark),
      meta: configPayload,
      scope: String(configPayload.scope || ""),
      scopeLabel: String(configPayload.scope_label || "全局默认"),
      globalValues: cloneValues(configPayload.global_values || configPayload.values),
      overrideKeys: new Set(configPayload.override_keys || []),
      overridableSet: new Set(configPayload.group_overridable_keys || []),
      pendingUnset: new Set(),
      groupProfiles: Array.isArray(configPayload.group_profiles) ? configPayload.group_profiles : [],
      draft: cloneValues(configPayload.values),
      overview: overviewPayload,
      activeTab: "workbench",
      showDevKeys: false,
      views: {},

      isOverridable(key) {
        return store.overridableSet.has(key);
      },

      dirtyKeys() {
        const saved = store.meta?.values || {};
        const changed = [];
        for (const item of store.meta?.items || []) {
          const k = item.key;
          if (store.scope && !store.overridableSet.has(k)) continue;
          if (store.pendingUnset.has(k) || !valuesEqual(store.draft[k], saved[k])) {
            changed.push(k);
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

      applyConfigSnapshot(res, { syncTheme = true } = {}) {
        if (!res) return;
        if (res.scope !== undefined) {
          store.scope = String(res.scope || "");
        }
        store.scopeLabel = String(res.scope_label || (store.scope ? store.scope : "全局默认"));
        if (res.values) {
          store.meta.values = res.values;
          store.draft = cloneValues(res.values);
        }
        if (res.global_values) {
          store.globalValues = cloneValues(res.global_values);
        } else if (!store.scope && res.values) {
          store.globalValues = cloneValues(res.values);
        }
        if (Array.isArray(res.override_keys)) {
          store.overrideKeys = new Set(res.override_keys);
        } else if (!store.scope) {
          store.overrideKeys = new Set();
        }
        store.pendingUnset.clear();
        if (Array.isArray(res.group_overridable_keys)) {
          store.overridableSet = new Set(res.group_overridable_keys);
        }
        if (Array.isArray(res.group_profiles)) {
          store.groupProfiles = res.group_profiles;
        }
        if (res.node_schema) {
          store.meta.node_schema = res.node_schema;
        }
        if (Array.isArray(store.meta.platforms)) {
          const disabledSet = new Set(
            String(store.meta.values?.DISABLED_PLATFORMS || "")
              .split(",")
              .map((s) => s.trim().toLowerCase())
              .filter(Boolean),
          );
          store.meta.platforms = store.meta.platforms.map((p) => ({
            ...p,
            enabled: !disabledSet.has(p.name.toLowerCase()),
          }));
        }
        if (syncTheme) {
          store.applyCurrentTheme();
        }
      },

      setDraftValue(key, val, { rerender = true } = {}) {
        if (store.scope && !store.overridableSet.has(key)) {
          toast("该配置项仅全局生效，请切回「全局默认」修改", "warn");
          return;
        }
        store.pendingUnset.delete(key);
        store.draft[key] = val;
        if (key === "WEBUI_THEME" || key === "WEBUI_COLOR_MODE") {
          store.applyCurrentTheme();
        }
        // 就地更新行脏状态，不摧毁正在输入的 DOM 节点
        const savedVal = store.meta?.values?.[key];
        const isDirty = store.pendingUnset.has(key) || !valuesEqual(val, savedVal);
        if (typeof document.querySelectorAll === "function") {
          for (const row of document.querySelectorAll(`.setting-item[data-key="${key}"]`)) {
            row.classList.toggle("is-dirty", isDirty);
          }
        }
        renderSaveStrip();
        if (rerender && (key === "RENDER_PERSONA_WATERMARK" || key === "NODE_RULES")) {
          store.views.workbench?.sync?.();
        }
      },

      revertKeyToInherit(key) {
        if (!store.scope || !store.overridableSet.has(key)) return;
        const gVal = store.globalValues?.[key];
        store.draft[key] = Array.isArray(gVal) ? [...gVal] : gVal;
        if (store.overrideKeys.has(key)) {
          store.pendingUnset.add(key);
        } else {
          store.pendingUnset.delete(key);
        }
        renderSaveStrip();
        syncAllViews();
        store.views.studio?.refreshPreview?.();
      },

      async switchScope(nextScope) {
        const target = String(nextScope || "").trim();
        if (target === store.scope) {
          renderScopeBar();
          return;
        }
        if (store.dirtyKeys().length > 0) {
          toast("当前作用域有未保存改动，请先保存或点击放弃后再切换", "warn");
          renderScopeBar();
          return;
        }
        scopeBusy = true;
        renderScopeBar();
        try {
          const [cfgRes, ovRes] = await Promise.all([
            bridge.apiGet("config", { scope: target }),
            bridge.apiGet("overview", { scope: target }).catch(() => null),
          ]);
          if (cfgRes) {
            store.applyConfigSnapshot(cfgRes);
          }
          if (ovRes) {
            store.overview = ovRes;
          }
          renderSaveStrip();
          syncAllViews();
          store.views.studio?.refreshPreview?.();
          toast(`已切换配置作用域：${store.scopeLabel}`, "info");
        } catch (err) {
          toast(`切换作用域失败：${err.message || err}`, "err");
        } finally {
          scopeBusy = false;
          renderScopeBar();
        }
      },

      async createGroupScope(rawScope, label) {
        const trimmed = String(rawScope || "").trim();
        if (!trimmed) {
          toast("请输入群号（如 123456）或 UMO 标识", "warn");
          return false;
        }
        if (store.dirtyKeys().length > 0) {
          toast("当前作用域有未保存改动，请先保存或点击放弃", "warn");
          return false;
        }
        scopeBusy = true;
        renderScopeBar();
        try {
          const res = await bridge.apiPost("groups", {
            action: "create",
            scope: trimmed,
            label: String(label || "").trim(),
          });
          if (res?.errors?.length) {
            toast(res.errors[0], "err");
            return false;
          }
          if (Array.isArray(res?.groups)) {
            store.groupProfiles = res.groups;
          }
          addingGroup = false;
          newGroupInput = "";
          newGroupLabel = "";
          scopeBusy = false;
          await store.switchScope(res.scope || trimmed);
          return true;
        } catch (err) {
          toast(`添加分群失败：${err.message || err}`, "err");
          return false;
        } finally {
          scopeBusy = false;
          renderScopeBar();
        }
      },

      async deleteGroupScope(targetScope) {
        const target = String(targetScope || "").trim();
        if (!target) return;
        scopeBusy = true;
        renderScopeBar();
        try {
          const res = await bridge.apiPost("groups", { action: "delete", scope: target });
          if (res?.errors?.length) {
            toast(res.errors[0], "err");
            return;
          }
          if (Array.isArray(res?.groups)) {
            store.groupProfiles = res.groups;
          }
          if (target === store.scope) {
            store.pendingUnset.clear();
            store.draft = cloneValues(store.meta.values);
            scopeBusy = false;
            await store.switchScope("");
          } else {
            toast("已移除该分群档案", "ok");
          }
        } catch (err) {
          toast(`移除分群档案失败：${err.message || err}`, "err");
        } finally {
          scopeBusy = false;
          renderScopeBar();
        }
      },

      async refreshOverview(notify = false) {
        try {
          store.overview = await bridge.apiGet("overview", { scope: store.scope });
          store.views.workbench?.sync?.();
          if (notify) toast("运行状态已刷新", "ok");
        } catch (err) {
          if (notify) toast(`刷新失败：${err.message || err}`, "err");
        }
      },

      discardDraft() {
        store.pendingUnset.clear();
        store.draft = cloneValues(store.meta.values);
        store.applyCurrentTheme();
        syncAllViews();
        renderSaveStrip();
        renderScopeBar();
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
          const unset = [];
          for (const k of changed) {
            if (store.scope && store.pendingUnset.has(k)) {
              unset.push(k);
            } else {
              payload[k] = store.draft[k];
            }
          }
          const res = await bridge.apiPost("config", {
            scope: store.scope,
            values: payload,
            ...(unset.length ? { unset } : {}),
          });
          if (res?.values) {
            store.applyConfigSnapshot(res);
          }
          syncAllViews();
          renderScopeBar();
          store.refreshOverview(false);
          const errs = res?.errors || [];
          if (errs.length > 0) {
            toast(`保存提醒：${errs[0]}`, "warn", 4800);
          } else if (store.scope) {
            toast(`已更新「${store.scopeLabel}」分群设置并热生效`, "ok");
          } else {
            toast(`已保存 ${res?.changed?.length ?? changed.length} 项全局设置并热更新`, "ok");
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
          const res = await bridge.apiPost("config/reset", { scope: store.scope });
          if (res?.values) {
            store.applyConfigSnapshot(res);
          }
          syncAllViews();
          renderScopeBar();
          store.refreshOverview(false);
          store.views.studio?.refreshPreview?.();
          toast(store.scope ? "已清空本群独立覆写并恢复继承全局" : "已恢复全部默认设置", "ok");
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
      preserveScroll(() => {
        for (const view of Object.values(store.views)) {
          view?.sync?.();
        }
      });
    }

    function renderSaveStrip() {
      if (!saveStripEl) return;
      const changed = store.dirtyKeys();
      saveStripEl.classList.toggle("has-dirty", changed.length > 0);
      const nodes = [];

      if (changed.length > 0) {
        nodes.push(
          h(
            "div",
            { class: "save-info" },
            h("span", { class: "dirty-dot" }),
            h("strong", null, `${changed.length} 项待保存`),
          ),
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

      nodes.push(
        createInlineConfirmButton({
          label: store.scope ? "清空覆写" : "恢复默认",
          confirmLabel: store.scope ? "确认清空" : "确认重置",
          variant: "ghost",
          size: "sm",
          onConfirm: () => store.resetConfig(),
        }),
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
      swapContent(saveStripEl, nodes);
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
    scopeBarEl = h("section", { class: "scope-bar", "aria-label": "分群配置作用域" });

    function renderScopeBar() {
      if (!scopeBarEl) return;

      const profiles = Array.isArray(store.groupProfiles) ? store.groupProfiles : [];
      const overridden = profiles.filter((p) => p.has_override);
      const known = profiles.filter((p) => !p.has_override);
      const inProfiles = profiles.some((p) => p.scope_id === store.scope);

      const selectEl = h(
        "select",
        {
          class: "ctrl-input ctrl-sm scope-select",
          disabled: scopeBusy || saving,
          onchange: (e) => store.switchScope(e.target.value),
        },
        h("option", { value: "" }, "全局默认（所有未单独配置的群）"),
        overridden.length > 0
          ? h(
              "optgroup",
              { label: "已独立配置的分群" },
              overridden.map((p) =>
                h(
                  "option",
                  { value: p.scope_id },
                  `${p.display_name || p.scope_id}（独立 ${p.override_count || 0} 项 · ${p.scope_id}）`,
                ),
              ),
            )
          : null,
        known.length > 0
          ? h(
              "optgroup",
              { label: "已知 / 活跃群聊" },
              known.map((p) =>
                h(
                  "option",
                  { value: p.scope_id },
                  `${p.display_name || p.scope_id}（${p.scope_id}）`,
                ),
              ),
            )
          : null,
        store.scope && !inProfiles
          ? h("option", { value: store.scope }, `${store.scopeLabel}（${store.scope}）`)
          : null,
      );
      selectEl.value = store.scope;

      const statusBadge = store.scope
        ? h(
            "span",
            { class: `pill ${store.overrideKeys.size > 0 ? "pill-info" : ""}` },
            store.overrideKeys.size > 0
              ? `本群独立 ${store.overrideKeys.size} 项`
              : "继承全局（尚未单独覆盖）",
          )
        : h(
            "span",
            { class: `pill ${overridden.length > 0 ? "pill-info" : ""}` },
            overridden.length > 0 ? `已单独配置 ${overridden.length} 个分群` : "全局生效",
          );

      scopeBarEl.classList.toggle("is-group-scope", Boolean(store.scope));
      const nodes = [
        h(
          "div",
          { class: "scope-bar-row" },
          h(
            "div",
            { class: "scope-bar-left" },
            h("span", { class: "scope-label" }, "作用域"),
            selectEl,
            statusBadge,
            store.scope
              ? h(
                  "span",
                  { class: "scope-tip" },
                  "仅分群可覆写零重解析代价项，账号凭据/清晰度/代理/布局主题锁定为全局",
                )
              : null,
          ),
          h(
            "div",
            { class: "scope-bar-actions" },
            store.scope
              ? h(
                  "button",
                  {
                    type: "button",
                    class: "btn btn-ghost btn-sm",
                    disabled: scopeBusy,
                    onclick: () => store.switchScope(""),
                  },
                  "返回全局",
                )
              : null,
            h(
              "button",
              {
                type: "button",
                class: "btn btn-soft btn-sm",
                disabled: scopeBusy,
                onclick: () => {
                  addingGroup = !addingGroup;
                  renderScopeBar();
                },
              },
              addingGroup ? "收起添加" : "+ 添加分群",
            ),
            store.scope
              ? createInlineConfirmButton({
                  label: "移除档案",
                  confirmLabel: "确认移除",
                  variant: "ghost",
                  size: "sm",
                  onConfirm: () => store.deleteGroupScope(store.scope),
                })
              : null,
          ),
        ),
      ];

      if (addingGroup) {
        const idInp = h("input", {
          type: "text",
          class: "ctrl-input ctrl-sm mono scope-add-id",
          placeholder: "群号（如 123456）或 UMO（如 napcat:GroupMessage:123456）",
          oninput: (e) => {
            newGroupInput = e.target.value;
          },
          onkeydown: (e) => {
            if (e.key === "Enter" && !scopeBusy) {
              store.createGroupScope(newGroupInput, newGroupLabel);
            }
          },
        });
        idInp.value = newGroupInput;
        const labelInp = h("input", {
          type: "text",
          class: "ctrl-input ctrl-sm scope-add-label",
          placeholder: "群备注名称（可选，如 测试群）",
          oninput: (e) => {
            newGroupLabel = e.target.value;
          },
          onkeydown: (e) => {
            if (e.key === "Enter" && !scopeBusy) {
              store.createGroupScope(newGroupInput, newGroupLabel);
            }
          },
        });
        labelInp.value = newGroupLabel;

        nodes.push(
          h(
            "div",
            { class: "scope-add-form" },
            idInp,
            labelInp,
            h(
              "button",
              {
                type: "button",
                class: "btn btn-primary btn-sm",
                disabled: scopeBusy,
                onclick: () => store.createGroupScope(newGroupInput, newGroupLabel),
              },
              scopeBusy ? "创建中…" : "创建并切换",
            ),
            h(
              "button",
              {
                type: "button",
                class: "btn btn-ghost btn-sm",
                disabled: scopeBusy,
                onclick: () => {
                  addingGroup = false;
                  renderScopeBar();
                },
              },
              "取消",
            ),
          ),
        );
      }
      swapContent(scopeBarEl, nodes);
    }

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
      h("div", { class: "shell-content" }, topHeader, scopeBarEl, mainStage),
    );

    store.applyCurrentTheme();
    renderScopeBar();
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
