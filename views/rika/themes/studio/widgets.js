import { clear, h } from "../../core/dom.js";

/** 根据 CONFIG_META 条目构建 Studio 主题风格的表单行，支持原地状态更新避免滚动回顶 */
export function buildControlRow(store, item, options = {}) {
  const { showKey = false, full = false, secretState = null, onAfterChange = null } = options;
  const isGroup = Boolean(store.scope);
  const overridable = !isGroup || Boolean(store.isOverridable?.(item.key));
  const locked = isGroup && !overridable;
  const val = store.draft[item.key];
  const tagsHost = h("span", { class: "setting-label-tags" });
  let rowEl = null;

  function syncRowState() {
    const hasOverride = store.isKeyOverridden(item.key);
    const pendingUnset = Boolean(store.pendingUnset?.has(item.key));
    const dirtyNow = store.isKeyDirty(item.key);

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
