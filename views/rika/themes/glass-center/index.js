import { clear, createInlineConfirmButton, formatBytes, h, icon, preserveScroll, swapContent } from "../../core/dom.js";
import {
  NODE_ZONES,
  buildOrderSummary,
  cloneNodeRules,
  moveNodeBetweenZones,
  normalizeNodeRulesClient,
  rulesEqual,
  serializeNodeRules,
  splitNodeBuckets,
  zoneOfEntry,
} from "../../core/node_model.js";
import { normalizeColorMode, subscribeThemes } from "../registry.js";

const WORKSPACES = [
  { id: "cockpit", label: "驾驶舱总览", icon: "dashboard" },
  { id: "canvas", label: "气泡创作台", icon: "studio" },
  { id: "console", label: "全域控制台", icon: "sliders" },
];

const QUICK_URLS = [
  { label: "B站视频", url: "https://www.bilibili.com/video/BV1GJ411x7h7" },
  { label: "GitHub 仓库", url: "https://github.com/AstrBotDevs/AstrBot" },
];

const STEP_TONES = {
  ok: { label: "通过", tone: "ok" },
  pass: { label: "通过", tone: "ok" },
  skip: { label: "跳过", tone: "pill" },
  skipped: { label: "跳过", tone: "pill" },
  fail: { label: "失败", tone: "err" },
  error: { label: "失败", tone: "err" },
  warn: { label: "警告", tone: "warn" },
};

const CANVAS_TABS = [
  { id: "style", label: "风格与署名" },
  { id: "pipeline", label: "节点流水线" },
  { id: "delivery", label: "网页兜底与缓存" },
];

const CONSOLE_SECTIONS = [
  { id: "all", label: "全部参数" },
  { id: "platforms", label: "平台与传输" },
  { id: "accounts", label: "账号与 Cookie" },
  { id: "cloudflare", label: "CF 截图兜底" },
  { id: "themes", label: "主题画廊与日志" },
];

const PLATFORM_TRANSPORT_KEYS = [
  "BILI_QUALITY",
  "BILI_CODEC",
  "VIDEO_DURATION_MAXIMUM",
  "DOUYIN_LIVE_PHOTO_ENABLED",
  "TWITTER_MEDIA_PROXY_ENABLED",
  "TWITTER_MEDIA_PROXY_BASE",
  "FORWARD_MAX_NODES",
  "FORWARD_MAX_BATCH_MB",
];

const ACCOUNT_KEYS = [
  "BILI_CK",
  "XHS_CK",
  "BILI_COOKIE_MONITOR_ENABLED",
  "BILI_COOKIE_CHECK_INTERVAL",
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

export default {
  id: "glass-center",
  name: "空间指挥舱",
  subtitle: "Spatial Bento Cockpit · 三区空间画布 + 底部悬浮 Dock",
  description:
    "完全重构的页面信息架构：顶部半透明指挥条聚合作用域与快捷保存，首屏 Bento 驾驶舱直连实时诊断与一键平台芯片，创作台内嵌模拟聊天气泡真预览与泳道节点流水线。",
  badge: "空间感",
  preview: "cockpit",
  order: 20,
  styles: ["themes/glass-center/theme.css"],

  mount(mountEl, appCtx) {
    const {
      store,
      bili,
      preview,
      debug,
      cache,
      themes,
      setThemePreference,
      setColorModePreference,
      onDispose,
    } = appCtx;

    let activeWorkspace = "cockpit";
    let canvasTab = "style";
    let consoleSection = "all";
    let consoleSearch = "";
    let nodeMode = "video";
    let selectedNodeId = null;
    let dragNodeId = null;
    let dropZoneInfo = null;
    let cfAdvancedOpen = false;
    let addingGroup = false;
    let newGroupId = "";
    let newGroupLabel = "";
    let modalImage = null;
    const revealedSecrets = new Set();

    const deckEl = h("header", { class: "gc-deck" });
    const scopeDrawerEl = h("div", { class: "gc-scope-drawer is-hidden" });
    const stageEl = h("main", { class: "gc-stage" });
    const dockEl = h("nav", { class: "gc-dock-wrap", "aria-label": "空间导航" });
    const lightboxEl = h("div", { class: "gc-lightbox is-hidden" });

    const root = h(
      "div",
      { class: "gc-root" },
      deckEl,
      scopeDrawerEl,
      stageEl,
      dockEl,
      lightboxEl,
    );

    function renderDeck() {
      const dirtyCount = store.dirtyKeys().length;
      const mode = normalizeColorMode(store.draft.WEBUI_COLOR_MODE);
      const isGroup = Boolean(store.scope);
      const profiles = Array.isArray(store.groupProfiles) ? store.groupProfiles : [];
      const inProfiles = profiles.some((p) => p.scope_id === store.scope);

      const scopeSelect = h(
        "select",
        {
          class: "gc-scope-select",
          disabled: store.scopeBusy || store.saving,
          onchange: (e) => store.switchScope(e.target.value),
        },
        h("option", { value: "" }, "作用域：全局默认"),
        profiles.map((p) =>
          h(
            "option",
            { value: p.scope_id },
            `${p.display_name || p.scope_id}${p.has_override ? ` (${p.override_count}项)` : ""}`,
          ),
        ),
        store.scope && !inProfiles
          ? h("option", { value: store.scope }, `${store.scopeLabel} (${store.scope})`)
          : null,
      );
      scopeSelect.value = store.scope;

      deckEl.classList.toggle("has-dirty", dirtyCount > 0);
      swapContent(deckEl, [
        h(
          "div",
          { class: "gc-brand" },
          h("span", { class: "gc-logo-orb" }, icon("sparkles", 18)),
          h(
            "div",
            { class: "gc-brand-meta" },
            h("strong", null, "莉卡空间指挥舱"),
            h(
              "span",
              null,
              isGroup ? `分群 · ${store.scopeLabel}` : `全局控制中心 · ${store.meta?.version || "v3.5"}`,
            ),
          ),
        ),
        h(
          "div",
          { class: "gc-scope-cluster" },
          scopeSelect,
          isGroup
            ? h(
                "button",
                {
                  type: "button",
                  class: "gc-btn gc-btn-xs",
                  onclick: () => store.switchScope(""),
                },
                "回全局",
              )
            : null,
          h(
            "button",
            {
              type: "button",
              class: "gc-btn gc-btn-soft gc-btn-xs",
              onclick: () => {
                addingGroup = !addingGroup;
                renderScopeDrawer();
              },
            },
            addingGroup ? "收起" : "+ 分群",
          ),
          isGroup
            ? createInlineConfirmButton({
                label: "删档案",
                confirmLabel: "确认删除",
                cancelLabel: "否",
                buttonClass: "gc-btn gc-btn-xs",
                dangerClass: "gc-btn gc-btn-danger gc-btn-xs",
                onConfirm: () => store.deleteGroupScope(store.scope),
              })
            : null,
        ),
        h(
          "div",
          { class: "gc-deck-right" },
          h(
            "div",
            { class: "gc-color-switch", title: "界面明暗模式（全局）" },
            [
              { id: "auto", label: "自动" },
              { id: "light", label: "浅色" },
              { id: "dark", label: "深色" },
            ].map((m) =>
              h(
                "button",
                {
                  type: "button",
                  class: `gc-color-btn ${mode === m.id ? "is-active" : ""}`,
                  disabled: isGroup,
                  onclick: () => setColorModePreference(m.id),
                },
                m.label,
              ),
            ),
          ),
          dirtyCount > 0
            ? [
                h("span", { class: "gc-pill warn" }, `${dirtyCount} 项未保存`),
                h(
                  "button",
                  {
                    type: "button",
                    class: "gc-btn gc-btn-xs",
                    disabled: store.saving,
                    onclick: () => store.discardDraft(),
                  },
                  "放弃",
                ),
              ]
            : null,
          createInlineConfirmButton({
            label: store.scope ? "清空覆写" : "重置",
            confirmLabel: "确认",
            cancelLabel: "算了",
            buttonClass: "gc-btn gc-btn-xs",
            dangerClass: "gc-btn gc-btn-danger gc-btn-xs",
            onConfirm: () => store.resetConfig(),
          }),
          h(
            "button",
            {
              type: "button",
              class: "gc-btn gc-btn-primary gc-btn-sm",
              disabled: store.saving || dirtyCount === 0,
              onclick: () => store.saveDirty(),
            },
            store.saving ? "应用中…" : dirtyCount > 0 ? "保存生效" : "已同步",
          ),
        ),
      ]);
    }

    function renderScopeDrawer() {
      scopeDrawerEl.classList.toggle("is-hidden", !addingGroup);
      if (!addingGroup) {
        clear(scopeDrawerEl);
        return;
      }
      const idInp = h("input", {
        type: "text",
        class: "gc-input mono",
        style: { flex: "1.4", minWidth: "200px" },
        placeholder: "输入群号或 UMO（如 123456）",
        oninput: (e) => {
          newGroupId = e.target.value;
        },
      });
      idInp.value = newGroupId;
      const lblInp = h("input", {
        type: "text",
        class: "gc-input",
        style: { flex: "1", minWidth: "150px" },
        placeholder: "备注名（可选）",
        oninput: (e) => {
          newGroupLabel = e.target.value;
        },
      });
      lblInp.value = newGroupLabel;

      swapContent(scopeDrawerEl, [
        idInp,
        lblInp,
        h(
          "button",
          {
            type: "button",
            class: "gc-btn gc-btn-primary gc-btn-sm",
            disabled: store.scopeBusy,
            onclick: async () => {
              const ok = await store.createGroupScope(newGroupId, newGroupLabel);
              if (ok) {
                addingGroup = false;
                newGroupId = "";
                newGroupLabel = "";
                renderScopeDrawer();
              }
            },
          },
          store.scopeBusy ? "创建中…" : "创建并进入",
        ),
      ]);
    }

    function renderDock() {
      swapContent(dockEl, [
        h(
          "div",
          { class: "gc-dock", role: "tablist" },
          WORKSPACES.map((ws) =>
            h(
              "button",
              {
                type: "button",
                role: "tab",
                class: `gc-dock-btn ${activeWorkspace === ws.id ? "is-active" : ""}`,
                onclick: () => switchWorkspace(ws.id),
              },
              icon(ws.icon, 16),
              h("span", null, ws.label),
            ),
          ),
        ),
      ]);
    }

    function renderGlassField(item, { wide = false } = {}) {
      if (!item) return null;
      const isGroup = Boolean(store.scope);
      const overridable = !isGroup || store.isOverridable(item.key);
      const locked = isGroup && !overridable;
      const dirty = store.isKeyDirty(item.key);
      const overridden = store.isKeyOverridden(item.key);
      const pendingUnset = Boolean(store.pendingUnset?.has(item.key));
      const val = store.draft[item.key];

      let ctrlEl;
      if (item.type === "bool") {
        const chk = h("input", {
          type: "checkbox",
          checked: Boolean(val),
          disabled: locked,
          onchange: (e) => {
            store.setDraftValue(item.key, Boolean(e.target.checked));
            renderStage();
          },
        });
        ctrlEl = h(
          "label",
          { style: { display: "inline-flex", alignItems: "center", gap: "8px", cursor: locked ? "not-allowed" : "pointer" } },
          chk,
          h("span", { style: { fontWeight: "600" } }, Boolean(val) ? "已开启" : "已关闭"),
        );
      } else if (item.type === "select") {
        const opts = item.options || [];
        const labels = item.labels || opts;
        const sel = h(
          "select",
          {
            class: "gc-input",
            disabled: locked,
            onchange: (e) => {
              store.setDraftValue(item.key, e.target.value);
              renderStage();
            },
          },
          opts.map((o, i) =>
            h("option", { value: o, selected: String(val ?? "") === String(o) }, labels[i] || o),
          ),
        );
        sel.value = String(val ?? item.default ?? "");
        ctrlEl = sel;
      } else if (item.type === "list") {
        const ta = h("textarea", {
          class: "gc-input",
          rows: 3,
          disabled: locked,
          placeholder: item.placeholder || "每行或逗号分隔一条规则",
          oninput: (e) => {
            const rows = e.target.value
              .split(/\r?\n|,/)
              .map((s) => s.trim())
              .filter(Boolean);
            store.setDraftValue(item.key, rows, { rerender: false });
          },
        });
        ta.value = Array.isArray(val) ? val.join("\n") : String(val ?? "");
        ctrlEl = ta;
      } else if (item.type === "text") {
        const ta = h("textarea", {
          class: "gc-input mono",
          rows: 3,
          disabled: locked,
          placeholder: item.placeholder || "",
          oninput: (e) => store.setDraftValue(item.key, e.target.value, { rerender: false }),
        });
        ta.value = String(val ?? "");
        ctrlEl = ta;
      } else if (item.type === "int" || item.type === "float") {
        const num = h("input", {
          type: "number",
          class: "gc-input",
          disabled: locked,
          min: item.min ?? undefined,
          max: item.max ?? undefined,
          step: item.type === "float" ? String(item.step ?? 0.5) : "1",
          oninput: (e) => {
            if (e.target.value === "") return;
            const parsed =
              item.type === "float"
                ? Number.parseFloat(e.target.value)
                : Number.parseInt(e.target.value, 10);
            if (!Number.isNaN(parsed)) {
              store.setDraftValue(item.key, parsed, { rerender: false });
            }
          },
        });
        num.value = val ?? item.default ?? "";
        ctrlEl = item.unit
          ? h(
              "div",
              { style: { display: "flex", alignItems: "center", gap: "8px" } },
              num,
              h("span", { class: "gc-pill" }, item.unit),
            )
          : num;
      } else {
        const isSecret = Boolean(item.secret);
        let shown = isSecret && revealedSecrets.has(item.key);
        const inp = h("input", {
          type: isSecret && !shown ? "password" : "text",
          class: `gc-input ${isSecret ? "mono" : ""}`,
          disabled: locked,
          placeholder: item.placeholder || "",
          autocomplete: "off",
          oninput: (e) => store.setDraftValue(item.key, e.target.value, { rerender: false }),
        });
        inp.value = String(val ?? "");
        ctrlEl = isSecret
          ? h(
              "div",
              { style: { display: "flex", gap: "6px" } },
              inp,
              h(
                "button",
                {
                  type: "button",
                  class: "gc-btn gc-btn-xs",
                  onclick: () => {
                    if (revealedSecrets.has(item.key)) revealedSecrets.delete(item.key);
                    else revealedSecrets.add(item.key);
                    shown = revealedSecrets.has(item.key);
                    inp.type = shown ? "text" : "password";
                  },
                },
                "显隐",
              ),
            )
          : inp;
      }

      return h(
        "div",
        {
          class: `gc-field ${wide || item.type === "list" || item.type === "text" || item.secret ? "is-wide" : ""} ${dirty ? "is-dirty" : ""} ${locked ? "is-locked" : ""}`,
          dataset: { key: item.key },
        },
        h(
          "div",
          { class: "gc-field-head" },
          h("span", { class: "gc-field-title" }, item.label || item.key),
          h(
            "div",
            { style: { display: "inline-flex", alignItems: "center", gap: "5px", flexWrap: "wrap" } },
            store.showDevKeys ? h("code", { class: "gc-dev-key" }, item.key) : null,
            locked ? h("span", { class: "gc-pill" }, "仅全局") : null,
            overridden ? h("span", { class: "gc-pill info" }, "本群独立") : null,
            dirty ? h("span", { class: "gc-pill warn" }, pendingUnset ? "将恢复继承" : "待保存") : null,
            isGroup && overridable && (overridden || dirty)
              ? h(
                  "button",
                  {
                    type: "button",
                    class: "gc-btn gc-btn-xs",
                    onclick: () => store.revertKeyToInherit(item.key),
                  },
                  "恢复继承",
                )
              : null,
          ),
        ),
        item.hint ? h("p", { class: "gc-field-hint" }, item.hint) : null,
        ctrlEl,
      );
    }

    function renderCockpit() {
      const ov = store.overview || {};
      const platforms = ov.platforms || store.meta?.platforms || [];
      const enabledCount = platforms.filter((p) => store.isPlatformEnabled(p.name)).length;
      const biliState = bili.getState();
      const b = biliState.bili || {};
      const qr = biliState.qrSession;
      const dbg = debug.getState();
      const cacheInfo = ov.cache || {};
      const cacheState = cache.getState();
      const problems = ov.problems || store.meta?.problems || [];

      const urlInput = h("input", {
        type: "url",
        class: "gc-input",
        placeholder: "粘贴分享链接立即在当前作用域试跑诊断（只读，不发送）…",
        oninput: (e) => debug.setUrl(e.target.value),
        onkeydown: (e) => {
          if (e.key === "Enter" && !dbg.running) debug.runProbe();
        },
      });
      urlInput.value = dbg.url;

      const blocks = [];
      if (problems.length > 0) {
        blocks.push(
          h("div", { class: "gc-notice" }, h("strong", null, "配置提示："), problems.join("；")),
        );
      }

      blocks.push(
        h(
          "div",
          { class: "gc-bento-grid" },
          // Hero 诊断台
          h(
            "section",
            { class: "gc-tile gc-span-7" },
            h(
              "div",
              { class: "gc-tile-head" },
              h(
                "div",
                null,
                h("h2", null, "即时链路探针"),
                h(
                  "p",
                  { class: "gc-tile-sub" },
                  store.scope ? `按分群「${store.scopeLabel}」模拟节点与渲染` : "实时跟踪路由 → 解析 → 下载 → 出卡全链路",
                ),
              ),
              dbg.report?.token
                ? h(
                    "button",
                    {
                      type: "button",
                      class: "gc-btn gc-btn-soft gc-btn-xs",
                      onclick: () => debug.downloadLog(dbg.report.token, dbg.report.log_name),
                    },
                    "导出日志",
                  )
                : null,
            ),
            h(
              "div",
              { class: "gc-probe-row" },
              urlInput,
              h(
                "button",
                {
                  type: "button",
                  class: "gc-btn gc-btn-primary",
                  disabled: dbg.running,
                  onclick: () => debug.runProbe(),
                },
                dbg.running ? "探测中…" : "执行探测",
              ),
            ),
            h(
              "div",
              { class: "gc-probe-meta" },
              h(
                "div",
                { style: { display: "flex", gap: "12px", fontSize: "12px" } },
                h(
                  "label",
                  { style: { display: "inline-flex", alignItems: "center", gap: "5px" } },
                  h("input", {
                    type: "checkbox",
                    checked: dbg.downloadMedia,
                    onchange: (e) => debug.setDownloadMedia(Boolean(e.target.checked)),
                  }),
                  "下载媒体",
                ),
                h(
                  "label",
                  { style: { display: "inline-flex", alignItems: "center", gap: "5px" } },
                  h("input", {
                    type: "checkbox",
                    checked: dbg.renderCard,
                    onchange: (e) => debug.setRenderCard(Boolean(e.target.checked)),
                  }),
                  "渲染卡片",
                ),
              ),
              h(
                "div",
                { style: { display: "flex", gap: "6px" } },
                QUICK_URLS.map((s) =>
                  h(
                    "button",
                    {
                      type: "button",
                      class: "gc-btn gc-btn-xs",
                      onclick: () => {
                        debug.setUrl(s.url);
                        renderStage();
                      },
                    },
                    s.label,
                  ),
                ),
              ),
            ),
            dbg.error
              ? h("div", { class: "gc-notice" }, dbg.error)
              : dbg.report
                ? [
                    h(
                      "div",
                      { style: { display: "flex", flexWrap: "wrap", gap: "6px" } },
                      h(
                        "span",
                        { class: `gc-pill ${dbg.report.ok ? "ok" : "err"}` },
                        dbg.report.ok ? "诊断通过" : "发现异常",
                      ),
                      dbg.report.platform
                        ? h("span", { class: "gc-pill info" }, dbg.report.platform)
                        : null,
                      dbg.report.elapsed_ms != null
                        ? h("span", { class: "gc-pill" }, `${dbg.report.elapsed_ms} ms`)
                        : null,
                    ),
                    (dbg.report.steps || []).length > 0
                      ? h(
                          "div",
                          { class: "gc-waterfall" },
                          dbg.report.steps.map((st, idx) => {
                            const info = STEP_TONES[String(st.status || "").toLowerCase()] || {
                              label: st.status || "-",
                              tone: "pill",
                            };
                            return h(
                              "div",
                              { class: "gc-step-card" },
                              h(
                                "div",
                                { class: "gc-step-card-top" },
                                h("strong", null, `${idx + 1}. ${st.name || "步骤"}`),
                                h("span", { class: `gc-pill ${info.tone}` }, info.label),
                              ),
                              st.detail ? h("p", null, st.detail) : null,
                            );
                          }),
                        )
                      : null,
                    dbg.report.text ? h("pre", { class: "gc-log-pre" }, dbg.report.text) : null,
                  ]
                : h("p", { class: "gc-tile-sub" }, "运行一次链接探测即可在此展开各环节耗时与日志流水"),
          ),

          // 右上：B站账号状态与就地扫码
          h(
            "section",
            { class: "gc-tile gc-span-5" },
            h(
              "div",
              { class: "gc-tile-head" },
              h(
                "div",
                null,
                h("h2", null, "B站账号与扫码凭证"),
                h(
                  "p",
                  { class: "gc-tile-sub" },
                  b.username
                    ? `${b.username} (UID ${b.uid || 0})`
                    : b.has_cookie
                      ? "Cookie 已加密存储"
                      : "未登录 · 点击按钮直接面板扫码",
                ),
              ),
              h(
                "span",
                {
                  class: `gc-pill ${
                    !b.has_cookie ? "" : b.valid === true ? "ok" : b.valid === false ? "err" : "warn"
                  }`,
                },
                !b.has_cookie ? "未登录" : b.valid === true ? "有效" : b.valid === false ? "失效" : "待验证",
              ),
            ),
            h(
              "div",
              { style: { display: "flex", flexWrap: "wrap", gap: "6px" } },
              b.vip ? h("span", { class: "gc-pill info" }, "大会员") : null,
              b.has_cookie
                ? h("span", { class: `gc-pill ${b.refreshable ? "ok" : ""}` }, b.refreshable ? "自动续期" : "手动 Cookie")
                : null,
              h("span", { class: "gc-pill" }, b.monitor_running ? "监控运行中" : "监控未启动"),
            ),
            h(
              "div",
              { style: { display: "flex", flexWrap: "wrap", gap: "8px" } },
              h(
                "button",
                {
                  type: "button",
                  class: "gc-btn gc-btn-primary gc-btn-sm",
                  disabled: biliState.busyQr,
                  onclick: () => bili.startQrLogin(),
                },
                biliState.busyQr ? "申请中…" : qr ? "刷新二维码" : "扫码登录",
              ),
              h(
                "button",
                {
                  type: "button",
                  class: "gc-btn gc-btn-soft gc-btn-sm",
                  disabled: biliState.busyCheck,
                  onclick: () => bili.checkCookie(),
                },
                biliState.busyCheck ? "检测中…" : "检测 Cookie",
              ),
              h(
                "button",
                {
                  type: "button",
                  class: "gc-btn gc-btn-sm",
                  onclick: () => bili.refreshStatus(),
                },
                "刷新",
              ),
            ),
            qr
              ? h(
                  "div",
                  { class: "gc-bili-split" },
                  qr.qr_image ? h("img", { src: qr.qr_image, alt: "B站二维码", class: "gc-qr-img" }) : null,
                  h(
                    "div",
                    { style: { flex: "1", display: "flex", flexDirection: "column", gap: "6px" } },
                    h("strong", null, qr.message || "手机 B站扫码确认"),
                    qr.active && qr.remaining_seconds > 0
                      ? h("span", { class: "gc-tile-sub" }, `剩余 ${qr.remaining_seconds} 秒`)
                      : null,
                    h(
                      "button",
                      {
                        type: "button",
                        class: "gc-btn gc-btn-xs",
                        style: { alignSelf: "flex-start" },
                        onclick: () => bili.cancelQrLogin(),
                      },
                      qr.state === "success" ? "完成收起" : "取消扫码",
                    ),
                  ),
                )
              : null,
          ),

          // 左下：点击直控平台芯片墙
          h(
            "section",
            { class: "gc-tile gc-span-7" },
            h(
              "div",
              { class: "gc-tile-head" },
              h(
                "div",
                null,
                h("h3", null, "快捷平台矩阵（点击即切换）"),
                h("p", { class: "gc-tile-sub" }, `已启用 ${enabledCount} / ${platforms.length} 个平台 · 外部联动自动接入`),
              ),
              h(
                "button",
                {
                  type: "button",
                  class: "gc-btn gc-btn-xs",
                  onclick: () => switchWorkspace("console", "platforms"),
                },
                "策略详情 →",
              ),
            ),
            h(
              "div",
              { class: "gc-chip-wall" },
              platforms.map((p) => {
                const on = store.isPlatformEnabled(p.name);
                return h(
                  "button",
                  {
                    type: "button",
                    class: `gc-plat-chip ${on ? "" : "is-off"}`,
                    title: p.description || p.label,
                    onclick: () => {
                      store.togglePlatform(p.name);
                      renderStage();
                    },
                  },
                  h("span", { class: "gc-dot" }),
                  h("span", null, p.label || p.name),
                  p.external ? h("span", { class: "gc-pill info" }, "联动") : null,
                );
              }),
            ),
          ),

          // 右下：卡片脉搏与缓存
          h(
            "section",
            { class: "gc-tile gc-span-5" },
            h(
              "div",
              { class: "gc-tile-head" },
              h(
                "div",
                null,
                h("h3", null, "渲染与缓存快照"),
                h(
                  "p",
                  { class: "gc-tile-sub" },
                  `${store.draft.RENDER_STYLE} · ${store.draft.RENDER_THEME} · ${store.draft.RENDER_WIDTH}px`,
                ),
              ),
              h(
                "button",
                {
                  type: "button",
                  class: "gc-btn gc-btn-soft gc-btn-xs",
                  onclick: () => switchWorkspace("canvas"),
                },
                "进创作台",
              ),
            ),
            h(
              "div",
              { style: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: "8px" } },
              h(
                "div",
                null,
                h("strong", { style: { fontSize: "18px" } }, formatBytes(cacheInfo.bytes)),
                h(
                  "p",
                  { class: "gc-tile-sub" },
                  `${cacheInfo.files ?? 0} 个磁盘文件 · ${cacheInfo.memory_entries ?? 0} 条内存索引`,
                ),
              ),
              createInlineConfirmButton({
                label: cacheState.clearing ? "清理中…" : "清空缓存",
                confirmLabel: "确认删除",
                cancelLabel: "取消",
                buttonClass: "gc-btn gc-btn-sm",
                dangerClass: "gc-btn gc-btn-danger gc-btn-sm",
                onConfirm: () => cache.clearAll(),
              }),
            ),
          ),
        ),
      );

      return blocks;
    }

    function renderNodePipelineTab() {
      const schema = store.meta?.node_schema || { modes: [], catalog: {}, defaults: {} };
      const modes = schema.modes || [];
      const catalog = schema.catalog || {};
      const defaults = schema.defaults || {};
      if (!modes.length) {
        return h("div", { class: "gc-tile" }, "后端未返回节点编排元信息");
      }
      if (!modes.some((m) => m.id === nodeMode)) {
        nodeMode = modes[0].id;
      }

      const current = normalizeNodeRulesClient(store.draft.NODE_RULES, schema);
      const list = current[nodeMode] || [];
      const buckets = splitNodeBuckets(list, catalog);
      const locked = Boolean(store.scope) && !store.isOverridable("NODE_RULES");
      const summary = buildOrderSummary(list, catalog);

      if (selectedNodeId && !list.some((r) => r.id === selectedNodeId)) {
        selectedNodeId = null;
      }

      const moveSelectedOr = (nodeId, targetZone, targetIndex = null) => {
        const res = moveNodeBetweenZones({
          rawRules: store.draft.NODE_RULES,
          nodeSchema: schema,
          mode: nodeMode,
          nodeId,
          targetZone,
          targetIndex,
        });
        if (!res.ok) {
          if (res.reason) store.toast(res.reason, "warn", 3400);
          return;
        }
        selectedNodeId = nodeId;
        store.setDraftValue("NODE_RULES", res.serialized);
        renderStage();
      };

      const selectedMeta = selectedNodeId ? catalog[selectedNodeId] || { label: selectedNodeId } : null;
      const selectedEntry = selectedNodeId ? list.find((r) => r.id === selectedNodeId) : null;
      const selectedZone = selectedEntry ? zoneOfEntry(selectedEntry, catalog) : null;
      const selectedZoneList = selectedZone ? buckets[selectedZone] || [] : [];
      const selectedIdx = selectedZoneList.indexOf(selectedNodeId);

      return h(
        "div",
        { style: { display: "flex", flexDirection: "column", gap: "12px" } },
        h(
          "div",
          { style: { display: "flex", flexWrap: "wrap", justifyContent: "space-between", alignItems: "center", gap: "8px" } },
          h(
            "div",
            { class: "gc-seg-bar" },
            modes.map((m) =>
              h(
                "button",
                {
                  type: "button",
                  class: `gc-seg-btn ${nodeMode === m.id ? "is-active" : ""}`,
                  onclick: () => {
                    nodeMode = m.id;
                    selectedNodeId = null;
                    renderStage();
                  },
                },
                m.label,
              ),
            ),
          ),
          !rulesEqual({ [nodeMode]: list }, { [nodeMode]: defaults[nodeMode] || [] }, schema) && !locked
            ? h(
                "button",
                {
                  type: "button",
                  class: "gc-btn gc-btn-xs",
                  onclick: () => {
                    current[nodeMode] = cloneNodeRules(defaults[nodeMode] || []);
                    store.setDraftValue("NODE_RULES", serializeNodeRules(current, schema));
                    renderStage();
                  },
                },
                "恢复默认序列",
              )
            : null,
        ),
        h(
          "div",
          { style: { display: "flex", flexWrap: "wrap", gap: "6px", alignItems: "center" } },
          h("span", { class: "gc-tile-sub" }, "实时链路："),
          summary.map((c) =>
            h(
              "span",
              { class: `gc-pill ${c.kind === "merge" ? "info" : c.kind === "warn" ? "warn" : ""}` },
              c.label,
            ),
          ),
        ),
        h(
          "div",
          { class: "gc-lanes" },
          NODE_ZONES.map((zone) => {
            const ids = buckets[zone.id] || [];
            const laneEl = h(
              "div",
              { class: "gc-lane", dataset: { zone: zone.id } },
              h(
                "div",
                { class: "gc-lane-head" },
                h("strong", null, zone.title),
                h("span", { class: "gc-pill" }, String(ids.length)),
              ),
              h(
                "div",
                { class: "gc-lane-cards" },
                ids.length === 0
                  ? h("span", { class: "gc-tile-sub" }, zone.emptyHint)
                  : ids.map((nid, idx) => {
                      const meta = catalog[nid] || { label: nid, supports_merge: true };
                      const supportsMerge = meta.supports_merge !== false;
                      const chip = h(
                        "div",
                        {
                          class: `gc-node-chip ${selectedNodeId === nid ? "is-selected" : ""}`,
                          draggable: locked ? "false" : "true",
                          title: meta.description || meta.label || nid,
                          onclick: () => {
                            selectedNodeId = nid;
                            renderStage();
                          },
                        },
                        zone.id !== "disabled" ? h("span", { class: "gc-pill" }, String(idx + 1)) : null,
                        h("span", { style: { flex: "1" } }, meta.label || nid),
                        !supportsMerge ? h("span", { class: "gc-pill warn" }, "禁合并") : null,
                      );
                      if (!locked) {
                        chip.addEventListener("dragstart", (e) => {
                          dragNodeId = nid;
                          if (e.dataTransfer) {
                            e.dataTransfer.effectAllowed = "move";
                            e.dataTransfer.setData("text/plain", nid);
                          }
                        });
                        chip.addEventListener("dragover", (e) => {
                          if (!dragNodeId || (zone.id === "merge" && catalog[dragNodeId]?.supports_merge === false)) return;
                          e.preventDefault();
                          e.stopPropagation();
                          dropZoneInfo = { zone: zone.id, index: idx };
                        });
                      }
                      return chip;
                    }),
              ),
            );
            if (!locked) {
              laneEl.addEventListener("dragover", (e) => {
                const forbidden =
                  zone.id === "merge" && dragNodeId && catalog[dragNodeId]?.supports_merge === false;
                e.preventDefault();
                laneEl.classList.toggle("is-drop-forbidden", Boolean(forbidden));
                laneEl.classList.toggle("is-drop-target", !forbidden);
                if (!dropZoneInfo || dropZoneInfo.zone !== zone.id) {
                  dropZoneInfo = { zone: zone.id, index: ids.length };
                }
              });
              laneEl.addEventListener("dragleave", (e) => {
                if (!e.relatedTarget || !laneEl.contains(e.relatedTarget)) {
                  laneEl.classList.remove("is-drop-target", "is-drop-forbidden");
                }
              });
              laneEl.addEventListener("drop", (e) => {
                e.preventDefault();
                laneEl.classList.remove("is-drop-target", "is-drop-forbidden");
                const nid = dragNodeId || e.dataTransfer?.getData?.("text/plain") || "";
                const info = dropZoneInfo;
                dragNodeId = null;
                dropZoneInfo = null;
                if (!nid) return;
                moveSelectedOr(nid, zone.id, info?.zone === zone.id ? info.index : ids.length);
              });
            }
            return laneEl;
          }),
        ),
        selectedNodeId && selectedMeta
          ? h(
              "div",
              { class: "gc-tile", style: { padding: "12px", gap: "8px" } },
              h(
                "div",
                { style: { display: "flex", flexWrap: "wrap", justifyContent: "space-between", alignItems: "center", gap: "8px" } },
                h("strong", null, `${selectedMeta.label || selectedNodeId}：${selectedMeta.description || ""}`),
                h(
                  "div",
                  { style: { display: "flex", flexWrap: "wrap", gap: "6px" } },
                  NODE_ZONES.map((z) =>
                    h(
                      "button",
                      {
                        type: "button",
                        class: `gc-btn gc-btn-xs ${selectedZone === z.id ? "gc-btn-primary" : ""}`,
                        disabled: locked || (z.id === "merge" && selectedMeta.supports_merge === false),
                        onclick: () => moveSelectedOr(selectedNodeId, z.id),
                      },
                      z.title,
                    ),
                  ),
                  h(
                    "button",
                    {
                      type: "button",
                      class: "gc-btn gc-btn-xs",
                      disabled: locked || selectedIdx <= 0,
                      onclick: () => moveSelectedOr(selectedNodeId, selectedZone, selectedIdx - 1),
                    },
                    "上移",
                  ),
                  h(
                    "button",
                    {
                      type: "button",
                      class: "gc-btn gc-btn-xs",
                      disabled: locked || selectedIdx < 0 || selectedIdx >= selectedZoneList.length - 1,
                      onclick: () => moveSelectedOr(selectedNodeId, selectedZone, selectedIdx + 2),
                    },
                    "下移",
                  ),
                ),
              ),
            )
          : null,
      );
    }

    function renderCanvas() {
      const pState = preview.getState();
      const map = store.itemMap();
      const stylesMeta = store.meta?.styles || [];
      const thumbByName = new Map((pState.thumbs || []).map((t) => [t.name, t.image]));
      const samples = store.meta?.preview_samples || [
        { id: "video", label: "B站视频" },
        { id: "gallery", label: "小红书图集" },
        { id: "repost", label: "微博转发" },
      ];
      const d = pState.data;
      const personaOn = Boolean(store.draft.RENDER_PERSONA_WATERMARK);
      const activeBrand = personaOn
        ? `${pState.personaName || "达妮娅"}解析`
        : String(store.draft.RENDER_BRAND_NAME || "莉卡解析");

      const chatStage = h(
        "aside",
        { class: "gc-chat-stage" },
        h(
          "div",
          { class: "gc-tile-head" },
          h(
            "div",
            null,
            h("h2", null, "聊天真机效果"),
            h("p", { class: "gc-tile-sub" }, d ? `${d.used_style} · ${d.width}px · ${d.render_ms}ms` : "准备实时出图…"),
          ),
          h(
            "button",
            {
              type: "button",
              class: "gc-btn gc-btn-xs",
              disabled: pState.loading,
              onclick: () => preview.scheduleCard(0),
            },
            icon("refresh", 13),
            "重绘",
          ),
        ),
        h(
          "div",
          { class: "gc-seg-bar" },
          samples.map((sp) =>
            h(
              "button",
              {
                type: "button",
                class: `gc-seg-btn ${pState.sampleId === sp.id ? "is-active" : ""}`,
                onclick: () => preview.setSampleId(sp.id),
              },
              sp.label.replace(/（.*）/, ""),
            ),
          ),
        ),
        h(
          "div",
          { class: "gc-chat-phone" },
          h(
            "div",
            { class: "gc-chat-msg" },
            h("div", { class: "gc-chat-avatar" }, activeBrand.slice(0, 1)),
            h(
              "div",
              { class: "gc-chat-bubble" },
              h("div", { class: "gc-chat-sender" }, `${activeBrand} · Bot 预览`),
              pState.error
                ? h("div", { class: "gc-notice" }, pState.error)
                : d?.image
                  ? h("img", {
                      src: d.image,
                      alt: "实时卡片渲染图",
                      class: "gc-preview-img",
                      onclick: () => {
                        modalImage = d.image;
                        renderLightbox();
                      },
                    })
                  : h("p", { class: "gc-tile-sub" }, "正在渲染后端卡片图像…"),
            ),
          ),
        ),
      );

      let tabBody;
      if (canvasTab === "style") {
        const personaInp = h("input", {
          type: "text",
          class: "gc-input",
          placeholder: "输入试看人格（如 达妮娅）",
          oninput: (e) => preview.setPersonaName(e.target.value),
        });
        personaInp.value = pState.personaName;

        const brandInp = h("input", {
          type: "text",
          class: "gc-input",
          maxlength: 16,
          placeholder: "莉卡解析",
          oninput: (e) => {
            store.setDraftValue("RENDER_BRAND_NAME", e.target.value, { rerender: false });
            preview.scheduleCard(240);
          },
        });
        brandInp.value = String(store.draft.RENDER_BRAND_NAME ?? "莉卡解析");

        const widthVal = Number(store.draft.RENDER_WIDTH || 800);
        const widthSlider = h("input", {
          type: "range",
          min: 520,
          max: 1080,
          step: 20,
          style: { width: "100%" },
          oninput: (e) => {
            const n = Number.parseInt(e.target.value, 10);
            if (!Number.isNaN(n)) {
              store.setDraftValue("RENDER_WIDTH", n, { rerender: false });
              widthBadge.textContent = `${n}px`;
              preview.scheduleCard(220);
            }
          },
        });
        widthSlider.value = String(widthVal);
        const widthBadge = h("span", { class: "gc-pill info" }, `${widthVal}px`);

        tabBody = h(
          "div",
          { style: { display: "flex", flexDirection: "column", gap: "14px" } },
          h(
            "div",
            { style: { display: "flex", justifyContent: "space-between", alignItems: "center" } },
            h("strong", null, "卡片样式马赛克"),
            h(
              "label",
              { style: { display: "inline-flex", gap: "6px", alignItems: "center", cursor: "pointer" } },
              h("input", {
                type: "checkbox",
                checked: Boolean(store.draft.RENDER_ENABLED),
                onchange: (e) => {
                  store.setDraftValue("RENDER_ENABLED", Boolean(e.target.checked));
                  renderStage();
                },
              }),
              h("span", null, store.draft.RENDER_ENABLED ? "开启图片卡片" : "仅纯文本"),
            ),
          ),
          h(
            "div",
            { class: "gc-style-mosaic" },
            stylesMeta.map((st) => {
              const active = st.name === String(store.draft.RENDER_STYLE || "standard");
              const thumb = thumbByName.get(st.name);
              return h(
                "button",
                {
                  type: "button",
                  class: `gc-style-card ${active ? "is-active" : ""}`,
                  onclick: () => {
                    store.setDraftValue("RENDER_STYLE", st.name);
                    preview.scheduleCard(0);
                    renderStage();
                  },
                },
                h(
                  "div",
                  { class: "gc-style-thumb" },
                  thumb ? h("img", { src: thumb, alt: st.display_name }) : h("span", { class: "gc-tile-sub" }, st.display_name),
                ),
                h("strong", null, st.display_name),
                h("span", { class: "gc-tile-sub" }, st.description || st.name),
              );
            }),
          ),
          h(
            "div",
            { class: "gc-fields-grid" },
            h(
              "div",
              { class: "gc-field" },
              h("div", { class: "gc-field-head" }, h("span", { class: "gc-field-title" }, "卡片色板"), widthBadge),
              h(
                "div",
                { class: "gc-seg-bar" },
                [
                  { id: "dark", label: "深色" },
                  { id: "light", label: "浅色" },
                ].map((m) =>
                  h(
                    "button",
                    {
                      type: "button",
                      class: `gc-seg-btn ${store.draft.RENDER_THEME === m.id ? "is-active" : ""}`,
                      onclick: () => {
                        store.setDraftValue("RENDER_THEME", m.id);
                        preview.fetchStyleThumbs();
                        preview.scheduleCard(0);
                        renderStage();
                      },
                    },
                    m.label,
                  ),
                ),
              ),
              widthSlider,
            ),
            h(
              "div",
              { class: "gc-field" },
              h("div", { class: "gc-field-head" }, h("span", { class: "gc-field-title" }, "署名与人格跟随")),
              h(
                "label",
                { style: { display: "inline-flex", gap: "6px", alignItems: "center", cursor: "pointer" } },
                h("input", {
                  type: "checkbox",
                  checked: personaOn,
                  onchange: (e) => {
                    store.setDraftValue("RENDER_PERSONA_WATERMARK", Boolean(e.target.checked));
                    preview.fetchStyleThumbs();
                    preview.scheduleCard(0);
                    renderStage();
                  },
                }),
                h("span", null, personaOn ? "跟随会话人格" : "固定自定义署名"),
              ),
              personaOn ? personaInp : brandInp,
            ),
            renderGlassField(map.get("RENDER_COVER_FULL_SIZE")),
            renderGlassField(map.get("RENDER_FONT_PATH")),
          ),
        );
      } else if (canvasTab === "pipeline") {
        tabBody = renderNodePipelineTab();
      } else {
        tabBody = h(
          "div",
          { class: "gc-fields-grid" },
          ["WEBPAGE_FALLBACK_ENABLED", "WEBPAGE_TDOCS_JUMP", "CACHE_TTL_HOURS", "CACHE_CLEANUP_INTERVAL_MINUTES"]
            .map((k) => renderGlassField(map.get(k)))
            .filter(Boolean),
        );
      }

      const rightInspector = h(
        "section",
        { class: "gc-tile" },
        h(
          "div",
          { class: "gc-seg-bar" },
          CANVAS_TABS.map((t) =>
            h(
              "button",
              {
                type: "button",
                class: `gc-seg-btn ${canvasTab === t.id ? "is-active" : ""}`,
                onclick: () => {
                  canvasTab = t.id;
                  renderStage();
                },
              },
              t.label,
            ),
          ),
        ),
        tabBody,
      );

      return [h("div", { class: "gc-canvas-split" }, chatStage, rightInspector)];
    }

    function renderConsole() {
      const map = store.itemMap();
      const kw = consoleSearch.trim().toLowerCase();
      const matchItem = (it) => {
        if (!it || !kw) return Boolean(it);
        return `${it.key} ${it.label || ""} ${it.hint || ""}`.toLowerCase().includes(kw);
      };

      const searchInp = h("input", {
        type: "search",
        class: "gc-input",
        style: { maxWidth: "300px" },
        placeholder: "搜索任意配置项、键名或说明…",
        oninput: (e) => {
          consoleSearch = e.target.value;
          renderStage();
        },
      });
      searchInp.value = consoleSearch;

      const themeList = themes.listThemes();
      const activeThemeId = String(store.draft.WEBUI_THEME || "studio").toLowerCase();

      const headerTile = h(
        "section",
        { class: "gc-tile" },
        h(
          "div",
          { class: "gc-tile-head" },
          h(
            "div",
            { class: "gc-seg-bar" },
            CONSOLE_SECTIONS.map((s) =>
              h(
                "button",
                {
                  type: "button",
                  class: `gc-seg-btn ${consoleSection === s.id ? "is-active" : ""}`,
                  onclick: () => {
                    consoleSection = s.id;
                    renderStage();
                  },
                },
                s.label,
              ),
            ),
          ),
          searchInp,
        ),
      );

      const tiles = [headerTile];
      const show = (id) => Boolean(kw) || consoleSection === "all" || consoleSection === id;

      if (show("themes")) {
        const logItems = LOG_KEYS.map((k) => map.get(k)).filter(matchItem);
        tiles.push(
          h(
            "section",
            { class: "gc-tile" },
            h(
              "div",
              { class: "gc-tile-head" },
              h(
                "div",
                null,
                h("h2", null, "整页网页主题画廊"),
                h("p", { class: "gc-tile-sub" }, "每套主题拥有独立 HTML DOM 架构、交互流与 CSS 样式隔离；点击即可整页卸载并热切换"),
              ),
              h("span", { class: "gc-pill info" }, `已发现 ${themeList.length} 套`),
            ),
            h(
              "div",
              { class: "gc-theme-gallery" },
              themeList.map((t) =>
                h(
                  "button",
                  {
                    type: "button",
                    disabled: Boolean(store.scope),
                    class: `gc-theme-card ${t.id === activeThemeId ? "is-active" : ""}`,
                    onclick: () => {
                      if (!store.scope) setThemePreference(t.id);
                    },
                  },
                  h(
                    "div",
                    { style: { display: "flex", justifyContent: "space-between", alignItems: "center" } },
                    h("strong", { style: { fontSize: "15px" } }, t.name),
                    t.badge ? h("span", { class: "gc-pill info" }, t.badge) : null,
                  ),
                  h("span", { class: "gc-pill" }, t.subtitle || t.id),
                  h("p", { class: "gc-tile-sub", style: { lineHeight: "1.5" } }, t.description),
                ),
              ),
            ),
            h(
              "div",
              { class: "gc-fields-grid" },
              logItems.map((it) => renderGlassField(it)),
              h(
                "div",
                { class: "gc-field" },
                h("div", { class: "gc-field-head" }, h("span", { class: "gc-field-title" }, "显示底层变量名")),
                h(
                  "label",
                  { style: { display: "inline-flex", gap: "8px", alignItems: "center", cursor: "pointer" } },
                  h("input", {
                    type: "checkbox",
                    checked: Boolean(store.showDevKeys),
                    onchange: (e) => store.setShowDevKeys(Boolean(e.target.checked)),
                  }),
                  h("span", null, store.showDevKeys ? "已展示" : "简洁隐藏"),
                ),
              ),
            ),
          ),
        );
      }

      if (show("platforms")) {
        const items = PLATFORM_TRANSPORT_KEYS.map((k) => map.get(k)).filter(matchItem);
        if (items.length > 0) {
          tiles.push(
            h(
              "section",
              { class: "gc-tile" },
              h("div", { class: "gc-tile-head" }, h("h2", null, "下载画质、代理与合并转发策略")),
              h("div", { class: "gc-fields-grid" }, items.map((it) => renderGlassField(it))),
            ),
          );
        }
      }

      if (show("accounts")) {
        const items = ACCOUNT_KEYS.map((k) => map.get(k)).filter(matchItem);
        if (items.length > 0) {
          tiles.push(
            h(
              "section",
              { class: "gc-tile" },
              h("div", { class: "gc-tile-head" }, h("h2", null, "账号凭据与监控明细")),
              h("div", { class: "gc-fields-grid" }, items.map((it) => renderGlassField(it))),
            ),
          );
        }
      }

      if (show("cloudflare")) {
        const basics = CF_BASIC_KEYS.map((k) => map.get(k)).filter(matchItem);
        const adv = (store.meta?.items || []).filter((it) => it.tier === "advanced" && matchItem(it));
        if (basics.length > 0 || adv.length > 0) {
          tiles.push(
            h(
              "section",
              { class: "gc-tile" },
              h("div", { class: "gc-tile-head" }, h("h2", null, "Cloudflare 网页渲染兜底")),
              h("div", { class: "gc-fields-grid" }, basics.map((it) => renderGlassField(it))),
              adv.length > 0
                ? h(
                    "details",
                    {
                      open: cfAdvancedOpen,
                      ontoggle: (e) => {
                        cfAdvancedOpen = Boolean(e.target.open);
                      },
                    },
                    h("summary", { style: { cursor: "pointer", fontWeight: "600" } }, `展开高级参数 (${adv.length} 项)`),
                    h("div", { class: "gc-fields-grid", style: { marginTop: "10px" } }, adv.map((it) => renderGlassField(it))),
                  )
                : null,
            ),
          );
        }
      }

      return tiles;
    }

    function renderStage() {
      preserveScroll(() => {
        let nodes = [];
        if (activeWorkspace === "cockpit") nodes = renderCockpit();
        else if (activeWorkspace === "canvas") nodes = renderCanvas();
        else nodes = renderConsole();
        swapContent(stageEl, nodes);
      });
    }

    function renderLightbox() {
      clear(lightboxEl);
      lightboxEl.classList.toggle("is-hidden", !modalImage);
      if (!modalImage) return;
      lightboxEl.onclick = () => {
        modalImage = null;
        renderLightbox();
      };
      lightboxEl.appendChild(h("img", { src: modalImage, alt: "高清放大图" }));
    }

    function switchWorkspace(wsId, sectionId = null) {
      activeWorkspace = wsId;
      if (sectionId) consoleSection = sectionId;
      renderDock();
      renderStage();
      if (wsId === "canvas") {
        preview.fetchStyleThumbs();
        const p = preview.getState();
        if (!p.data && !p.loading) preview.scheduleCard(0);
      }
    }

    renderDeck();
    renderScopeDrawer();
    renderDock();
    renderStage();
    bili.refreshStatus();
    mountEl.appendChild(root);

    onDispose(
      store.subscribe((ev) => {
        if (ev.type === "draft") {
          for (const el of mountEl.querySelectorAll(`.gc-field[data-key="${ev.key}"]`)) {
            el.classList.toggle("is-dirty", store.isKeyDirty(ev.key));
          }
          renderDeck();
          if (ev.reverted || ev.key === "WEBUI_COLOR_MODE") renderStage();
        } else if (ev.type === "snapshot" || ev.type === "discard" || ev.type === "scope" || ev.type === "saving") {
          renderDeck();
          renderStage();
        } else if (ev.type === "overview" || ev.type === "devkeys") {
          renderStage();
        }
      }),
    );
    onDispose(bili.subscribe(() => {
      if (activeWorkspace === "cockpit") renderStage();
    }));
    onDispose(preview.subscribe(() => {
      if (activeWorkspace === "canvas") renderStage();
    }));
    onDispose(debug.subscribe(() => {
      if (activeWorkspace === "cockpit") renderStage();
    }));
    onDispose(cache.subscribe(() => {
      if (activeWorkspace === "cockpit") renderStage();
    }));
    onDispose(subscribeThemes(() => {
      if (activeWorkspace === "console") renderStage();
    }));

    return {
      unmount() {
        bili.stopPolling();
        root.remove();
      },
    };
  },
};
