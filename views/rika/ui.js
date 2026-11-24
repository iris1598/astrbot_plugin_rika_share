/**
 * 轻量 DOM 工具、SVG 图标库与受限 iframe 安全交互组件。
 *
 * 严格约束：
 * - 全部文案使用 textContent，禁止拼装 html 字符串；
 * - 表单控件赋值全部走 DOM property（node.value / node.checked）；
 * - 危险动作全部采用行内二次确认，绝不调用 alert/confirm。
 */

export function append(parent, child) {
  if (child == null || child === false) return;
  if (Array.isArray(child)) {
    for (const item of child) append(parent, item);
    return;
  }
  if (child instanceof Node) {
    parent.appendChild(child);
    return;
  }
  parent.appendChild(document.createTextNode(String(child)));
}

export function h(tag, attrs = null, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [key, val] of Object.entries(attrs)) {
      if (val == null || val === false) continue;
      if (key === "class" || key === "className") {
        el.className = String(val);
      } else if (key === "style" && typeof val === "object") {
        Object.assign(el.style, val);
      } else if (key === "dataset" && typeof val === "object") {
        Object.assign(el.dataset, val);
      } else if (key.startsWith("on") && typeof val === "function") {
        el.addEventListener(key.slice(2).toLowerCase(), val);
      } else if (key === "value") {
        el.value = String(val);
      } else if (key === "checked" || key === "disabled" || key === "open" || key === "selected") {
        el[key] = Boolean(val);
      } else if (val === true) {
        el.setAttribute(key, "");
      } else {
        el.setAttribute(key, String(val));
      }
    }
  }
  append(el, children);
  return el;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

/** 在同步 DOM 重建期间锁住当前窗口与文档滚动位置，防止高度塌陷回顶 */
export function preserveScroll(fn) {
  const win = typeof window !== "undefined" ? window : null;
  const doc = typeof document !== "undefined" ? document : null;
  const se = doc?.scrollingElement || doc?.documentElement || doc?.body || null;
  const prevY = typeof win?.scrollY === "number" ? win.scrollY : (se?.scrollTop ?? 0);
  const prevX = typeof win?.scrollX === "number" ? win.scrollX : (se?.scrollLeft ?? 0);
  const res = fn();
  if (prevY > 0 || prevX > 0) {
    if (se && typeof se.scrollTop === "number") se.scrollTop = prevY;
    if (typeof win?.scrollTo === "function") win.scrollTo(prevX, prevY);
    if (typeof requestAnimationFrame === "function") {
      requestAnimationFrame(() => {
        if (se && typeof se.scrollTop === "number") se.scrollTop = prevY;
        if (typeof win?.scrollTo === "function") win.scrollTo(prevX, prevY);
      });
    }
  }
  return res;
}

/** 原子替换容器子节点（不先把高度清零），并维持滚动坐标稳定 */
export function swapContent(container, children) {
  const list = [];
  const pushFlat = (item) => {
    if (item == null || item === false) return;
    if (Array.isArray(item)) {
      for (const x of item) pushFlat(x);
      return;
    }
    if (item instanceof Node) {
      list.push(item);
      return;
    }
    list.push(document.createTextNode(String(item)));
  };
  pushFlat(children);

  const prevHeight = Number(container?.offsetHeight || 0);
  const prevMin = container?.style?.minHeight || "";
  return preserveScroll(() => {
    if (prevHeight > 0 && container?.style) {
      container.style.minHeight = `${prevHeight}px`;
    }
    if (typeof container.replaceChildren === "function") {
      container.replaceChildren(...list);
    } else {
      clear(container);
      for (const node of list) container.appendChild(node);
    }
    if (container?.style) {
      container.style.minHeight = prevMin;
    }
  });
}

const SVG_NS = "http://www.w3.org/2000/svg";

const ICON_PATHS = {
  dashboard: [
    "M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z",
  ],
  platforms: [
    "M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 3a3 3 0 1 1-3 3 3 3 0 0 1 3-3zm0 14.2a7.2 7.2 0 0 1-6-3.22c.03-1.99 4-3.08 6-3.08s5.97 1.09 6 3.08a7.2 7.2 0 0 1-6 3.22z",
  ],
  studio: [
    "M4 5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5zm3 3v4h10V8H7zm0 7v2h6v-2H7z",
  ],
  sliders: [
    "M4 7h9m4 0h3M15 4v6M4 17h3m4 0h9M9 14v6M4 12h16",
  ],
  eye: [
    "M2 12s3.8-6 10-6 10 6 10 6-3.8 6-10 6-10-6-10-6zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  ],
  refresh: [
    "M20 11a8 8 0 0 0-14.9-3M4 4v4h4M4 13a8 8 0 0 0 14.9 3M20 20v-4h-4",
  ],
  logo: [
    "M8 6.5h7.2c3.1 0 5.3 1.8 5.3 4.6 0 2-1.1 3.5-2.9 4.2l3.4 6.2h-3.6l-3-5.6h-3.1v5.6H8V6.5zm3.3 2.7v4.1h3.7c1.4 0 2.2-.8 2.2-2s-.8-2.1-2.2-2.1h-3.7z",
  ],
};

export function icon(name, size = 18) {
  const paths = ICON_PATHS[name] || ICON_PATHS.dashboard;
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("fill", name === "sliders" || name === "refresh" ? "none" : "currentColor");
  if (name === "sliders" || name === "refresh") {
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.9");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
  }
  svg.setAttribute("aria-hidden", "true");
  for (const d of paths) {
    const p = document.createElementNS(SVG_NS, "path");
    p.setAttribute("d", d);
    svg.appendChild(p);
  }
  return svg;
}

export function formatBytes(bytes) {
  const n = Number(bytes || 0);
  if (!Number.isFinite(n) || n <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let idx = 0;
  let val = n;
  while (val >= 1024 && idx < units.length - 1) {
    val /= 1024;
    idx += 1;
  }
  return `${idx === 0 ? val : val.toFixed(1)} ${units[idx]}`;
}

export function valuesEqual(a, b) {
  if (Array.isArray(a) || Array.isArray(b)) {
    const la = Array.isArray(a) ? a : [];
    const lb = Array.isArray(b) ? b : [];
    return la.length === lb.length && la.every((v, i) => String(v) === String(lb[i]));
  }
  return a === b;
}

export function createToaster() {
  const host = h("div", { class: "toast-stack", role: "status", "aria-live": "polite" });
  document.body.appendChild(host);

  return function toast(message, kind = "info", durationMs = 3200) {
    const item = h(
      "div",
      { class: `toast toast-${kind}` },
      h("span", { class: "toast-dot", "aria-hidden": "true" }),
      h("span", { class: "toast-msg" }, message),
    );
    host.appendChild(item);
    requestAnimationFrame(() => item.classList.add("is-in"));
    const timer = window.setTimeout(() => {
      item.classList.remove("is-in");
      window.setTimeout(() => item.remove(), 220);
    }, durationMs);
    item.addEventListener("click", () => {
      window.clearTimeout(timer);
      item.remove();
    });
  };
}

export function createInlineConfirmButton({
  label,
  confirmLabel = "确认执行",
  cancelLabel = "取消",
  variant = "ghost",
  size = "",
  onConfirm,
}) {
  const wrap = h("span", { class: "inline-confirm" });
  let armed = false;
  let busy = false;
  const sizeCls = size ? ` btn-${size}` : "";

  const render = () => {
    clear(wrap);
    if (!armed) {
      wrap.appendChild(
        h(
          "button",
          {
            type: "button",
            class: `btn btn-${variant}${sizeCls}`,
            disabled: busy,
            onclick: () => {
              armed = true;
              render();
            },
          },
          label,
        ),
      );
      return;
    }

    wrap.appendChild(
      h(
        "span",
        { class: "confirm-pair" },
        h(
          "button",
          {
            type: "button",
            class: `btn btn-danger${sizeCls}`,
            disabled: busy,
            onclick: async () => {
              busy = true;
              render();
              try {
                await onConfirm?.();
              } finally {
                busy = false;
                armed = false;
                render();
              }
            },
          },
          busy ? "处理中…" : confirmLabel,
        ),
        h(
          "button",
          {
            type: "button",
            class: `btn btn-ghost${sizeCls}`,
            disabled: busy,
            onclick: () => {
              armed = false;
              render();
            },
          },
          cancelLabel,
        ),
      ),
    );
  };

  render();
  return wrap;
}

/** 根据 CONFIG_META 条目构建标准化控件，支持原地状态更新避免页面滚动复位 */
export function buildControlRow(store, item, options = {}) {
  const { showKey = false, full = false, secretState = null, onAfterChange = null } = options;
  const isGroup = Boolean(store.scope);
  const overridable = !isGroup || Boolean(store.isOverridable?.(item.key));
  const locked = isGroup && !overridable;
  const val = store.draft[item.key];
  const tagsHost = h("span", { class: "setting-label-tags" });
  let rowEl = null;

  function syncRowState() {
    const curVal = store.draft[item.key];
    const savedVal = store.meta?.values?.[item.key];
    const pendingUnset = Boolean(store.pendingUnset?.has(item.key));
    const hasOverride =
      isGroup &&
      overridable &&
      Boolean(store.overrideKeys?.has(item.key)) &&
      !pendingUnset;
    const dirtyNow = !locked && (pendingUnset || !valuesEqual(curVal, savedVal));

    if (rowEl) {
      rowEl.classList.toggle("is-dirty", dirtyNow);
    }
    clear(tagsHost);
    if (showKey) tagsHost.appendChild(h("code", { class: "dev-key" }, item.key));
    if (locked) {
      tagsHost.appendChild(h("span", { class: "pill scope-pill-global" }, "仅全局"));
    } else if (hasOverride) {
      tagsHost.appendChild(h("span", { class: "pill pill-info scope-pill-group" }, "本群独立"));
    }
    if (dirtyNow) {
      tagsHost.appendChild(h("span", { class: "dirty-pill" }, pendingUnset ? "将恢复继承" : "已更改"));
    }
    if (isGroup && overridable && (hasOverride || dirtyNow)) {
      tagsHost.appendChild(
        h(
          "button",
          {
            type: "button",
            class: "btn btn-ghost btn-xs scope-revert-btn",
            onclick: () => {
              store.revertKeyToInherit?.(item.key);
              onAfterChange?.();
            },
          },
          "恢复继承",
        ),
      );
    }
  }

  let controlEl;
  if (item.type === "bool") {
    const switchText = h("span", { class: "switch-text" }, Boolean(val) ? "已开启" : "已关闭");
    const chk = h("input", {
      type: "checkbox",
      checked: Boolean(val),
      onchange: (e) => {
        const nextVal = Boolean(e.target.checked);
        store.setDraftValue(item.key, nextVal);
        switchText.textContent = nextVal ? "已开启" : "已关闭";
        syncRowState();
        onAfterChange?.();
      },
    });
    controlEl = h(
      "label",
      { class: "switch" },
      chk,
      h("span", { class: "switch-track" }),
      switchText,
    );
  } else if (item.type === "select") {
    const opts = item.options || [];
    const labels = item.labels || opts;
    const sel = h(
      "select",
      {
        class: "ctrl-input ctrl-select",
        onchange: (e) => {
          store.setDraftValue(item.key, e.target.value);
          syncRowState();
          onAfterChange?.();
        },
      },
      opts.map((opt, idx) =>
        h("option", { value: opt, selected: String(val ?? "") === String(opt) }, labels[idx] || opt),
      ),
    );
    sel.value = String(val ?? item.default ?? "");
    controlEl = sel;
  } else if (item.type === "list") {
    const ta = h("textarea", {
      class: "ctrl-input ctrl-textarea",
      rows: 3,
      placeholder: item.placeholder || "每行或逗号分隔一条规则",
      oninput: (e) => {
        const rows = e.target.value
          .split(/\r?\n|,/)
          .map((s) => s.trim())
          .filter(Boolean);
        store.setDraftValue(item.key, rows, { rerender: false });
        syncRowState();
      },
    });
    ta.value = Array.isArray(val) ? val.join("\n") : String(val ?? "");
    controlEl = ta;
  } else if (item.type === "text") {
    const ta = h("textarea", {
      class: "ctrl-input ctrl-textarea mono",
      rows: 3,
      placeholder: item.placeholder || "",
      oninput: (e) => {
        store.setDraftValue(item.key, e.target.value, { rerender: false });
        syncRowState();
      },
    });
    ta.value = String(val ?? "");
    controlEl = ta;
  } else if (item.type === "int" || item.type === "float") {
    const num = h("input", {
      type: "number",
      class: "ctrl-input",
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
          syncRowState();
        }
      },
    });
    num.value = val ?? item.default ?? "";
    controlEl = item.unit
      ? h("div", { class: "unit-field" }, num, h("span", { class: "unit-tag" }, item.unit))
      : num;
  } else {
    const isSecret = Boolean(item.secret);
    let revealed = isSecret && Boolean(secretState?.has(item.key));
    const inp = h("input", {
      type: isSecret && !revealed ? "password" : "text",
      class: `ctrl-input ${isSecret ? "mono" : ""}`,
      placeholder: item.placeholder || "",
      autocomplete: "off",
      oninput: (e) => {
        store.setDraftValue(item.key, e.target.value, { rerender: false });
        syncRowState();
      },
    });
    inp.value = String(val ?? "");
    let toggleBtn = null;
    if (isSecret) {
      toggleBtn = h(
        "button",
        {
          type: "button",
          class: "btn btn-ghost btn-sm",
          onclick: () => {
            if (!secretState) return;
            if (secretState.has(item.key)) secretState.delete(item.key);
            else secretState.add(item.key);
            revealed = secretState.has(item.key);
            inp.type = revealed ? "text" : "password";
            toggleBtn.textContent = revealed ? "隐藏" : "显示";
          },
        },
        revealed ? "隐藏" : "显示",
      );
    }
    controlEl = isSecret
      ? h("div", { class: "secret-field" }, inp, toggleBtn)
      : inp;
  }

  rowEl = h(
    "div",
    {
      class: `setting-item ${full || item.type === "list" || item.type === "text" || item.secret ? "is-wide" : ""} ${locked ? "is-global-locked" : ""}`,
      dataset: { key: item.key },
    },
    h(
      "div",
      { class: "setting-meta" },
      h(
        "div",
        { class: "setting-label-row" },
        h("span", { class: "setting-label" }, item.label || item.key),
        tagsHost,
      ),
      item.hint ? h("p", { class: "setting-hint" }, item.hint) : null,
    ),
    h("div", { class: "setting-ctrl" }, controlEl),
  );
  syncRowState();
  if (locked) {
    for (const el of rowEl.querySelectorAll("input, select, textarea")) {
      el.disabled = true;
    }
  }
  return rowEl;
}
