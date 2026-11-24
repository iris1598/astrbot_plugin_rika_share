import { createInlineConfirmButton, h, icon, preserveScroll, swapContent } from "../../core/dom.js";
import { subscribeThemes } from "../registry.js";
import { createStudioCardView } from "./views/card_studio.js";
import { createStudioPlatformsView } from "./views/platforms.js";
import { createStudioSystemView } from "./views/system.js";
import { createStudioWorkbenchView } from "./views/workbench.js";

const TABS = [
  { id: "workbench", label: "总览与诊断", icon: "dashboard", desc: "状态监控与链接测试" },
  { id: "platforms", label: "平台与账号", icon: "platforms", desc: "开关矩阵、凭据与代理" },
  { id: "studio", label: "卡片工作室", icon: "studio", desc: "样式、节点编排、署名与实时预览" },
  { id: "system", label: "主题与兜底", icon: "sliders", desc: "整页主题切换与 Cloudflare 兜底" },
];

export default {
  id: "studio",
  name: "工作台分栏",
  subtitle: "Studio Workbench · 多标签工程控制台",
  description:
    "经典桌面工具流设计：左侧固定导航栏 + 独立全局/分群作用域横栏 + 四页签结构化配置表，信息密度高、条理分明，适合精密调参。",
  badge: "默认",
  preview: "studio",
  order: 10,
  styles: ["themes/studio/theme.css"],

  mount(mountEl, appCtx) {
    const { store, bili, preview, debug, cache, onDispose } = appCtx;

    let activeTab = "workbench";
    let addingGroup = false;
    let newGroupInput = "";
    let newGroupLabel = "";

    const tabButtons = new Map();
    const viewHosts = new Map();
    const activeTitleEl = h("h1", { class: "stage-title" }, TABS[0].label);
    const activeDescEl = h("p", { class: "stage-sub" }, TABS[0].desc);
    const saveStripEl = h("div", { class: "save-strip" });
    const scopeBarEl = h("section", { class: "scope-bar", "aria-label": "分群配置作用域" });
    const sidebarThemePill = h(
      "button",
      {
        type: "button",
        class: "theme-badge-btn",
        onclick: () => switchTab("system"),
      },
      appCtx.theme.name,
    );

    const views = {
      workbench: createStudioWorkbenchView(appCtx, { navigate: switchTab }),
      platforms: createStudioPlatformsView(appCtx),
      studio: createStudioCardView(appCtx),
      system: createStudioSystemView(appCtx),
    };

    function syncAllViews() {
      preserveScroll(() => {
        for (const v of Object.values(views)) {
          v?.sync?.();
        }
      });
    }

    function renderSaveStrip() {
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
              disabled: store.saving,
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
            disabled: store.saving || changed.length === 0,
            onclick: () => store.saveDirty(),
          },
          store.saving ? "保存中…" : changed.length > 0 ? "保存并生效" : "已同步",
        ),
      );
      swapContent(saveStripEl, nodes);
    }

    function renderScopeBar() {
      const profiles = Array.isArray(store.groupProfiles) ? store.groupProfiles : [];
      const overridden = profiles.filter((p) => p.has_override);
      const known = profiles.filter((p) => !p.has_override);
      const inProfiles = profiles.some((p) => p.scope_id === store.scope);

      const selectEl = h(
        "select",
        {
          class: "ctrl-input ctrl-sm scope-select",
          disabled: store.scopeBusy || store.saving,
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
                  "仅分群可覆写零重解析代价项，账号凭据/清晰度/代理/网页主题锁定为全局",
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
                    disabled: store.scopeBusy,
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
                disabled: store.scopeBusy,
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
        const submitNewGroup = async () => {
          const ok = await store.createGroupScope(newGroupInput, newGroupLabel);
          if (ok) {
            addingGroup = false;
            newGroupInput = "";
            newGroupLabel = "";
            renderScopeBar();
          }
        };
        const idInp = h("input", {
          type: "text",
          class: "ctrl-input ctrl-sm mono scope-add-id",
          placeholder: "群号（如 123456）或 UMO（如 napcat:GroupMessage:123456）",
          oninput: (e) => {
            newGroupInput = e.target.value;
          },
          onkeydown: (e) => {
            if (e.key === "Enter" && !store.scopeBusy) submitNewGroup();
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
            if (e.key === "Enter" && !store.scopeBusy) submitNewGroup();
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
                disabled: store.scopeBusy,
                onclick: submitNewGroup,
              },
              store.scopeBusy ? "创建中…" : "创建并切换",
            ),
            h(
              "button",
              {
                type: "button",
                class: "btn btn-ghost btn-sm",
                disabled: store.scopeBusy,
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

    function switchTab(tabId) {
      if (!viewHosts.has(tabId)) return;
      activeTab = tabId;
      const tabDef = TABS.find((t) => t.id === tabId) || TABS[0];
      activeTitleEl.textContent = tabDef.label;
      activeDescEl.textContent = tabDef.desc;
      for (const [id, holder] of viewHosts.entries()) {
        holder.classList.toggle("is-hidden", id !== tabId);
      }
      for (const [id, btn] of tabButtons.entries()) {
        btn.classList.toggle("is-active", id === tabId);
      }
      views[tabId]?.onActivated?.();
      views[tabId]?.sync?.();
    }

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
          h("span", null, store.meta?.version || "v3.5.0"),
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
              class: `nav-btn ${t.id === activeTab ? "is-active" : ""}`,
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
        h("span", { class: "nav-foot-label" }, "当前页面主题"),
        sidebarThemePill,
      ),
    );

    const topHeader = h(
      "header",
      { class: "stage-header" },
      h(
        "div",
        { class: "stage-heading" },
        h("div", null, activeTitleEl, activeDescEl),
      ),
      h("div", { class: "stage-actions" }, saveStripEl),
    );

    const mainStage = h("main", { class: "stage-body" });
    for (const t of TABS) {
      const holder = h(
        "div",
        { class: `tab-panel ${t.id === activeTab ? "" : "is-hidden"}` },
        views[t.id].element,
      );
      viewHosts.set(t.id, holder);
      mainStage.appendChild(holder);
    }

    const shell = h(
      "div",
      { class: "app-shell" },
      sidebar,
      h("div", { class: "shell-content" }, topHeader, scopeBarEl, mainStage),
    );

    renderScopeBar();
    renderSaveStrip();
    mountEl.appendChild(shell);

    onDispose(
      store.subscribe((ev) => {
        if (ev.type === "draft") {
          for (const row of mountEl.querySelectorAll(`.setting-item[data-key="${ev.key}"]`)) {
            row.classList.toggle("is-dirty", store.isKeyDirty(ev.key));
          }
          renderSaveStrip();
          if (ev.reverted) {
            syncAllViews();
            preview.scheduleCard(0);
          } else if (ev.rerender && (ev.key === "RENDER_PERSONA_WATERMARK" || ev.key === "NODE_RULES")) {
            views.workbench?.sync?.();
          }
        } else if (ev.type === "snapshot" || ev.type === "discard") {
          renderSaveStrip();
          renderScopeBar();
          syncAllViews();
          if (activeTab === "studio") preview.scheduleCard(0);
        } else if (ev.type === "scope" || ev.type === "saving") {
          renderScopeBar();
          renderSaveStrip();
        } else if (ev.type === "overview" || ev.type === "devkeys") {
          syncAllViews();
        }
      }),
    );

    onDispose(
      bili.subscribe(() => {
        views.workbench?.sync?.();
        views.platforms?.syncBiliBox?.();
      }),
    );
    onDispose(
      preview.subscribe(() => {
        views.studio?.syncStyleGrid?.();
        views.studio?.updatePreviewStage?.();
      }),
    );
    onDispose(debug.subscribe(() => views.workbench?.sync?.()));
    onDispose(cache.subscribe(() => views.workbench?.sync?.()));
    onDispose(subscribeThemes(() => views.system?.sync?.()));

    return {
      unmount() {
        bili.stopPolling();
        shell.remove();
      },
    };
  },
};
