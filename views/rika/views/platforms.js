import { buildControlRow, clear, h } from "../ui.js";

const ACCOUNT_KEYS = [
  "BILI_CK",
  "XHS_CK",
  "BILI_COOKIE_MONITOR_ENABLED",
  "BILI_COOKIE_CHECK_INTERVAL",
];

const QR_STATE_META = {
  waiting: { label: "等待扫码", tone: "info" },
  scanned: { label: "已扫码待确认", tone: "warn" },
  success: { label: "登录成功", tone: "ok" },
  expired: { label: "二维码已过期", tone: "err" },
  error: { label: "登录异常", tone: "err" },
  idle: { label: "未开启", tone: "neutral" },
};

const TRANSPORT_KEYS = [
  "BILI_QUALITY",
  "BILI_CODEC",
  "VIDEO_DURATION_MAXIMUM",
  "DOUYIN_LIVE_PHOTO_ENABLED",
  "TWITTER_MEDIA_PROXY_ENABLED",
  "TWITTER_MEDIA_PROXY_BASE",
  "FORWARD_MAX_NODES",
  "FORWARD_MAX_BATCH_MB",
];

function parseDisabledSet(raw) {
  return new Set(
    String(raw || "")
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean),
  );
}

export function createPlatformsView(store) {
  const root = h("div", { class: "page-stack" });
  let filterText = "";
  const revealed = new Set();
  let busyCheck = false;
  let busyQr = false;
  let qrSession = null;
  let pollTimer = null;

  function stopPolling() {
    if (pollTimer) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function startPolling() {
    stopPolling();
    if (!qrSession?.active || !qrSession?.qrcode_key) return;
    pollTimer = window.setInterval(() => {
      pollBiliStatus();
    }, 2500);
  }

  function applyBiliResponse(res) {
    if (res?.bili) {
      store.overview = { ...(store.overview || {}), bili: res.bili };
      store.views.workbench?.sync?.();
    }
  }

  async function refreshBiliStatus() {
    try {
      const res = await store.bridge.apiGet("bili/status", {});
      applyBiliResponse(res);
      if (res?.qr && res.qr.active) {
        qrSession = { ...(qrSession || {}), ...res.qr };
        startPolling();
      }
      render();
    } catch (err) {
      store.toast(`获取B站状态失败：${err.message || err}`, "err");
    }
  }

  async function checkBiliCookie() {
    if (busyCheck) return;
    busyCheck = true;
    render();
    try {
      const res = await store.bridge.apiPost("bili/check", {});
      applyBiliResponse(res);
      if (res?.checked === false) {
        store.toast(res.message || "尚未配置B站 Cookie", "warn");
      } else if (res?.result?.valid) {
        store.toast(`B站 Cookie 有效（${res.result.username || "已登录"}）`, "ok");
      } else {
        store.toast(`B站 Cookie 已失效：${res?.result?.error || "请重新扫码"}`, "err");
      }
    } catch (err) {
      store.toast(`检测失败：${err.message || err}`, "err");
    } finally {
      busyCheck = false;
      render();
    }
  }

  async function startQrLogin() {
    if (busyQr) return;
    busyQr = true;
    render();
    try {
      const res = await store.bridge.apiPost("bili/login", { action: "start" });
      applyBiliResponse(res);
      qrSession = res?.qr || null;
      if (qrSession?.active) {
        startPolling();
      }
    } catch (err) {
      store.toast(`获取二维码失败：${err.message || err}`, "err");
    } finally {
      busyQr = false;
      render();
    }
  }

  async function cancelQrLogin() {
    stopPolling();
    qrSession = null;
    render();
    try {
      const res = await store.bridge.apiPost("bili/login", { action: "cancel" });
      applyBiliResponse(res);
    } catch {
      // 关闭面板不阻塞前端交互
    }
  }

  async function pollBiliStatus() {
    if (!qrSession?.qrcode_key || store.activeTab !== "platforms") return;
    try {
      const res = await store.bridge.apiGet("bili/status", {
        qrcode_key: qrSession.qrcode_key,
      });
      applyBiliResponse(res);
      if (res?.qr) {
        qrSession = { ...qrSession, ...res.qr };
        if (!res.qr.active) {
          stopPolling();
          if (res.qr.state === "success") {
            store.toast(res.qr.message || "B站扫码登录成功！", "ok", 4200);
            store.refreshOverview(false);
          } else if (res.qr.state === "expired") {
            store.toast("登录二维码已过期，请点击刷新", "warn");
          }
        }
        render();
      }
    } catch {
      // 网络短暂抖动等待下次轮询
    }
  }

  function renderBiliStatusBox() {
    const bili = store.overview?.bili || {};
    const statusTone = !bili.has_cookie
      ? "neutral"
      : bili.valid === true
        ? "ok"
        : bili.valid === false
          ? "err"
          : "warn";
    const statusLabel = !bili.has_cookie
      ? "未登录"
      : bili.valid === true
        ? "Cookie 有效"
        : bili.valid === false
          ? "已失效"
          : "待检测";

    const infoBits = [];
    if (bili.username) {
      infoBits.push(`${bili.username} (UID ${bili.uid || 0})`);
    } else if (bili.has_cookie) {
      infoBits.push("已读取 Cookie，点击右侧按钮可验证用户信息");
    } else {
      infoBits.push("未配置 B站 Cookie，高画质视频与部分图文建议扫码登录");
    }
    if (bili.error && bili.valid === false) {
      infoBits.push(`异常：${bili.error}`);
    }

    const box = h(
      "div",
      { class: "bili-status-card" },
      h(
        "div",
        { class: "bili-status-top" },
        h(
          "div",
          { class: "bili-status-info" },
          h(
            "div",
            { class: "bili-badges-row" },
            h("strong", null, "B站账号登录态"),
            h("span", { class: `pill pill-${statusTone}` }, statusLabel),
            bili.vip ? h("span", { class: "pill pill-info" }, "大会员") : null,
            bili.has_cookie
              ? h(
                  "span",
                  { class: `pill ${bili.refreshable ? "pill-ok" : "pill-neutral"}` },
                  bili.refreshable ? "自动续期就绪" : "普通 Cookie",
                )
              : null,
            h(
              "span",
              { class: "pill pill-neutral" },
              bili.monitor_running ? "监控运行中" : "监控未运行",
            ),
          ),
          h("p", { class: "setting-hint" }, infoBits.join(" · ")),
          bili.last_check_time
            ? h("p", { class: "bili-check-time" }, `上次检测：${bili.last_check_time}`)
            : null,
        ),
        h(
          "div",
          { class: "btn-group" },
          h(
            "button",
            {
              type: "button",
              class: "btn btn-primary btn-sm",
              disabled: busyQr,
              onclick: startQrLogin,
            },
            busyQr ? "获取二维码…" : qrSession ? "刷新二维码" : "扫码登录 B站",
          ),
          h(
            "button",
            {
              type: "button",
              class: "btn btn-soft btn-sm",
              disabled: busyCheck,
              onclick: checkBiliCookie,
            },
            busyCheck ? "检测中…" : "立即检测",
          ),
          h(
            "button",
            {
              type: "button",
              class: "btn btn-ghost btn-sm",
              onclick: refreshBiliStatus,
            },
            "刷新状态",
          ),
        ),
      ),
    );

    if (qrSession) {
      const qrMeta = QR_STATE_META[qrSession.state] || QR_STATE_META.waiting;
      box.appendChild(
        h(
          "div",
          { class: "bili-qr-panel" },
          qrSession.qr_image
            ? h(
                "div",
                { class: "bili-qr-img-wrap" },
                h("img", {
                  src: qrSession.qr_image,
                  alt: "B站扫码登录二维码",
                  class: "bili-qr-img",
                }),
              )
            : null,
          h(
            "div",
            { class: "bili-qr-meta" },
            h(
              "div",
              { class: "bili-badges-row" },
              h("span", { class: `pill pill-${qrMeta.tone}` }, qrMeta.label),
              qrSession.active && qrSession.remaining_seconds > 0
                ? h("span", { class: "pill pill-neutral" }, `剩余 ${qrSession.remaining_seconds}s`)
                : null,
            ),
            h("p", { class: "bili-qr-msg" }, qrSession.message || "请使用手机 B站 App 扫描二维码"),
            h(
              "div",
              { class: "btn-group" },
              qrSession.state === "expired" || qrSession.state === "error"
                ? h(
                    "button",
                    {
                      type: "button",
                      class: "btn btn-soft btn-sm",
                      disabled: busyQr,
                      onclick: startQrLogin,
                    },
                    "重新获取二维码",
                  )
                : null,
              h(
                "button",
                {
                  type: "button",
                  class: "btn btn-ghost btn-sm",
                  onclick: cancelQrLogin,
                },
                qrSession.state === "success" ? "完成并收起" : "取消扫码",
              ),
            ),
          ),
        ),
      );
    }
    return box;
  }

  function itemsMap() {
    const map = new Map();
    for (const item of store.meta?.items || []) map.set(item.key, item);
    return map;
  }

  function render() {
    clear(root);
    const map = itemsMap();
    const platforms = store.meta?.platforms || [];
    const showKey = Boolean(store.showDevKeys);

    // 1. 平台开关矩阵
    const gridEl = h("div", { class: "platform-cards" });

    const renderGrid = () => {
      clear(gridEl);
      const disabled = parseDisabledSet(store.draft.DISABLED_PLATFORMS);
      const kw = filterText.trim().toLowerCase();
      const filtered = platforms.filter((p) => {
        if (!kw) return true;
        return `${p.name} ${p.label} ${p.description || ""}`.toLowerCase().includes(kw);
      });
      for (const p of filtered) {
        const enabled = !disabled.has(p.name.toLowerCase());
        gridEl.appendChild(
          h(
            "button",
            {
              type: "button",
              class: `platform-tile ${enabled ? "is-on" : "is-off"}`,
              onclick: () => {
                const next = parseDisabledSet(store.draft.DISABLED_PLATFORMS);
                const key = p.name.toLowerCase();
                if (next.has(key)) next.delete(key);
                else next.add(key);
                store.setDraftValue("DISABLED_PLATFORMS", Array.from(next).sort().join(", "));
                renderGrid();
              },
            },
            h(
              "div",
              { class: "platform-tile-top" },
              h("span", { class: "platform-tile-name" }, p.label || p.name),
              h(
                "span",
                { class: "platform-tile-tags" },
                p.external ? h("span", { class: "pill pill-info" }, "外部") : null,
                h("span", { class: `pill ${enabled ? "pill-ok" : "pill-neutral"}` }, enabled ? "开启" : "停用"),
              ),
            ),
            p.description ? h("p", { class: "platform-tile-desc" }, p.description) : null,
          ),
        );
      }
    };

    renderGrid();

    const searchInput = h("input", {
      type: "search",
      class: "ctrl-input ctrl-sm",
      placeholder: "筛选平台名称或能力…",
      oninput: (e) => {
        filterText = e.target.value;
        renderGrid();
      },
    });
    searchInput.value = filterText;

    root.appendChild(
      h(
        "section",
        { class: "surface-panel" },
        h(
          "div",
          { class: "surface-head" },
          h(
            "div",
            null,
            h("h2", { class: "surface-title" }, "支持平台开关"),
            h("p", { class: "surface-desc" }, "点击平台卡片即切换启停；外部联动插件安装后会自动出现在此列表"),
          ),
          h(
            "div",
            { class: "btn-group" },
            h(
              "button",
              {
                type: "button",
                class: "btn btn-ghost btn-sm",
                onclick: () => {
                  store.setDraftValue("DISABLED_PLATFORMS", "");
                  renderGrid();
                },
              },
              "全部开启",
            ),
            h(
              "button",
              {
                type: "button",
                class: "btn btn-ghost btn-sm",
                onclick: () => {
                  store.setDraftValue(
                    "DISABLED_PLATFORMS",
                    platforms.map((p) => p.name.toLowerCase()).join(", "),
                  );
                  renderGrid();
                },
              },
              "全部关闭",
            ),
          ),
        ),
        h("div", { class: "filter-bar" }, searchInput),
        gridEl,
      ),
    );

    // 2. 统一账号凭据与扫码监控（B站扫码登录 + B站/小红书 Cookie + 失效监控）
    const accountItems = ACCOUNT_KEYS.map((k) => map.get(k)).filter(Boolean);
    root.appendChild(
      h(
        "section",
        { class: "surface-panel" },
        h(
          "div",
          { class: "surface-head" },
          h(
            "div",
            null,
            h("h2", { class: "surface-title" }, "B站扫码登录与账号凭据"),
            h("p", { class: "surface-desc" }, "支持直接在面板扫码授权 B站并加密落盘（含自动续期凭据），下方也可手动管理 B站与小红书 Cookie"),
          ),
        ),
        renderBiliStatusBox(),
        accountItems.length > 0
          ? h(
              "div",
              { class: "settings-list" },
              accountItems.map((it) =>
                buildControlRow(store, it, {
                  showKey,
                  secretState: revealed,
                  onAfterChange: render,
                }),
              ),
            )
          : null,
      ),
    );

    // 3. 下载清晰度、代理与转发上限
    const transportItems = TRANSPORT_KEYS.map((k) => map.get(k)).filter(Boolean);
    if (transportItems.length > 0) {
      root.appendChild(
        h(
          "section",
          { class: "surface-panel" },
          h(
            "div",
            { class: "surface-head" },
            h(
              "div",
              null,
              h("h2", { class: "surface-title" }, "画质、代理与发送策略"),
              h("p", { class: "surface-desc" }, "控制视频最大时长、编码偏好、Twitter 反代及 OneBot 合并转发分批上限"),
            ),
          ),
          h(
            "div",
            { class: "settings-list two-col" },
            transportItems.map((it) =>
              buildControlRow(store, it, {
                showKey,
                onAfterChange: render,
              }),
            ),
          ),
        ),
      );
    }
  }

  function onActivated() {
    refreshBiliStatus();
    if (qrSession?.active) startPolling();
  }

  render();
  return { element: root, sync: render, onActivated };
}
