import { createInlineConfirmButton, formatBytes, h, icon, swapContent } from "../../../core/dom.js";

const STEP_TONES = {
  ok: { label: "通过", tone: "ok" },
  pass: { label: "通过", tone: "ok" },
  skip: { label: "跳过", tone: "neutral" },
  skipped: { label: "跳过", tone: "neutral" },
  fail: { label: "失败", tone: "err" },
  error: { label: "失败", tone: "err" },
  warn: { label: "警告", tone: "warn" },
};

const QUICK_URLS = [
  { label: "B站视频", url: "https://www.bilibili.com/video/BV1GJ411x7h7" },
  { label: "GitHub 仓库", url: "https://github.com/AstrBotDevs/AstrBot" },
];

export function createStudioWorkbenchView(appCtx, { navigate }) {
  const { store, bili, debug, cache, themes } = appCtx;
  const root = h("div", { class: "page-stack" });

  function renderProbeOutput() {
    const dbg = debug.getState();
    if (dbg.error) {
      return h("div", { class: "notice notice-err" }, h("strong", null, "诊断请求失败："), dbg.error);
    }
    if (!dbg.report) {
      return h(
        "p",
        { class: "empty-note" },
        "输入分享链接并执行只读测试，可逐阶段验证路由匹配、网络解析、媒体下载与卡片生成结果（不会向任何聊天发消息）。",
      );
    }

    const probeReport = dbg.report;
    const steps = probeReport.steps || [];
    const summary = Object.entries(probeReport.summary || {});
    const token = probeReport.token || "";

    return h(
      "div",
      { class: "probe-output" },
      h(
        "div",
        { class: "probe-summary-head" },
        h(
          "div",
          { class: "probe-badges" },
          h(
            "span",
            { class: `pill ${probeReport.ok ? "pill-ok" : "pill-err"}` },
            probeReport.ok ? "诊断通过" : "存在异常",
          ),
          probeReport.scope_label ? h("span", { class: "pill pill-neutral" }, probeReport.scope_label) : null,
          probeReport.platform ? h("span", { class: "pill pill-info" }, probeReport.platform) : null,
          probeReport.elapsed_ms != null
            ? h("span", { class: "pill" }, `${probeReport.elapsed_ms} ms`)
            : null,
        ),
        token
          ? h(
              "button",
              {
                type: "button",
                class: "btn btn-soft btn-sm",
                onclick: () => debug.downloadLog(token, probeReport.log_name),
              },
              "下载脱敏日志",
            )
          : null,
      ),
      summary.length > 0
        ? h(
            "dl",
            { class: "kv-grid" },
            summary.map(([k, v]) =>
              h("div", { class: "kv-item" }, h("dt", null, k), h("dd", null, String(v ?? ""))),
            ),
          )
        : null,
      steps.length > 0
        ? h(
            "div",
            { class: "step-list" },
            steps.map((step, i) => {
              const st = STEP_TONES[String(step.status || "").toLowerCase()] || {
                label: step.status || "未知",
                tone: "neutral",
              };
              return h(
                "div",
                { class: "step-row" },
                h("span", { class: "step-num" }, String(i + 1)),
                h(
                  "div",
                  { class: "step-info" },
                  h(
                    "div",
                    { class: "step-top" },
                    h("strong", null, step.name || `步骤 ${i + 1}`),
                    h("span", { class: `pill pill-${st.tone}` }, st.label),
                    step.elapsed_ms != null
                      ? h("span", { class: "step-ms" }, `${step.elapsed_ms} ms`)
                      : null,
                  ),
                  step.detail ? h("p", { class: "step-detail" }, step.detail) : null,
                ),
              );
            }),
          )
        : null,
      probeReport.text ? h("pre", { class: "log-viewer" }, probeReport.text) : null,
    );
  }

  function render() {
    const sections = [];
    const ov = store.overview || {};
    const platforms = ov.platforms || store.meta?.platforms || [];
    const enabledCount = platforms.filter((p) => p.enabled).length;
    const extCount = platforms.filter((p) => p.external).length;
    const biliState = bili.getState();
    const biliInfo = biliState.bili || {};
    const cacheInfo = ov.cache || {};
    const cacheCtrl = cache.getState();
    const dbg = debug.getState();
    const activeTheme = themes.getTheme(store.draft.WEBUI_THEME);
    const problems = ov.problems || store.meta?.problems || [];
    const personaOn = Boolean(store.draft.RENDER_PERSONA_WATERMARK);

    if (problems.length > 0) {
      sections.push(
        h(
          "div",
          { class: "notice notice-warn" },
          h("strong", null, `配置自检提示（${problems.length}）：`),
          problems.join("；"),
        ),
      );
    }

    const biliLabel = !biliInfo.has_cookie
      ? "未配置"
      : biliInfo.valid === true
        ? biliInfo.username || "有效"
        : biliInfo.valid === false
          ? "已失效"
          : "待验证";
    const biliTone = !biliInfo.has_cookie
      ? "neutral"
      : biliInfo.valid === true
        ? "ok"
        : biliInfo.valid === false
          ? "err"
          : "warn";

    sections.push(
      h(
        "div",
        { class: "kpi-grid" },
        h(
          "section",
          { class: "kpi-card" },
          h(
            "div",
            { class: "kpi-head" },
            h("span", { class: "kpi-label" }, "解析平台"),
            h("span", { class: "pill pill-ok" }, `${enabledCount}/${platforms.length}`),
          ),
          h("div", { class: "kpi-value" }, `${enabledCount} 个启用`),
          h(
            "p",
            { class: "kpi-sub" },
            `${extCount > 0 ? `含 ${extCount} 个外部联动插件` : "全部使用内置适配器"}${
              (store.groupProfiles || []).some((g) => g.has_override)
                ? ` · ${(store.groupProfiles || []).filter((g) => g.has_override).length} 个独立分群`
                : ""
            }`,
          ),
          h(
            "button",
            {
              type: "button",
              class: "btn btn-ghost btn-sm",
              onclick: () => navigate("platforms"),
            },
            "管理平台与账号 →",
          ),
        ),
        h(
          "section",
          { class: "kpi-card" },
          h(
            "div",
            { class: "kpi-head" },
            h("span", { class: "kpi-label" }, "B站登录态"),
            h("span", { class: `pill pill-${biliTone}` }, biliLabel),
          ),
          h(
            "div",
            { class: "kpi-value" },
            biliInfo.username ? biliInfo.username : biliInfo.has_cookie ? "已存 Cookie" : "未登录",
          ),
          h(
            "p",
            { class: "kpi-sub" },
            `${biliInfo.refreshable ? "自动续期就绪 · " : ""}监控 ${biliInfo.monitor_running ? "运行中" : "已停"}${biliInfo.last_check_time ? ` · ${biliInfo.last_check_time}` : ""}`,
          ),
          h(
            "div",
            { class: "btn-group" },
            h(
              "button",
              {
                type: "button",
                class: "btn btn-soft btn-sm",
                disabled: biliState.busyCheck,
                onclick: () => bili.checkCookie(),
              },
              biliState.busyCheck ? "检测中…" : "检测有效性",
            ),
            h(
              "button",
              {
                type: "button",
                class: "btn btn-ghost btn-sm",
                onclick: () => navigate("platforms"),
              },
              biliInfo.has_cookie ? "扫码更新" : "扫码登录 →",
            ),
          ),
        ),
        h(
          "section",
          { class: "kpi-card" },
          h(
            "div",
            { class: "kpi-head" },
            h("span", { class: "kpi-label" }, "卡片与署名"),
            h(
              "span",
              { class: `pill ${store.draft.RENDER_ENABLED ? "pill-info" : "pill-neutral"}` },
              store.draft.RENDER_ENABLED ? store.draft.RENDER_STYLE : "纯文本",
            ),
          ),
          h(
            "div",
            { class: "kpi-value" },
            personaOn
              ? "人格动态署名"
              : (String(store.draft.RENDER_BRAND_NAME || "").trim() || ov.renderer?.brand_name || "莉卡解析"),
          ),
          h(
            "p",
            { class: "kpi-sub" },
            `${store.draft.RENDER_THEME === "light" ? "浅色" : "深色"} · ${store.draft.RENDER_WIDTH}px · 界面「${activeTheme?.name || "工作台"}」`,
          ),
          h(
            "button",
            {
              type: "button",
              class: "btn btn-soft btn-sm",
              onclick: () => navigate("studio"),
            },
            "进入卡片工作室 →",
          ),
        ),
        h(
          "section",
          { class: "kpi-card" },
          h(
            "div",
            { class: "kpi-head" },
            h("span", { class: "kpi-label" }, "磁盘与内存缓存"),
            h(
              "span",
              { class: "pill pill-neutral" },
              cacheInfo.ttl_hours ? `TTL ${cacheInfo.ttl_hours}h` : "不自动清理",
            ),
          ),
          h("div", { class: "kpi-value" }, formatBytes(cacheInfo.bytes)),
          h(
            "p",
            { class: "kpi-sub" },
            `${cacheInfo.files ?? 0} 个文件 · ${cacheInfo.memory_entries ?? 0} 条内存索引`,
          ),
          createInlineConfirmButton({
            label: cacheCtrl.clearing ? "清理中…" : "清理全部缓存",
            confirmLabel: "确认删除",
            variant: "ghost",
            size: "sm",
            onConfirm: () => cache.clearAll(),
          }),
        ),
      ),
    );

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
            h("h2", { class: "surface-title" }, "已接入平台矩阵"),
            h("p", { class: "surface-desc" }, "点击任意平台可直接前往启停开关与参数配置"),
          ),
          h(
            "button",
            {
              type: "button",
              class: "btn btn-ghost btn-sm",
              onclick: () => store.refreshOverview(true),
            },
            icon("refresh", 14),
            "刷新状态",
          ),
        ),
        h(
          "div",
          { class: "chip-cloud" },
          platforms.map((p) =>
            h(
              "button",
              {
                type: "button",
                class: `status-chip ${p.enabled ? "is-on" : "is-off"}`,
                title: p.description || p.label,
                onclick: () => navigate("platforms"),
              },
              h("span", { class: "chip-dot" }),
              h("span", null, p.label || p.name),
              p.external ? h("span", { class: "chip-tag" }, "联动") : null,
            ),
          ),
        ),
      ),
    );

    const urlInput = h("input", {
      type: "url",
      class: "ctrl-input",
      placeholder: "输入 http:// 或 https:// 分享链接测试解析链路",
      oninput: (e) => debug.setUrl(e.target.value),
      onkeydown: (e) => {
        if (e.key === "Enter" && !dbg.running) debug.runProbe();
      },
    });
    urlInput.value = dbg.url;

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
            h("h2", { class: "surface-title" }, "链接链路快速诊断"),
            h(
              "p",
              { class: "surface-desc" },
              store.scope
                ? `当前将按「${store.scopeLabel}」分群配置模拟解析与节点编排（只读，不发消息）`
                : "定位解析失败、媒体跳过或卡片渲染问题（只读，不发消息）",
            ),
          ),
        ),
        h(
          "div",
          { class: "probe-bar" },
          urlInput,
          h(
            "button",
            {
              type: "button",
              class: "btn btn-primary",
              disabled: dbg.running,
              onclick: () => debug.runProbe(),
            },
            dbg.running ? "诊断中…" : "开始诊断",
          ),
        ),
        h(
          "div",
          { class: "probe-opts" },
          h(
            "div",
            { class: "probe-checks" },
            h(
              "label",
              { class: "check-inline" },
              h("input", {
                type: "checkbox",
                checked: dbg.downloadMedia,
                onchange: (e) => debug.setDownloadMedia(Boolean(e.target.checked)),
              }),
              h("span", null, "测试下载媒体"),
            ),
            h(
              "label",
              { class: "check-inline" },
              h("input", {
                type: "checkbox",
                checked: dbg.renderCard,
                onchange: (e) => debug.setRenderCard(Boolean(e.target.checked)),
              }),
              h("span", null, "测试卡片生成"),
            ),
          ),
          h(
            "div",
            { class: "probe-samples" },
            QUICK_URLS.map((s) =>
              h(
                "button",
                {
                  type: "button",
                  class: "btn btn-ghost btn-sm",
                  onclick: () => {
                    debug.setUrl(s.url);
                    render();
                  },
                },
                s.label,
              ),
            ),
          ),
        ),
        renderProbeOutput(),
      ),
    );
    swapContent(root, sections);
  }

  render();
  return { element: root, sync: render };
}
