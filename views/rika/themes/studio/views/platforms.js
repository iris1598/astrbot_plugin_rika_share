import { clear, h, swapContent, valuesEqual } from "../../../core/dom.js";
import { buildControlRow } from "../widgets.js";

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

export function createStudioPlatformsView(appCtx) {
  const { store, bili } = appCtx;
  const root = h("div", { class: "page-stack" });
  const biliBoxHost = h("div", { class: "bili-box-host" });
  let filterText = "";
  const revealed = new Set();

  function renderBiliStatusBox() {
    const state = bili.getState();
    const info = state.bili || {};
    const qrSession = state.qrSession;
    const statusTone = !info.has_cookie
      ? "neutral"
      : info.valid === true
        ? "ok"
        : info.valid === false
          ? "err"
          : "warn";
    const statusLabel = !info.has_cookie
      ? "未登录"
      : info.valid === true
        ? "Cookie 有效"
        : info.valid === false
          ? "已失效"
          : "待检测";

    const infoBits = [];
    if (info.username) {
      infoBits.push(`${info.username} (UID ${info.uid || 0})`);
    } else if (info.has_cookie) {
      infoBits.push("已读取 Cookie，点击右侧按钮可验证用户信息");
    } else {
      infoBits.push("未配置 B站 Cookie，高画质视频与部分图文建议扫码登录");
    }
    if (info.error && info.valid === false) {
      infoBits.push(`异常：${info.error}`);
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
            info.vip ? h("span", { class: "pill pill-info" }, "大会员") : null,
            info.has_cookie
              ? h(
                  "span",
                  { class: `pill ${info.refreshable ? "pill-ok" : "pill-neutral"}` },
                  info.refreshable ? "自动续期就绪" : "普通 Cookie",
                )
              : null,
            h(
              "span",
              { class: "pill pill-neutral" },
              info.monitor_running ? "监控运行中" : "监控未运行",
            ),
          ),
          h("p", { class: "setting-hint" }, infoBits.join(" · ")),
          info.last_check_time
            ? h("p", { class: "bili-check-time" }, `上次检测：${info.last_check_time}`)
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
              disabled: state.busyQr,
              onclick: () => bili.startQrLogin(),
            },
            state.busyQr ? "获取二维码…" : qrSession ? "刷新二维码" : "扫码登录 B站",
          ),
          h(
            "button",
            {
              type: "button",
              class: "btn btn-soft btn-sm",
              disabled: state.busyCheck,
              onclick: () => bili.checkCookie(),
            },
            state.busyCheck ? "检测中…" : "立即检测",
          ),
          h(
            "button",
            {
              type: "button",
              class: "btn btn-ghost btn-sm",
              onclick: () => bili.refreshStatus(),
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
                      disabled: state.busyQr,
                      onclick: () => bili.startQrLogin(),
                    },
                    "重新获取二维码",
                  )
                : null,
              h(
                "button",
                {
                  type: "button",
                  class: "btn btn-ghost btn-sm",
                  onclick: () => bili.cancelQrLogin(),
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

  function syncBiliBox() {
    swapContent(biliBoxHost, [renderBiliStatusBox()]);
  }

  function render() {
    const map = store.itemMap();
    const platforms = store.meta?.platforms || [];
    const showKey = Boolean(store.showDevKeys);
    const sections = [];

    const gridEl = h("div", { class: "platform-cards" });
    const platTagHost = h("span", { class: "setting-label-tags" });
    const platRevertHost = h("span", { class: "setting-label-tags" });

    const syncPlatformScopeTags = () => {
      const isGroup = Boolean(store.scope);
      const platPendingUnset = Boolean(store.pendingUnset?.has("DISABLED_PLATFORMS"));
      const platHasOverride =
        isGroup && Boolean(store.overrideKeys?.has("DISABLED_PLATFORMS")) && !platPendingUnset;
      const platDirty =
        platPendingUnset ||
        !valuesEqual(store.draft.DISABLED_PLATFORMS, store.meta?.values?.DISABLED_PLATFORMS);

      clear(platTagHost);
      clear(platRevertHost);
      if (isGroup) {
        platTagHost.appendChild(
          platHasOverride
            ? h("span", { class: "pill pill-info" }, "本群独立")
            : h("span", { class: "pill" }, "继承全局"),
        );
      }
      if (platDirty) {
        platTagHost.appendChild(
          h("span", { class: "pill pill-warn" }, platPendingUnset ? "将恢复继承" : "待保存"),
        );
      }
      if (isGroup && (platHasOverride || platPendingUnset || platDirty)) {
        platRevertHost.appendChild(
          h(
            "button",
            {
              type: "button",
              class: "btn btn-ghost btn-sm",
              onclick: () => store.revertKeyToInherit("DISABLED_PLATFORMS"),
            },
            "恢复继承",
          ),
        );
      }
    };

    const renderGrid = () => {
      const disabled = store.disabledPlatformSet();
      const kw = filterText.trim().toLowerCase();
      const filtered = platforms.filter((p) => {
        if (!kw) return true;
        return `${p.name} ${p.label} ${p.description || ""}`.toLowerCase().includes(kw);
      });
      const cards = filtered.map((p) => {
        const enabled = !disabled.has(p.name.toLowerCase());
        return h(
          "button",
          {
            type: "button",
            class: `platform-tile ${enabled ? "is-on" : "is-off"}`,
            onclick: () => {
              store.togglePlatform(p.name);
              renderGrid();
              syncPlatformScopeTags();
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
        );
      });
      swapContent(gridEl, cards);
    };

    syncPlatformScopeTags();
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

    const isGroup = Boolean(store.scope);

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
            h(
              "div",
              { class: "setting-label-row" },
              h("h2", { class: "surface-title" }, "支持平台开关"),
              platTagHost,
            ),
            h("p", { class: "surface-desc" }, "点击平台卡片即切换启停；外部联动插件安装后会自动出现在此列表"),
          ),
          h(
            "div",
            { class: "btn-group" },
            platRevertHost,
            h(
              "button",
              {
                type: "button",
                class: "btn btn-ghost btn-sm",
                onclick: () => {
                  store.setAllPlatformsEnabled(true);
                  renderGrid();
                  syncPlatformScopeTags();
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
                  store.setAllPlatformsEnabled(false);
                  renderGrid();
                  syncPlatformScopeTags();
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

    syncBiliBox();
    const accountItems = ACCOUNT_KEYS.map((k) => map.get(k)).filter(Boolean);
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
            h("h2", { class: "surface-title" }, "B站扫码登录与账号凭据"),
            h("p", { class: "surface-desc" }, "支持直接在面板扫码授权 B站并加密落盘（含自动续期凭据），下方也可手动管理 B站与小红书 Cookie"),
          ),
          isGroup ? h("span", { class: "pill" }, "账号凭据全局共用") : null,
        ),
        biliBoxHost,
        accountItems.length > 0
          ? h(
              "div",
              { class: "settings-list" },
              accountItems.map((it) => buildControlRow(store, it, { showKey, secretState: revealed })),
            )
          : null,
      ),
    );

    const transportItems = TRANSPORT_KEYS.map((k) => map.get(k)).filter(Boolean);
    if (transportItems.length > 0) {
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
              h("h2", { class: "surface-title" }, "画质、代理与发送策略"),
              h("p", { class: "surface-desc" }, "控制视频最大时长、编码偏好、Twitter 反代及 OneBot 合并转发分批上限"),
            ),
            isGroup ? h("span", { class: "pill" }, "转发上限可分群，画质与代理仅全局") : null,
          ),
          h(
            "div",
            { class: "settings-list two-col" },
            transportItems.map((it) => buildControlRow(store, it, { showKey })),
          ),
        ),
      );
    }
    swapContent(root, sections);
  }

  function onActivated() {
    bili.refreshStatus();
  }

  render();
  return { element: root, sync: render, syncBiliBox, onActivated };
}
