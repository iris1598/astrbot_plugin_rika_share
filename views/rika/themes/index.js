import {
  DEFAULT_THEME_ID,
  applyTheme,
  getTheme,
  installGlobalThemeApi,
  listThemes,
  normalizeColorMode,
  registerTheme,
} from "./registry.js";

import "./studio.js";
import "./glass-center.js";

installGlobalThemeApi();

export {
  DEFAULT_THEME_ID,
  applyTheme,
  getTheme,
  listThemes,
  normalizeColorMode,
  registerTheme,
};
