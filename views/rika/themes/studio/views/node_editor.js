import { h, swapContent, valuesEqual } from "../../../core/dom.js";
import {
  NODE_ZONES,
  buildOrderSummary,
  cloneNodeRules,
  moveNodeBetweenZones,
  normalizeNodeRulesClient,
  rulesEqual,
  serializeNodeRules,
  splitNodeBuckets,
  zoneOfEntry,
} from "../../../core/node_model.js";

const SVG_NS = "http://www.w3.org/2000/svg";

function createGripSvg() {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("width", "12");
  svg.setAttribute("height", "12");
  svg.setAttribute("viewBox", "0 0 12 12");
  svg.setAttribute("fill", "currentColor");
  svg.setAttribute("aria-hidden", "true");
  for (const cx of [3.5, 8.5]) {
    for (const cy of [2, 6, 10]) {
      const dot = document.createElementNS(SVG_NS, "circle");
      dot.setAttribute("cx", String(cx));
      dot.setAttribute("cy", String(cy));
      dot.setAttribute("r", "1.1");
      svg.appendChild(dot);
    }
  }
  return svg;
}

export function createStudioNodeRulesPanel(store, { onAfterChange = null } = {}) {
  const root = h("section", { class: "surface-panel node-editor-panel" });
  let activeMode = "video";
  let selectedId = null;
  let dragState = null;
  let dropTarget = null;

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

  function clearDragIndicators() {
    if (typeof root.querySelectorAll !== "function") return;
    for (const el of root.querySelectorAll(".is-dragging, .is-drop-target, .is-drop-forbidden, .is-drop-before, .is-drop-after")) {
      el.classList.remove(
        "is-dragging",
        "is-drop-target",
        "is-drop-forbidden",
        "is-drop-before",
        "is-drop-after",
      );
    }
  }

  function moveCardToZone(nodeId, targetZone, targetIndex = null, { focusAfter = false } = {}) {
    const schema = getSchema();
    const res = moveNodeBetweenZones({
      rawRules: store.draft.NODE_RULES,
      nodeSchema: schema,
      mode: activeMode,
      nodeId,
      targetZone,
      targetIndex,
    });
    if (!res.ok) {
      if (res.reason) store.toast(res.reason, "warn", 3600);
      return false;
    }
    selectedId = nodeId;
    store.setDraftValue("NODE_RULES", res.serialized);
    render();
    onAfterChange?.();

    if (focusAfter && typeof requestAnimationFrame === "function") {
      requestAnimationFrame(() => {
        root.querySelector(`.node-drag-card[data-node-id="${nodeId}"]`)?.focus?.();
      });
    }
    return true;
  }

  function shiftWithinZone(nodeId, delta, { focusAfter = false } = {}) {
    const schema = getSchema();
    const catalog = schema.catalog || {};
    const current = normalizeNodeRulesClient(store.draft.NODE_RULES, schema);
    const buckets = splitNodeBuckets(current[activeMode] || [], catalog);
    for (const z of NODE_ZONES) {
      const idx = buckets[z.id].indexOf(nodeId);
      if (idx >= 0) {
        const nextIdx = idx + delta;
        if (nextIdx < 0 || nextIdx >= buckets[z.id].length) return false;
        const targetPos = delta > 0 ? nextIdx + 1 : nextIdx;
        return moveCardToZone(nodeId, z.id, targetPos, { focusAfter });
      }
    }
    return false;
  }

  function resetMode(mode) {
    const schema = getSchema();
    const current = normalizeNodeRulesClient(store.draft.NODE_RULES, schema);
    const defaults = schema.defaults || {};
    if (!Array.isArray(defaults[mode])) return;
    current[mode] = cloneNodeRules(defaults[mode]);
    applyUpdatedRules(current);
  }

  function renderQuickBar(buckets, list, catalog, locked) {
    if (!selectedId || !list.some((r) => r.id === selectedId)) {
      return h(
        "div",
        { class: "node-quick-bar is-idle" },
        h(
          "span",
          { class: "node-quick-hint" },
          locked
            ? "当前配置作用域锁定「节点编排」仅全局编辑，请切回全局修改"
            : "拖拽任意小卡片到「单独发 / 合并转发 / 不发」区域，或区内拖动排序；点击小卡片可查看完整说明与快捷移动",
        ),
      );
    }

    const entry = list.find((r) => r.id === selectedId);
    const meta = catalog[selectedId] || { id: selectedId, label: selectedId, supports_merge: true };
    const currentZone = zoneOfEntry(entry, catalog);
    const zoneList = buckets[currentZone] || [];
    const idxInZone = zoneList.indexOf(selectedId);
    const supportsMerge = meta.supports_merge !== false;

    return h(
      "div",
      { class: "node-quick-bar is-active" },
      h(
        "div",
        { class: "node-quick-info" },
        h(
          "div",
          { class: "node-quick-title-row" },
          h("strong", null, meta.label || selectedId),
          store.showDevKeys ? h("code", { class: "dev-key" }, selectedId) : null,
          !supportsMerge ? h("span", { class: "pill pill-warn" }, "不支持合并转发") : null,
        ),
        meta.description ? h("p", { class: "node-quick-desc" }, meta.description) : null,
        meta.merge_note
          ? h("p", { class: `node-quick-note ${!supportsMerge ? "is-warn" : ""}` }, meta.merge_note)
          : null,
      ),
      h(
        "div",
        { class: "node-quick-actions" },
        h(
          "div",
          { class: "seg-group node-zone-switch" },
          NODE_ZONES.map((z) => {
            const isCur = currentZone === z.id;
            const disabledBtn = locked || (z.id === "merge" && !supportsMerge);
            return h(
              "button",
              {
                type: "button",
                class: `seg-btn ${isCur ? "is-active" : ""}`,
                disabled: disabledBtn,
                title:
                  z.id === "merge" && !supportsMerge
                    ? meta.merge_note || "该节点不支持放入合并转发"
                    : `移动到「${z.title}」`,
                onclick: () => {
                  if (!isCur) moveCardToZone(selectedId, z.id);
                },
              },
              z.title,
            );
          }),
        ),
        h(
          "div",
          { class: "btn-group" },
          h(
            "button",
            {
              type: "button",
              class: "btn btn-ghost btn-xs node-order-prev",
              disabled: locked || idxInZone <= 0,
              onclick: () => shiftWithinZone(selectedId, -1),
            },
            "← 前移",
          ),
          h(
            "button",
            {
              type: "button",
              class: "btn btn-ghost btn-xs node-order-next",
              disabled: locked || idxInZone < 0 || idxInZone >= zoneList.length - 1,
              onclick: () => shiftWithinZone(selectedId, 1),
            },
            "后移 →",
          ),
          h(
            "button",
            {
              type: "button",
              class: "btn btn-ghost btn-xs",
              title: "收起详情",
              onclick: () => {
                selectedId = null;
                for (const card of root.querySelectorAll(".node-drag-card")) {
                  card.classList.remove("is-selected");
                }
                const nextQuick = renderQuickBar(buckets, list, catalog, locked);
                const host = root.querySelector(".node-quick-host");
                if (host) swapContent(host, [nextQuick]);
              },
            },
            "×",
          ),
        ),
      ),
    );
  }

  function render() {
    const schema = getSchema();
    const modes = schema.modes || [];
    const catalog = schema.catalog || {};
    const defaults = schema.defaults || {};

    if (!modes.length) {
      swapContent(root, [h("p", { class: "surface-desc" }, "后端未返回节点元数据")]);
      return;
    }
    if (!modes.some((m) => m.id === activeMode)) {
      activeMode = modes[0].id;
    }

    const current = normalizeNodeRulesClient(store.draft.NODE_RULES, schema);
    const list = current[activeMode] || [];
    const modeMeta = modes.find((m) => m.id === activeMode) || modes[0];
    const buckets = splitNodeBuckets(list, catalog);

    if (selectedId && !list.some((r) => r.id === selectedId)) {
      selectedId = null;
    }

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
    if (store.showDevKeys) statusTags.push(h("code", { class: "dev-key" }, "NODE_RULES"));
    if (isGroup && hasOverride) statusTags.push(h("span", { class: "pill pill-info" }, "本群独立"));
    else if (isGroup) statusTags.push(h("span", { class: "pill" }, "继承全局"));
    if (isDirty) statusTags.push(h("span", { class: "pill pill-warn" }, "待保存"));

    const panelNodes = [];
    panelNodes.push(
      h(
        "div",
        { class: "surface-head" },
        h(
          "div",
          null,
          h("div", { class: "setting-label-row" }, h("h2", { class: "surface-title" }, "输出节点编排"), ...statusTags),
          h(
            "p",
            { class: "surface-desc" },
            "按内容形态（视频 / 图文 / 动态文章）拖动小卡片划分去向与发送顺序，零重解析代价，支持分群独立覆盖",
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

    panelNodes.push(
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
                  selectedId = null;
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

    const chunks = buildOrderSummary(list, catalog);
    const webpageFallback = Boolean(store.draft.WEBPAGE_FALLBACK_ENABLED);
    panelNodes.push(
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

    const boardEl = h(
      "div",
      { class: `node-zones-board ${locked ? "is-global-locked" : ""}` },
      NODE_ZONES.map((zone) => {
        const cardIds = buckets[zone.id] || [];
        const zoneEl = h("section", {
          class: `node-zone node-zone-${zone.id}`,
          dataset: { zone: zone.id },
        });
        const cardsHost = h("div", {
          class: "node-zone-cards",
          role: "list",
          "aria-label": zone.title,
        });

        if (!locked) {
          zoneEl.addEventListener("dragover", (e) => {
            const draggingId = dragState?.id;
            const supportsMerge = draggingId ? catalog[draggingId]?.supports_merge !== false : true;
            const forbidden = zone.id === "merge" && !supportsMerge;
            e.preventDefault();
            if (e.dataTransfer) {
              e.dataTransfer.dropEffect = forbidden ? "none" : "move";
            }
            if (forbidden) {
              zoneEl.classList.add("is-drop-forbidden");
              zoneEl.classList.remove("is-drop-target");
              dropTarget = { zone: zone.id, index: cardIds.length, forbidden: true };
              return;
            }
            for (const other of boardEl.querySelectorAll(".node-zone")) {
              if (other !== zoneEl) other.classList.remove("is-drop-target", "is-drop-forbidden");
            }
            for (const c of boardEl.querySelectorAll(".is-drop-before, .is-drop-after")) {
              c.classList.remove("is-drop-before", "is-drop-after");
            }
            zoneEl.classList.remove("is-drop-forbidden");
            zoneEl.classList.add("is-drop-target");

            const cardEl = e.target?.closest?.(".node-drag-card");
            if (!cardEl || !zoneEl.contains(cardEl)) {
              dropTarget = { zone: zone.id, index: cardIds.length, forbidden: false };
            }
          });

          zoneEl.addEventListener("dragleave", (e) => {
            if (!e.relatedTarget || !zoneEl.contains(e.relatedTarget)) {
              zoneEl.classList.remove("is-drop-target", "is-drop-forbidden");
            }
          });

          zoneEl.addEventListener("drop", (e) => {
            e.preventDefault();
            e.stopPropagation();
            const droppedId = dragState?.id || e.dataTransfer?.getData?.("text/plain") || "";
            const targetInfo = dropTarget;
            dragState = null;
            dropTarget = null;
            clearDragIndicators();
            if (!droppedId) return;
            if (targetInfo?.forbidden || (zone.id === "merge" && catalog[droppedId]?.supports_merge === false)) {
              store.toast(catalog[droppedId]?.merge_note || "该节点不支持放入合并转发", "warn", 3600);
              return;
            }
            const targetIdx = targetInfo && targetInfo.zone === zone.id ? targetInfo.index : cardIds.length;
            moveCardToZone(droppedId, zone.id, targetIdx);
          });
        }

        if (cardIds.length === 0) {
          cardsHost.appendChild(h("div", { class: "node-zone-empty" }, zone.emptyHint));
        } else {
          cardIds.forEach((nid, cardIdx) => {
            const meta = catalog[nid] || { id: nid, label: nid, description: "", supports_merge: true };
            const supportsMerge = meta.supports_merge !== false;
            const isSelected = selectedId === nid;
            const tooltipParts = [meta.label || nid];
            if (meta.description) tooltipParts.push(meta.description);
            if (meta.merge_note) tooltipParts.push(meta.merge_note);

            const classes = ["node-drag-card"];
            if (isSelected) classes.push("is-selected");
            if (!supportsMerge) classes.push("is-merge-unsupported");
            if (zone.id === "disabled") classes.push("is-muted");

            const cardEl = h(
              "div",
              {
                class: classes.join(" "),
                role: "listitem",
                tabindex: locked ? "-1" : "0",
                draggable: locked ? "false" : "true",
                title: tooltipParts.join("\n"),
                dataset: { nodeId: nid, zone: zone.id },
                onclick: () => {
                  selectedId = nid;
                  for (const c of boardEl.querySelectorAll(".node-drag-card")) {
                    c.classList.toggle("is-selected", c.getAttribute("data-node-id") === nid);
                  }
                  const host = root.querySelector(".node-quick-host");
                  if (host) {
                    swapContent(host, [renderQuickBar(buckets, list, catalog, locked)]);
                  }
                },
              },
              h("span", { class: "node-drag-grip", "aria-hidden": "true" }, createGripSvg()),
              zone.id !== "disabled" ? h("span", { class: "node-card-idx" }, String(cardIdx + 1)) : null,
              h("span", { class: "node-card-name" }, meta.label || nid),
              !supportsMerge
                ? h("span", { class: "node-card-badge is-warn" }, "禁合并")
                : nid === "video" && zone.id === "merge"
                  ? h("span", { class: "node-card-badge is-info" }, "OneBot合并")
                  : null,
              store.showDevKeys ? h("code", { class: "dev-key node-card-key" }, nid) : null,
            );

            if (!locked) {
              cardEl.addEventListener("dragstart", (e) => {
                dragState = { id: nid, sourceZone: zone.id };
                dropTarget = { zone: zone.id, index: cardIdx, forbidden: false };
                if (e.dataTransfer) {
                  e.dataTransfer.effectAllowed = "move";
                  e.dataTransfer.setData("text/plain", nid);
                }
                if (typeof requestAnimationFrame === "function") {
                  requestAnimationFrame(() => cardEl.classList.add("is-dragging"));
                } else {
                  cardEl.classList.add("is-dragging");
                }
                if (!supportsMerge) {
                  boardEl.querySelector('.node-zone[data-zone="merge"]')?.classList.add("is-merge-blocked");
                }
              });

              cardEl.addEventListener("dragend", () => {
                dragState = null;
                dropTarget = null;
                clearDragIndicators();
                boardEl.querySelector('.node-zone[data-zone="merge"]')?.classList.remove("is-merge-blocked");
              });

              cardEl.addEventListener("dragover", (e) => {
                const draggingId = dragState?.id;
                if (!draggingId) return;
                const draggingSupportsMerge = catalog[draggingId]?.supports_merge !== false;
                if (zone.id === "merge" && !draggingSupportsMerge) return;

                e.preventDefault();
                e.stopPropagation();
                if (e.dataTransfer) e.dataTransfer.dropEffect = "move";

                for (const other of boardEl.querySelectorAll(".node-zone")) {
                  if (other !== zoneEl) other.classList.remove("is-drop-target", "is-drop-forbidden");
                }
                zoneEl.classList.add("is-drop-target");
                for (const c of boardEl.querySelectorAll(".is-drop-before, .is-drop-after")) {
                  c.classList.remove("is-drop-before", "is-drop-after");
                }

                if (draggingId === nid) {
                  dropTarget = { zone: zone.id, index: cardIdx, forbidden: false };
                  return;
                }

                const rect = cardEl.getBoundingClientRect?.();
                const hostRect = cardsHost.getBoundingClientRect?.();
                let isAfter = false;
                if (rect && rect.width > 0) {
                  if (hostRect && rect.width > hostRect.width * 0.72) {
                    isAfter = e.clientY - rect.top > rect.height * 0.5;
                  } else {
                    isAfter = e.clientX - rect.left > rect.width * 0.5;
                  }
                }
                cardEl.classList.add(isAfter ? "is-drop-after" : "is-drop-before");
                dropTarget = {
                  zone: zone.id,
                  index: isAfter ? cardIdx + 1 : cardIdx,
                  forbidden: false,
                };
              });

              cardEl.addEventListener("keydown", (e) => {
                if (e.key === "ArrowUp") {
                  e.preventDefault();
                  shiftWithinZone(nid, -1, { focusAfter: true });
                } else if (e.key === "ArrowDown") {
                  e.preventDefault();
                  shiftWithinZone(nid, 1, { focusAfter: true });
                } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
                  e.preventDefault();
                  const order = NODE_ZONES.map((z) => z.id);
                  const curIdx = order.indexOf(zone.id);
                  const step = e.key === "ArrowRight" ? 1 : -1;
                  const nextIdx = curIdx + step;
                  if (nextIdx < 0 || nextIdx >= order.length) return;
                  let nextZone = order[nextIdx];
                  if (nextZone === "merge" && !supportsMerge) {
                    const skippedIdx = nextIdx + step;
                    if (skippedIdx >= 0 && skippedIdx < order.length) {
                      nextZone = order[skippedIdx];
                    } else {
                      store.toast(meta.merge_note || "该节点不支持放入合并转发", "warn", 3200);
                      return;
                    }
                  }
                  moveCardToZone(nid, nextZone, null, { focusAfter: true });
                }
              });
            }

            cardsHost.appendChild(cardEl);
          });
        }

        zoneEl.appendChild(
          h(
            "header",
            { class: "node-zone-head" },
            h(
              "div",
              { class: "node-zone-title-row" },
              h("span", { class: `node-zone-dot dot-${zone.id}` }),
              h("strong", { class: "node-zone-title" }, zone.title),
              h("span", { class: "node-zone-count" }, String(cardIds.length)),
            ),
            h("span", { class: "node-zone-sub" }, zone.subtitle),
          ),
        );
        zoneEl.appendChild(cardsHost);
        return zoneEl;
      }),
    );

    const quickHost = h(
      "div",
      { class: "node-quick-host" },
      renderQuickBar(buckets, list, catalog, locked),
    );
    panelNodes.push(boardEl, quickHost);
    swapContent(root, panelNodes);
  }

  render();
  return { element: root, sync: render };
}
