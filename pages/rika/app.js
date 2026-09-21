/* 莉卡解析 · 插件页面入口
 *
 * 职责：等 bridge 就绪 → 取配置元数据 → 渲染左侧分组导航 → 挂载设置视图。
 * 表单与保存逻辑都在 views/settings.js，本文件保持「框架层」的轻量。
 */

import { h, clear } from "./ui.js";
import { PLATFORM_VIEW, createSettingsView } from "./views/settings.js";

const bridge = window.AstrBotPluginPage;

/** 统一的接口调用封装：后端返回普通 JSON 时 bridge 直接给出业务对象。 */
export const api = {
  get(endpoint, params) {
    return bridge.apiGet(endpoint, params);
  },
  post(endpoint, body) {
    return bridge.apiPost(endpoint, body);
  },
};

const ALL = "__all__";

/* ---------------- 分组导航图标 ---------------- */

function svg(paths) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
    stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`;
}

const ICON_ALL = svg(
  '<rect x="3" y="3" width="8" height="10" rx="2"/><rect x="13" y="3" width="8" height="6" rx="2"/>' +
    '<rect x="13" y="11" width="8" height="10" rx="2"/><rect x="3" y="15" width="8" height="6" rx="2"/>',
);
/** 解析器开关：平台清单来自适配器注册表，新增平台会自动出现在这一页。 */
const ICON_PLATFORMS = svg(
  '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/>' +
    '<path d="M7 7.5h.01"/><path d="M7 16.5h.01"/>',
);
const ICON_DEFAULT = svg(
  '<circle cx="12" cy="12" r="3"/>' +
    '<path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0-.3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8 2.8l.1.1a1.7 1.7 0 0 0-.3 1.9v.1a1.7 1.7 0 0 0 1.5 1h.1a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
);

/** 分组名 -> 图标。分组由后端 CONFIG_META 决定，这里只做展示层的点缀。 */
const GROUP_ICONS = {
  "平台设置": svg(
    '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/>' +
      '<path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
  ),
  "Twitter 设置": svg(
    '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/>' +
      '<path d="M12 3c2.5 2.4 3.8 5.4 3.8 9S14.5 18.6 12 21c-2.5-2.4-3.8-5.4-3.8-9S9.5 5.4 12 3z"/>',
  ),
  "B站设置": svg(
    '<rect x="2" y="7" width="20" height="13" rx="2"/><path d="M8 3l4 4 4-4"/>',
  ),
  "缓存设置": svg(
    '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/>' +
      '<path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  ),
  "解析图片渲染": svg(
    '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/>' +
      '<path d="M21 15l-5-5L5 21"/>',
  ),
  "Cloudflare 基础设置": svg(
    '<path d="M17.5 19a4.5 4.5 0 0 0 .5-8.98A6 6 0 0 0 6.1 11.2A3.5 3.5 0 0 0 6.5 19z"/>',
  ),
  "Cloudflare 截图设置": svg(
    '<path d="M3 8.5A2.5 2.5 0 0 1 5.5 6h1.7A2 2 0 0 1 9 4.7h6A2.5 2.5 0 0 1 17.5 7h1A2.5 2.5 0 0 1 21 9.5V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>' +
      '<circle cx="12" cy="13" r="3.2"/>',
  ),
  "调试设置": svg(
    '<path d="M4 6h10"/><path d="M4 12h10"/><path d="M4 18h10"/>' +
      '<circle cx="18" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="20" cy="18" r="2"/>',
  ),
};

/* ---------------- 界面状态 ---------------- */

const state = {
  view: null,
  group: ALL,
  title: document.getElementById("view-title"),
  sub: document.getElementById("view-sub"),
  body: document.getElementById("stage-body"),
  pill: document.getElementById("head-pill"),
  dot: document.getElementById("rail-dot"),
  status: document.getElementById("rail-status"),
  version: document.getElementById("brand-version"),
  reloadButton: document.getElementById("btn-reload"),
};

const ctx = {
  api,
  setHead(text, kind = "") {
    if (!text) {
      state.pill.hidden = true;
      state.pill.textContent = "";
      state.pill.className = "pill";
      return;
    }
    state.pill.hidden = false;
    state.pill.textContent = text;
    state.pill.className = `pill ${kind}`.trim();
  },
  setVersion(text) {
    if (text) state.version.textContent = text;
  },
  setConnection(ok, text) {
    state.dot.className = `dot ${ok ? "is-ok" : "is-err"}`;
    state.status.textContent = text;
  },
};

/** 非分组视图的标题与副标题；其余分组直接用分组名。 */
const VIEW_LABELS = {
  [ALL]: { title: "设置", sub: "全部配置项，保存后立即生效" },
  [PLATFORM_VIEW]: { title: "解析器开关", sub: "一键启用 / 关闭各平台解析器" },
};

/* ---------------- 导航 ---------------- */

function buildNav(groups, hasPlatforms) {
  const nav = document.getElementById("rail-nav");
  clear(nav);

  const entries = [{ name: ALL, label: "全部设置", icon: ICON_ALL }];
  // 解析器开关固定排在分组前面（平台清单动态，没有平台时不显示这一项）
  if (hasPlatforms) {
    entries.push({ name: PLATFORM_VIEW, label: "解析器开关", icon: ICON_PLATFORMS });
  }
  entries.push(
    ...groups.map((name) => ({
      name,
      label: name,
      icon: GROUP_ICONS[name] || ICON_DEFAULT,
    })),
  );

  for (const entry of entries) {
    nav.appendChild(
      h(
        "button",
        {
          class: `rail-item${entry.name === state.group ? " is-active" : ""}`,
          type: "button",
          dataset: { group: entry.name },
        },
        [
          h("span", { class: "rail-icon", html: entry.icon, "aria-hidden": "true" }),
          h("span", { class: "rail-label", text: entry.label }),
        ],
      ),
    );
  }

  nav.onclick = (event) => {
    const button = event.target.closest(".rail-item");
    if (!button || button.dataset.group === state.group) return;
    selectGroup(button.dataset.group);
  };
}

function selectGroup(name) {
  state.group = name;
  for (const item of document.querySelectorAll(".rail-item")) {
    item.classList.toggle("is-active", item.dataset.group === name);
  }
  const labels = VIEW_LABELS[name] || {
    title: name,
    sub: "该分组的配置项，保存后立即生效",
  };
  state.title.textContent = labels.title;
  state.sub.textContent = labels.sub;
  if (state.view) state.view.showGroup(name);
}

function bindReload() {
  state.reloadButton.addEventListener("click", async () => {
    state.reloadButton.disabled = true;
    state.reloadButton.textContent = "刷新中…";
    try {
      if (state.view) await state.view.refresh();
    } finally {
      state.reloadButton.disabled = false;
      state.reloadButton.textContent = "刷新";
    }
  });
}

/* ---------------- 启动 ---------------- */

function fail(message) {
  ctx.setConnection(false, "未连接");
  clear(state.body);
  state.body.appendChild(h("div", { class: "empty", text: message }));
}

async function boot() {
  bindReload();

  if (!bridge || typeof bridge.ready !== "function") {
    fail(
      "没有拿到 AstrBotPluginPage bridge。请确认插件已启用，并从插件详情页打开本页面。",
    );
    return;
  }

  try {
    await bridge.ready();
  } catch (error) {
    console.error("等待 bridge 上下文失败", error);
  }

  const view = createSettingsView(ctx);
  state.view = view;

  try {
    view.adopt(await api.get("config"));
  } catch (error) {
    console.error("读取配置失败", error);
    fail(`读取配置失败：${error.message || error}`);
    return;
  }

  buildNav(view.groupNames(), view.hasPlatforms());
  ctx.setConnection(true, "已连接");

  const holder = h("div", { class: "view" });
  state.body.appendChild(holder);
  try {
    await view.mount(holder);
  } catch (error) {
    console.error("设置页渲染失败", error);
    fail(`页面渲染失败：${error.message || error}`);
    return;
  }

  selectGroup(ALL);
}

boot();
