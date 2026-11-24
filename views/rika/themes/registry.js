/**
 * 结构级网页主题注册表与布局引擎。
 *
 * 主题不仅控制配色，还能声明完全不同的页面骨架（data-layout / navMode）
 * 与专属 CSS 排版规则，通过 window.RikaWebTheme 对外部扩展开放。
 *
 * ThemeSpec 结构：
 * {
 *   id: string,                    // 唯一标识
 *   name: string,                  // 展示名
 *   subtitle: string,              // 简短定位
 *   description: string,           // 设计说明
 *   layout: "studio" | "glass-center" | string, // 网页结构拓扑模式
 *   navMode: "sidebar" | "dock" | string,       // 导航形态（左侧栏 / 底部悬浮胶囊）
 *   badge?: string,
 *   light: Record<string, string>, // 浅色变量令牌
 *   dark: Record<string, string>,  // 深色变量令牌
 *   css?: string,                  // 布局专属扩展样式
 * }
 */

const _themes = new Map();
let _appliedVars = [];
const EXTRA_STYLE_ID = "rika-theme-layout-css";

export const DEFAULT_THEME_ID = "studio";
export const VALID_COLOR_MODES = new Set(["auto", "light", "dark"]);

export function normalizeColorMode(mode) {
  const m = String(mode || "auto").trim().toLowerCase();
  return VALID_COLOR_MODES.has(m) ? m : "auto";
}

export function registerTheme(spec) {
  if (!spec || !spec.id) {
    throw new Error("Theme spec must declare a non-empty id");
  }
  const id = String(spec.id).trim().toLowerCase();
  const normalized = {
    ...spec,
    id,
    name: String(spec.name || id),
    subtitle: String(spec.subtitle || ""),
    description: String(spec.description || ""),
    layout: String(spec.layout || id),
    navMode: String(spec.navMode || (spec.layout === "glass-center" ? "dock" : "sidebar")),
    badge: spec.badge ? String(spec.badge) : "",
    light: { ...(spec.light || {}) },
    dark: { ...(spec.dark || {}) },
    css: typeof spec.css === "string" ? spec.css : "",
  };
  _themes.set(id, normalized);
  return normalized;
}

export function getTheme(id) {
  const key = String(id || "").trim().toLowerCase();
  return _themes.get(key) || _themes.get(DEFAULT_THEME_ID) || _themes.values().next().value || null;
}

export function listThemes() {
  return Array.from(_themes.values());
}

export function applyTheme(themeId, { systemIsDark = false, colorMode = "auto" } = {}) {
  const mode = normalizeColorMode(colorMode);
  const resolvedDark = mode === "auto" ? Boolean(systemIsDark) : mode === "dark";
  const resolvedMode = resolvedDark ? "dark" : "light";
  const theme = getTheme(themeId);

  const root = document.documentElement;
  root.setAttribute("data-theme", resolvedMode);
  root.setAttribute("data-color-mode", mode);

  for (const k of _appliedVars) root.style.removeProperty(k);
  _appliedVars = [];

  if (!theme) return { themeId: DEFAULT_THEME_ID, resolvedMode, colorMode: mode, theme: null };

  root.setAttribute("data-rika-theme", theme.id);
  root.setAttribute("data-layout", theme.layout);
  root.setAttribute("data-nav", theme.navMode);

  const palette = resolvedDark ? theme.dark : theme.light;
  for (const [rawKey, value] of Object.entries(palette || {})) {
    const cssVar = rawKey.startsWith("--") ? rawKey : `--${rawKey}`;
    root.style.setProperty(cssVar, String(value));
    _appliedVars.push(cssVar);
  }

  let extraEl = document.getElementById(EXTRA_STYLE_ID);
  if (theme.css) {
    if (!extraEl) {
      extraEl = document.createElement("style");
      extraEl.id = EXTRA_STYLE_ID;
      document.head.appendChild(extraEl);
    }
    extraEl.textContent = theme.css;
  } else if (extraEl) {
    extraEl.textContent = "";
  }

  return { themeId: theme.id, resolvedMode, colorMode: mode, theme };
}

export function installGlobalThemeApi() {
  window.RikaWebTheme = Object.freeze({
    registerTheme,
    getTheme,
    listThemes,
    applyTheme,
    normalizeColorMode,
  });
  return window.RikaWebTheme;
}
