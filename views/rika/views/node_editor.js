import { clear, h, valuesEqual } from "../ui.js";

function cloneRules(obj) {
  return JSON.parse(JSON.stringify(obj || {}));
}

export function normalizeNodeRulesClient(raw, nodeSchema) {
  const defaults = nodeSchema?.defaults || {};
  const catalog = nodeSchema?.catalog || {};
  const modes = (nodeSchema?.modes || []).map((m) => m.id);
  const modeList = modes.length ? modes : Object.keys(defaults);

  let parsed = null;
  if (typeof raw === "string") {
    const text = raw.trim();
    if (text) {
      try {
        const obj = JSON.parse(text);
        if (obj && typeof obj === "object" && !Array.isArray(obj)) {
          parsed = obj;
        }
      } catch {
        parsed = null;
      }
    }
  } else if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    parsed = raw;
  }

  const out = {};
  for (const mode of modeList) {
    const defList = Array.isArray(defaults[mode]) ? defaults[mode] : [];
    const allowedIds = new Set(defList.map((entry) => entry.id));
    const defMap = new Map(defList.map((entry) => [entry.id, entry]));
    const rawList = Array.isArray(parsed?.[mode]) ? parsed[mode] : defList;

    const seen = new Set();
    const list = [];
    for (const item of rawList) {
      if (!item || typeof item !== "object") continue;
      const id = String(item.id || "").trim();
      if (!allowedIds.has(id) || seen.has(id)) continue;
      seen.add(id);
      const supportsMerge = catalog[id]?.supports_merge !== false;
      list.push({
        id,
        enabled: Boolean(item.enabled),
        merge: supportsMerge ? Boolean(item.merge) : false,
      });
    }
    for (const defEntry of defList) {
      if (seen.has(defEntry.id)) continue;
      const supportsMerge = catalog[defEntry.id]?.supports_merge !== false;
      list.push({
        id: defEntry.id,
        enabled: Boolean(defEntry.enabled),
        merge: supportsMerge ? Boolean(defEntry.merge) : false,
      });
    }
    out[mode] = list;
  }
  return out;
}

export function rulesEqual(a, b, nodeSchema) {
  const na = normalizeNodeRulesClient(a, nodeSchema);
  const nb = normalizeNodeRulesClient(b, nodeSchema);
  const keys = Object.keys(na);
  if (keys.length !== Object.keys(nb).length) return false;
  return keys.every((mode) => {
    const la = na[mode] || [];
    const lb = nb[mode] || [];
    return (
      la.length === lb.length &&
      la.every(
        (item, idx) =>
          item.id === lb[idx].id &&
          item.enabled === lb[idx].enabled &&
          item.merge === lb[idx].merge,
      )
    );
  });
}

export function serializeNodeRules(rulesObj, nodeSchema) {
  const normalized = normalizeNodeRulesClient(rulesObj, nodeSchema);
  const defaults = nodeSchema?.defaults || {};
  if (rulesEqual(normalized, defaults, nodeSchema)) {
    return "";
  }
  return JSON.stringify(normalized);
}

/** 分模式输出节点编排器：支持节点启用开关、上下排序、是否放入合并转发与分群覆写 */
export function createNodeRulesPanel(store, { onAfterChange = null } = {}) {
  const root = h("section", { class: "surface-panel node-editor-panel" });
  let activeMode = "video";

  function getSchema() {
    return store.meta?.node_schema || { modes: [], catalog: {}, defaults: {} };
  }

  function applyUpdatedRules(nextObj) {
    const schema = getSchema();
    const serialized = serializeNodeRules(nextObj, schema);
    store.setDraftValue("NODE_RULES", serialized);
    render();
    onAfterChange?.();
  }

  function moveNode(mode, index, delta) {
    const schema = getSchema();
    const current = normalizeNodeRulesClient(store.draft.NODE_RULES, schema);
    const list = cloneRules(current[mode] || []);
    const target = index + delta;
    if (target < 0 || target >= list.length) return;
    const [picked] = list.splice(index, 1);
    list.splice(target, 0, picked);
    current[mode] = list;
    applyUpdatedRules(current);
  }

  function toggleField(mode, index, field, value) {
    const schema = getSchema();
    const catalog = schema.catalog || {};
    const current = normalizeNodeRulesClient(store.draft.NODE_RULES, schema);
    const list = cloneRules(current[mode] || []);
    const item = list[index];
    if (!item) return;
    if (field === "merge" && catalog[item.id]?.supports_merge === false) {
      return;
    }
    item[field] = Boolean(value);
    if (catalog[item.id]?.supports_merge === false) {
      item.merge = false;
    }
    current[mode] = list;
    applyUpdatedRules(current);
  }

  function resetMode(mode) {
    const schema = getSchema();
    const current = normalizeNodeRulesClient(store.draft.NODE_RULES, schema);
    const defaults = schema.defaults || {};
    if (!Array.isArray(defaults[mode])) return;
    current[mode] = cloneRules(defaults[mode]);
    applyUpdatedRules(current);
  }

  function buildOrderSummary(list, catalog) {
    const enabled = list.filter((entry) => entry.enabled);
    if (enabled.length === 0) {
      return [{ kind: "warn", label: "当前模式已关闭全部可选节点（仅保留兜底保护）" }];
    }

    const chunks = [];
    let mergeBuf = [];
    const flushMerge = () => {
      if (!mergeBuf.length) return;
      chunks.push({
        kind: "merge",
        label: `合并转发(${mergeBuf.join(" → ")})`,
      });
      mergeBuf = [];
    };

    for (const entry of enabled) {
      const name = catalog[entry.id]?.label || entry.id;
      const supportsMerge = catalog[entry.id]?.supports_merge !== false;
      if (supportsMerge && entry.merge) {
        mergeBuf.push(name);
      } else {
        flushMerge();
        chunks.push({ kind: "single", label: `独立:${name}` });
      }
    }
    flushMerge();
    return chunks;
  }

  function render() {
    clear(root);
    const schema = getSchema();
    const modes = schema.modes || [];
    const catalog = schema.catalog || {};
    const defaults = schema.defaults || {};

    if (!modes.length) {
      root.appendChild(h("p", { class: "surface-desc" }, "后端未返回节点元数据"));
      return;
    }
    if (!modes.some((m) => m.id === activeMode)) {
      activeMode = modes[0].id;
    }

    const current = normalizeNodeRulesClient(store.draft.NODE_RULES, schema);
    const list = current[activeMode] || [];
    const modeMeta = modes.find((m) => m.id === activeMode) || modes[0];

    const isGroup = Boolean(store.scope);
    const overridable = !isGroup || store.isOverridable("NODE_RULES");
    const locked = isGroup && !overridable;
    const isDirty =
      store.pendingUnset?.has("NODE_RULES") ||
      !valuesEqual(store.draft.NODE_RULES, store.meta?.values?.NODE_RULES);
    const hasOverride =
      isGroup && store.overrideKeys?.has("NODE_RULES") && !store.pendingUnset?.has("NODE_RULES");
    const differsFromDefault = !rulesEqual(
      { [activeMode]: list },
      { [activeMode]: defaults[activeMode] || [] },
      schema,
    );

    const statusTags = [];
    if (store.showDevKeys) {
      statusTags.push(h("code", { class: "dev-key" }, "NODE_RULES"));
    }
    if (isGroup && hasOverride) {
      statusTags.push(h("span", { class: "pill pill-info" }, "本群独立"));
    } else if (isGroup) {
      statusTags.push(h("span", { class: "pill" }, "继承全局"));
    }
    if (isDirty) {
      statusTags.push(h("span", { class: "pill pill-warn" }, "待保存"));
    }

    root.appendChild(
      h(
        "div",
        { class: "surface-head" },
        h(
          "div",
          null,
          h("div", { class: "setting-label-row" }, h("h2", { class: "surface-title" }, "输出节点编排（分模式开关 · 顺序 · 合并）"), ...statusTags),
          h(
            "p",
            { class: "surface-desc" },
            "按内容形态（视频 / 图文 / 动态文章）分别编排输出节点，零重解析代价，支持分群独立覆盖",
          ),
        ),
        isGroup && (hasOverride || isDirty)
          ? h(
              "button",
              {
                type: "button",
                class: "btn btn-ghost btn-sm",
                onclick: () => store.revertKeyToInherit("NODE_RULES"),
              },
              "恢复继承全局",
            )
          : null,
      ),
    );

    // 模式切换栏
    root.appendChild(
      h(
        "div",
        { class: "node-mode-bar" },
        h(
          "div",
          { class: "seg-group node-mode-tabs", role: "tablist" },
          modes.map((m) => {
            const active = m.id === activeMode;
            const changed = !rulesEqual(
              { [m.id]: current[m.id] || [] },
              { [m.id]: defaults[m.id] || [] },
              schema,
            );
            return h(
              "button",
              {
                type: "button",
                role: "tab",
                "aria-selected": active ? "true" : "false",
                class: `seg-btn ${active ? "is-active" : ""}`,
                onclick: () => {
                  activeMode = m.id;
                  render();
                },
              },
              m.label,
              changed ? h("span", { class: "mode-custom-dot", title: "已自定义" }) : null,
            );
          }),
        ),
        h(
          "div",
          { class: "node-mode-actions" },
          h("span", { class: "node-mode-desc" }, modeMeta?.description || ""),
          differsFromDefault && !locked
            ? h(
                "button",
                {
                  type: "button",
                  class: "btn btn-ghost btn-sm",
                  onclick: () => resetMode(activeMode),
                },
                "恢复本模式默认",
              )
            : null,
        ),
      ),
    );

    // 当前模式编排预览条
    const chunks = buildOrderSummary(list, catalog);
    const webpageFallback = Boolean(store.draft.WEBPAGE_FALLBACK_ENABLED);
    root.appendChild(
      h(
        "div",
        { class: "node-flow-preview" },
        h(
          "span",
          { class: "node-flow-label" },
          webpageFallback
            ? "发送序预览（非 OneBot 将按合并段转临时网页）："
            : "发送序预览（非 OneBot 将自动拆解为独立消息）：",
        ),
        h(
          "div",
          { class: "node-flow-chips" },
          chunks.map((chunk) =>
            h(
              "span",
              {
                class: `pill ${
                  chunk.kind === "merge"
                    ? "pill-info"
                    : chunk.kind === "warn"
                      ? "pill-warn"
                      : ""
                }`,
              },
              chunk.label,
            ),
          ),
        ),
      ),
    );

    // 节点顺序列表
    root.appendChild(
      h(
        "div",
        { class: `node-list ${locked ? "is-global-locked" : ""}` },
        list.map((entry, idx) => {
          const meta = catalog[entry.id] || {
            id: entry.id,
            label: entry.id,
            description: "",
            supports_merge: true,
          };
          const supportsMerge = meta.supports_merge !== false;
          const mergeLocked = !supportsMerge || locked;
          const rowClasses = ["node-row"];
          if (!entry.enabled) rowClasses.push("is-disabled");
          if (supportsMerge && entry.enabled && entry.merge) rowClasses.push("is-merged");
          if (!supportsMerge) rowClasses.push("is-merge-unsupported");

          const moveBtns = h(
            "div",
            { class: "node-move-group" },
            h(
              "button",
              {
                type: "button",
                class: "btn btn-ghost btn-sm node-move-btn",
                disabled: locked || idx === 0,
                title: "上移一位",
                onclick: () => moveNode(activeMode, idx, -1),
              },
              "↑",
            ),
            h(
              "button",
              {
                type: "button",
                class: "btn btn-ghost btn-sm node-move-btn",
                disabled: locked || idx === list.length - 1,
                title: "下移一位",
                onclick: () => moveNode(activeMode, idx, 1),
              },
              "↓",
            ),
          );

          const enabledSwitch = h(
            "label",
            { class: "switch node-switch", title: "是否输出该节点" },
            h("input", {
              type: "checkbox",
              checked: Boolean(entry.enabled),
              disabled: locked,
              onchange: (e) => toggleField(activeMode, idx, "enabled", e.target.checked),
            }),
            h("span", { class: "switch-track" }),
            h("span", { class: "switch-text" }, entry.enabled ? "启用" : "关闭"),
          );

          const mergeSwitch = h(
            "label",
            {
              class: `switch node-switch ${!supportsMerge ? "is-locked" : ""}`,
              title: !supportsMerge
                ? meta.merge_note || "该节点不支持放入合并转发"
                : "文本模式为 merge/forward 时放入合并转发",
            },
            h("input", {
              type: "checkbox",
              checked: supportsMerge && Boolean(entry.merge),
              disabled: mergeLocked,
              onchange: (e) => toggleField(activeMode, idx, "merge", e.target.checked),
            }),
            h("span", { class: "switch-track" }),
            h(
              "span",
              { class: "switch-text" },
              !supportsMerge ? "不支持合并" : entry.merge ? "放入合并" : "独立发送",
            ),
          );

          return h(
            "div",
            { class: rowClasses.join(" "), "data-node-id": entry.id },
            h("span", { class: "node-order-badge" }, String(idx + 1)),
            h(
              "div",
              { class: "node-main" },
              h(
                "div",
                { class: "node-title-row" },
                h("strong", { class: "node-title" }, meta.label || entry.id),
                store.showDevKeys ? h("code", { class: "dev-key" }, entry.id) : null,
                !supportsMerge
                  ? h("span", { class: "pill pill-warn" }, "不支持合并转发")
                  : entry.id === "video" && entry.merge
                    ? h("span", { class: "pill pill-info" }, "OneBot 合并视频")
                    : null,
              ),
              meta.description ? h("p", { class: "node-desc" }, meta.description) : null,
              meta.merge_note
                ? h(
                    "p",
                    { class: `node-subnote ${!supportsMerge ? "is-warn" : ""}` },
                    meta.merge_note,
                  )
                : null,
            ),
            h("div", { class: "node-controls" }, moveBtns, enabledSwitch, mergeSwitch),
          );
        }),
      ),
    );
  }

  render();
  return { element: root, sync: render };
}
