import * as dom from "./core/dom.js";
import * as nodeModel from "./core/node_model.js";
import { createAppStore } from "./core/store.js";
import {
  createBiliController,
  createCacheController,
  createDebugController,
  createPreviewController,
} from "./core/controllers.js";
import {
  DEFAULT_THEME_ID,
  activateTheme,
  getActiveThemeId,
  getTheme,
  installGlobalThemeApi,
  listThemes,
  notifyActiveThemeColorChange,
  notifyActiveThemeContextChange,
  registerDiscoveredManifests,
} from "./themes/registry.js";

installGlobalThemeApi();

// 预导入内置主题，保证无清单文件回退或本地离线环境同样可用
import studioTheme from "./themes/studio/index.js";
import glassCenterTheme from "./themes/glass-center/index.js";
import { registerTheme } from "./themes/registry.js";

registerTheme(studioTheme);
registerTheme(glassCenterTheme);

function resolveBridge() {
  const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
  if (!bridge) {
    throw new Error("未检测到 window.AstrBotPluginView，请在 AstrBot 控制台中打开插件页面");
  }
  return bridge;
}

async function boot() {
  const mountEl = document.getElementById("app");
  const toast = dom.createToaster();

  try {
    const bridge = resolveBridge();
    const ctx = await bridge.ready();

    const [configPayload, overviewPayload] = await Promise.all([
      bridge.apiGet("config", { scope: "" }),
      bridge.apiGet("overview", { scope: "" }).catch(() => null),
    ]);

    if (Array.isArray(configPayload?.webui_themes)) {
      registerDiscoveredManifests(configPayload.webui_themes);
    }

    const store = createAppStore({
      bridge,
      toast,
      context: ctx,
      configPayload,
      overviewPayload,
    });

    const bili = createBiliController(store);
    const preview = createPreviewController(store);
    const debug = createDebugController(store);
    const cache = createCacheController(store);

    const themeApi = {
      listThemes,
      getTheme,
      getActiveThemeId,
      DEFAULT_THEME_ID,
      registerTheme,
    };

    let mountingChain = Promise.resolve();

    function targetThemeId() {
      const configured = String(store.draft.WEBUI_THEME || DEFAULT_THEME_ID).trim().toLowerCase();
      return getTheme(configured)?.id || DEFAULT_THEME_ID;
    }

    function enqueueThemeMount(themeId) {
      mountingChain = mountingChain
        .then(async () => {
          const target = getTheme(themeId)?.id || DEFAULT_THEME_ID;
          if (target === getActiveThemeId() && mountEl.childNodes.length > 0) {
            return;
          }
          await activateTheme(target, mountEl, {
            store,
            bili,
            preview,
            debug,
            cache,
            nodeModel,
            dom,
            themes: themeApi,
            colorMode: store.draft.WEBUI_COLOR_MODE,
            systemIsDark: store.systemIsDark,
            setThemePreference(nextThemeId) {
              const id = String(nextThemeId || "").trim().toLowerCase();
              if (!id) return false;
              return store.setDraftValue("WEBUI_THEME", id);
            },
            setColorModePreference(nextMode) {
              return store.setDraftValue("WEBUI_COLOR_MODE", String(nextMode || "auto"));
            },
          });
        })
        .catch((err) => {
          console.error("[RikaWebUI] failed to mount theme:", err);
          toast(`切换网页主题失败：${err?.message || err}`, "err");
        });
      return mountingChain;
    }

    store.subscribe((ev) => {
      if (ev.type === "draft" && ev.key === "WEBUI_THEME") {
        const nextId = targetThemeId();
        if (nextId !== getActiveThemeId()) {
          enqueueThemeMount(nextId);
        }
      } else if (ev.type === "draft" && ev.key === "WEBUI_COLOR_MODE") {
        notifyActiveThemeColorChange({
          colorMode: store.draft.WEBUI_COLOR_MODE,
          systemIsDark: store.systemIsDark,
        });
      } else if (ev.type === "snapshot" || ev.type === "discard") {
        if (Array.isArray(store.meta?.webui_themes)) {
          registerDiscoveredManifests(store.meta.webui_themes);
        }
        const nextId = targetThemeId();
        if (nextId !== getActiveThemeId()) {
          enqueueThemeMount(nextId);
        } else {
          notifyActiveThemeColorChange({
            colorMode: store.draft.WEBUI_COLOR_MODE,
            systemIsDark: store.systemIsDark,
          });
        }
      } else if (ev.type === "context") {
        notifyActiveThemeColorChange({
          colorMode: store.draft.WEBUI_COLOR_MODE,
          systemIsDark: store.systemIsDark,
        });
        notifyActiveThemeContextChange(store.context);
      }
    });

    if (typeof bridge.onContext === "function") {
      bridge.onContext((nextCtx) => {
        store.updateContext(nextCtx);
      });
    }

    await enqueueThemeMount(targetThemeId());
  } catch (err) {
    dom.clear(mountEl);
    mountEl.appendChild(
      dom.h(
        "div",
        { class: "fatal-panel" },
        dom.h("h2", null, "控制中心启动失败"),
        dom.h("p", null, err?.message || String(err)),
        dom.h(
          "button",
          {
            type: "button",
            class: "fatal-retry-btn",
            onclick: () => window.location.reload(),
          },
          "刷新页面",
        ),
      ),
    );
  }
}

boot();
