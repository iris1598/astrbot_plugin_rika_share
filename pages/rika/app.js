/* 莉卡解析 · 插件页面入口
 *
 * 职责：等 bridge 就绪 → 取配置元数据 → 渲染左侧导航 → 按导航切换视图。
 * 业务都在 views/ 下（设置 / 链接调试），本文件保持「框架层」的轻量。
 */

import { h, clear } from "./ui.js";
import { PLATFORM_VIEW, createSettingsView } from "./views/settings.js";
import { createDebugView } from "./views/debug.js";

const bridge = window.AstrBotPluginPage;

/** 统一的接口调用封装：后端返回普通 JSON 时 bridge 直接给出业务对象。 */
export const api = {
  get(endpoint, params) {
    return bridge.apiGet(endpoint, params);
  },
  post(endpoint, body) {
    return bridge.apiPost(endpoint, body);
  },
  download(endpoint, params, filename) {
    return bridge.download(endpoint, params, filename);
  },
};

/** 视图工厂：导航项的 view 字段对应这里的键。 */
const VIEW_FACTORIES = {
  settings: createSettingsView,
  debug: createDebugView,
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
/** 链接调试：输入链接跑一遍完整流程并导出日志。 */
const ICON_DEBUG = svg(
  '<path d="M8 6h8l-1 4 4 9a1 1 0 0 1-.9 1.4H5.9A1 1 0 0 1 5 19l4-9z"/>' +
    '<path d="M9.5 14h5"/>',
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
  /** 当前导航项 {view, key, label, title, sub} */
  current: null,
  /** view 名 -> { instance, holder }，挂载后一直留着（切走不丢未保存的草稿） */
  views: new Map(),
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

/* ---------------- 导航 ---------------- */

/** 导航项 = 设置视图的若干入口 + 链接调试。 */
function navEntries(settingsView) {
  const entries = [
    { view: "settings", key: ALL, label: "全部设置", title: "设置", sub: "全部配置项，保存后立即生效", icon: ICON_ALL },
  ];
  // 解析器开关固定排在分组前面（平台清单动态，没有平台时不显示这一项）
  if (settingsView.hasPlatforms()) {
    entries.push({
      view: "settings",
      key: PLATFORM_VIEW,
      label: "解析器开关",
      title: "解析器开关",
      sub: "一键启用 / 关闭各平台解析器",
      icon: ICON_PLATFORMS,
    });
  }
  for (const name of settingsView.groupNames()) {
    entries.push({
      view: "settings",
      key: name,
      label: name,
      title: name,
      sub: "该分组的配置项，保存后立即生效",
      icon: GROUP_ICONS[name] || ICON_DEFAULT,
    });
  }
  entries.push({
    view: "debug",
    key: "debug",
    label: "链接调试",
    title: "链接调试",
    sub: "输入链接跑一遍完整解析流程，导出可下载的日志",
    icon: ICON_DEBUG,
  });
  return entries;
}

function buildNav(entries) {
  const nav = document.getElementById("rail-nav");
  clear(nav);
  state.entries = entries;

  for (const entry of entries) {
    nav.appendChild(
      h(
        "button",
        {
          class: "rail-item",
          type: "button",
          dataset: { index: String(entries.indexOf(entry)) },
          title: entry.label,
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
    if (!button) return;
    const entry = entries[Number(button.dataset.index)];
    if (!entry || entry === state.current) return;
    selectEntry(entry);
  };
}

function markActive(entry) {
  const items = document.querySelectorAll(".rail-item");
  items.forEach((item) => {
    item.classList.toggle("is-active", state.entries[Number(item.dataset.index)] === entry);
  });
}

/** 取出（必要时创建并挂载）某个视图；每个视图一个 holder，切换靠 hidden。 */
async function ensureView(name) {
  const existing = state.views.get(name);
  if (existing) return existing;

  const holder = h("div", { class: "view" });
  state.body.appendChild(holder);
  const instance = VIEW_FACTORIES[name](ctx);
  const slot = { instance, holder };
  state.views.set(name, slot);
  try {
    await instance.mount(holder);
  } catch (error) {
    console.error(`视图 ${name} 渲染失败`, error);
    clear(holder);
    holder.appendChild(h("div", { class: "empty", text: `页面渲染失败：${error.message || error}` }));
    throw error;
  }
  return slot;
}

async function selectEntry(entry) {
  let slot;
  try {
    slot = await ensureView(entry.view);
  } catch {
    return; // 已渲染失败提示，不再切标题
  }
  for (const [name, item] of state.views) {
    item.holder.hidden = name !== entry.view;
  }
  state.current = entry;
  markActive(entry);
  state.title.textContent = entry.title;
  state.sub.textContent = entry.sub;
  ctx.setHead("");

  // 设置视图还要切到具体的分组 / 解析器开关
  if (entry.view === "settings" && typeof slot.instance.showGroup === "function") {
    slot.instance.showGroup(entry.key);
  }
}

function bindReload() {
  state.reloadButton.addEventListener("click", async () => {
    state.reloadButton.disabled = true;
    state.reloadButton.textContent = "刷新中…";
    try {
      const slot = state.current && state.views.get(state.current.view);
      if (slot && typeof slot.instance.refresh === "function") await slot.instance.refresh();
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

  // 导航项要按后端的分组 / 平台清单生成，所以设置视图先实例化并 adopt，
  // 再建导航；调试视图等第一次点进去时再懒挂载。
  const settings = createSettingsView(ctx);
  try {
    settings.adopt(await api.get("config"));
  } catch (error) {
    console.error("读取配置失败", error);
    fail(`读取配置失败：${error.message || error}`);
    return;
  }

  const holder = h("div", { class: "view", hidden: true });
  state.body.appendChild(holder);
  state.views.set("settings", { instance: settings, holder });
  try {
    await settings.mount(holder);
  } catch (error) {
    console.error("设置页渲染失败", error);
    fail(`页面渲染失败：${error.message || error}`);
    return;
  }

  buildNav(navEntries(settings));
  ctx.setConnection(true, "已连接");
  await selectEntry(state.entries[0]);
}

boot();
