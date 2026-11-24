/**
 * 网页整页主题（Full-Page Web Theme）注册引擎与生命周期宿主机。
 *
 * 每个网页主题都是一套完整独立的页面设计与前端应用：
 * - 自带完整的 DOM 骨架、导航逻辑、组件实现与隔离样式表（styles / css）；
 * - 切走主题时自动卸载组件、回收主题私有定时器/监听器并移除 <head> 样式标签，互不污染；
 * - 既支持后端从 `views/rika/themes/<id>/manifest.json` 自动发现并按需 import()，
 *   也支持第三方脚本通过 `window.RikaWebTheme.registerTheme(spec)` 在运行时注册。
 */

export const DEFAULT_THEME_ID = "studio";
export const VALID_COLOR_MODES = new Set(["auto", "light", "dark"]);

const _themes = new Map();
const _themeListeners = new Set();
let _activeHandle = null;
let _activeThemeId = "";
let _activeCleanups = [];
let _mountToken = 0;

function emitThemeListChange() {
  for (const fn of Array.from(_themeListeners)) {
    try {
      fn(listThemes());
    } catch (err) {
      console.error("[RikaWebUI] theme listener error:", err);
    }
  }
}

export function subscribeThemes(fn) {
  if (typeof fn !== "function") return () => {};
  _themeListeners.add(fn);
  return () => _themeListeners.delete(fn);
}

export function normalizeColorMode(mode) {
  const m = String(mode || "auto").trim().toLowerCase();
  return VALID_COLOR_MODES.has(m) ? m : "auto";
}

export function resolveColorMode(colorMode, systemIsDark = false) {
  const mode = normalizeColorMode(colorMode);
  const resolvedDark = mode === "auto" ? Boolean(systemIsDark) : mode === "dark";
  return {
    colorMode: mode,
    resolvedDark,
    resolvedMode: resolvedDark ? "dark" : "light",
  };
}

/**
 * 登记由后端 manifest 扫描到的主题清单（未实际切换前不强制拉取其 JS/CSS，按需加载）。
 */
export function registerDiscoveredManifests(manifests = []) {
  for (const m of manifests) {
    if (!m || !m.id) continue;
    const id = String(m.id).trim().toLowerCase();
    const prev = _themes.get(id) || {};
    _themes.set(id, {
      ...prev,
      id,
      name: String(m.name || prev.name || id),
      subtitle: String(m.subtitle || prev.subtitle || ""),
      description: String(m.description || prev.description || ""),
      badge: String(m.badge ?? prev.badge ?? ""),
      preview: String(m.preview || prev.preview || ""),
      order: Number.isFinite(Number(m.order)) ? Number(m.order) : (prev.order ?? 100),
      entry: m.entry ? String(m.entry) : prev.entry || "",
      styles: Array.isArray(m.styles) ? [...m.styles] : prev.styles || [],
      css: prev.css || "",
      mount: prev.mount || null,
      loader: prev.loader || null,
    });
  }
}

/**
 * 注册一套完整的网页设计主题包。
 *
 * spec 结构：
 * {
 *   id: string,                     // 唯一 ID（需匹配 ^[a-z][a-z0-9_-]*$）
 *   name: string,                   // 主题名称
 *   subtitle?: string,              // 设计定位
 *   description?: string,           // 设计说明
 *   badge?: string,                 // 角标
 *   order?: number,                 // 排序权重
 *   preview?: string,               // 预览线框类型或自定义渲染提示
 *   styles?: string[],              // 相对 views/rika/ 的独立 CSS 文件路径清单
 *   css?: string,                   // 仅单文件运行时注册时使用的内联 CSS 字符串
 *   mount: (mountEl, ctx) => { unmount?, onColorModeChange?, onContextChange? }
 * }
 */
export function registerTheme(spec) {
  if (!spec || !spec.id) {
    throw new Error("Theme spec must declare a non-empty id");
  }
  if (typeof spec.mount !== "function" && typeof spec.loader !== "function") {
    throw new Error(`Theme '${spec.id}' must provide a mount(mountEl, ctx) function`);
  }
  const id = String(spec.id).trim().toLowerCase();
  const prev = _themes.get(id) || {};
  const normalized = {
    ...prev,
    ...spec,
    id,
    name: String(spec.name || prev.name || id),
    subtitle: String(spec.subtitle || prev.subtitle || ""),
    description: String(spec.description || prev.description || ""),
    badge: String(spec.badge ?? prev.badge ?? ""),
    preview: String(spec.preview || prev.preview || ""),
    order: Number.isFinite(Number(spec.order)) ? Number(spec.order) : (prev.order ?? 100),
    styles: Array.isArray(spec.styles) ? [...spec.styles] : prev.styles || [],
    css: typeof spec.css === "string" ? spec.css : prev.css || "",
    mount: typeof spec.mount === "function" ? spec.mount : prev.mount || null,
    loader: typeof spec.loader === "function" ? spec.loader : prev.loader || null,
  };
  _themes.set(id, normalized);
  emitThemeListChange();
  return normalized;
}

export function getTheme(id) {
  const key = String(id || "").trim().toLowerCase();
  return _themes.get(key) || _themes.get(DEFAULT_THEME_ID) || _themes.values().next().value || null;
}

export function listThemes() {
  return Array.from(_themes.values()).sort(
    (a, b) => Number(a.order ?? 100) - Number(b.order ?? 100) || a.id.localeCompare(b.id),
  );
}

export function getActiveThemeId() {
  return _activeThemeId;
}

function clearThemeStyles() {
  for (const el of document.querySelectorAll("[data-rika-theme-asset]")) {
    el.remove();
  }
}

function toStylesheetHref(relPath) {
  const clean = String(relPath || "").trim().replace(/^\.\//, "");
  return `./${clean}`;
}

async function ensureThemeLoaded(theme) {
  if (!theme) return null;
  if (typeof theme.mount === "function") return theme;

  if (typeof theme.loader === "function") {
    await theme.loader();
    return _themes.get(theme.id) || theme;
  }

  if (theme.entry) {
    const relEntry = theme.entry.startsWith("./") || theme.entry.startsWith("/") ? theme.entry : `./${theme.entry}`;
    // manifest 下发的 entry 相对于 views/rika/（页面根），而 import() 默认相对于本模块（themes/），
    // 因此需按文档基址解析为绝对 URL，避免变成 themes/themes/<id>/index.js。
    const specifier = new URL(relEntry, document.baseURI).href;
    const mod = await import(specifier);
    const candidate = mod?.default && typeof mod.default === "object" ? mod.default : mod;
    if (typeof candidate?.mount === "function") {
      registerTheme({ ...theme, ...candidate, id: theme.id });
    }
    return _themes.get(theme.id) || theme;
  }
  return theme;
}

function loadThemeStylesheets(theme) {
  clearThemeStyles();
  const promises = [];

  for (const rawPath of theme?.styles || []) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = toStylesheetHref(rawPath);
    link.setAttribute("data-rika-theme-asset", theme.id);

    const p = new Promise((resolve) => {
      let settled = false;
      const done = () => {
        if (!settled) {
          settled = true;
          resolve();
        }
      };
      link.addEventListener("load", done, { once: true });
      link.addEventListener("error", done, { once: true });
      // 在无网络/jsdom 环境中兜底超时，确保不会永久阻塞渲染
      window.setTimeout(done, 150);
    });
    promises.push(p);
    document.head.appendChild(link);
  }

  if (theme?.css) {
    const styleEl = document.createElement("style");
    styleEl.setAttribute("data-rika-theme-asset", theme.id);
    styleEl.textContent = theme.css;
    document.head.appendChild(styleEl);
  }

  return Promise.all(promises);
}

export function syncColorAttributes({ themeId, colorMode, systemIsDark }) {
  const { colorMode: mode, resolvedDark, resolvedMode } = resolveColorMode(colorMode, systemIsDark);
  const root = document.documentElement;
  root.setAttribute("data-theme", resolvedMode);
  root.setAttribute("data-color-mode", mode);
  if (themeId) {
    root.setAttribute("data-rika-theme", themeId);
  }
  return { colorMode: mode, resolvedDark, resolvedMode };
}

export function unmountActiveTheme(mountEl) {
  for (const fn of _activeCleanups.splice(0)) {
    try {
      fn();
    } catch (err) {
      console.error("[RikaWebUI] cleanup error during unmount:", err);
    }
  }
  if (_activeHandle && typeof _activeHandle.unmount === "function") {
    try {
      _activeHandle.unmount();
    } catch (err) {
      console.error("[RikaWebUI] theme unmount error:", err);
    }
  }
  _activeHandle = null;
  _activeThemeId = "";
  clearThemeStyles();
  if (mountEl) {
    while (mountEl.firstChild) mountEl.removeChild(mountEl.firstChild);
  }
}

/**
 * 卸载当前主题，加载并挂载目标整页主题。
 */
export async function activateTheme(themeId, mountEl, buildCtx) {
  const myToken = ++_mountToken;
  const candidate = getTheme(themeId);
  if (!candidate) {
    throw new Error("未找到任何可用的网页主题");
  }

  const loaded = await ensureThemeLoaded(candidate);
  if (myToken !== _mountToken) return null;
  if (!loaded || typeof loaded.mount !== "function") {
    throw new Error(`网页主题「${candidate.id}」未提供有效 mount(mountEl, ctx) 入口`);
  }

  unmountActiveTheme(mountEl);

  const colorState = syncColorAttributes({
    themeId: loaded.id,
    colorMode: buildCtx.colorMode,
    systemIsDark: buildCtx.systemIsDark,
  });

  await loadThemeStylesheets(loaded);
  if (myToken !== _mountToken) return null;

  const cleanups = [];
  _activeCleanups = cleanups;
  const ctx = {
    ...buildCtx,
    ...colorState,
    theme: loaded,
    onDispose(fn) {
      if (typeof fn === "function") cleanups.push(fn);
    },
  };

  _activeThemeId = loaded.id;
  _activeHandle = (await loaded.mount(mountEl, ctx)) || {};
  return { theme: loaded, handle: _activeHandle, ...colorState };
}

export function notifyActiveThemeColorChange({ colorMode, systemIsDark }) {
  const colorState = syncColorAttributes({
    themeId: _activeThemeId,
    colorMode,
    systemIsDark,
  });
  _activeHandle?.onColorModeChange?.(colorState);
  return colorState;
}

export function notifyActiveThemeContextChange(context) {
  _activeHandle?.onContextChange?.(context);
}

export function installGlobalThemeApi() {
  window.RikaWebTheme = Object.freeze({
    registerTheme,
    getTheme,
    listThemes,
    getActiveThemeId,
    normalizeColorMode,
    resolveColorMode,
  });
  return window.RikaWebTheme;
}
