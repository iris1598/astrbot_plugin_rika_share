/**
 * 纯无头（Headless）输出节点编排数据模型。
 *
 * 与具体 UI 样式及 DOM 完全解耦，供任意网页主题按自己的布局方式渲染
 * （看板拖拽、分段列表、开关矩阵或紧凑抽屉等）并保持统一后端序列化格式。
 */

export const NODE_ZONES = [
  {
    id: "standalone",
    title: "单独发",
    subtitle: "按顺序各自独立发送",
    emptyHint: "拖入或移入节点后将逐条独立发出",
  },
  {
    id: "merge",
    title: "合并转发",
    subtitle: "连续合并项打包为转发消息",
    emptyHint: "拖入或移入节点以放入同一条合并转发",
  },
  {
    id: "disabled",
    title: "不发",
    subtitle: "解析后跳过该节点内容",
    emptyHint: "当前模式节点已全部启用",
  },
];

const MEDIA_TAIL_IDS = new Set(["video", "audio", "music_card"]);

export function cloneNodeRules(obj) {
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

export function zoneOfEntry(entry, catalog) {
  if (!entry?.enabled) return "disabled";
  const supportsMerge = catalog[entry.id]?.supports_merge !== false;
  return supportsMerge && entry.merge ? "merge" : "standalone";
}

export function splitNodeBuckets(list, catalog) {
  const buckets = { standalone: [], merge: [], disabled: [] };
  for (const entry of list || []) {
    buckets[zoneOfEntry(entry, catalog)].push(entry.id);
  }
  return buckets;
}

export function rebuildRulesFromBuckets(buckets, prevList, defList, catalog) {
  const defById = new Map((defList || []).map((r) => [r.id, r]));
  const prevById = new Map((prevList || []).map((r) => [r.id, r]));

  const standaloneRules = buckets.standalone.map((id) => ({
    id,
    enabled: true,
    merge: false,
  }));
  const mergeRules = buckets.merge
    .filter((id) => catalog[id]?.supports_merge !== false)
    .map((id) => ({
      id,
      enabled: true,
      merge: true,
    }));
  const disabledRules = buckets.disabled.map((id) => ({
    id,
    enabled: false,
    merge:
      Boolean(defById.get(id)?.merge ?? prevById.get(id)?.merge ?? false) &&
      catalog[id]?.supports_merge !== false,
  }));

  let activeRules;
  if (mergeRules.length === 0) {
    activeRules = standaloneRules;
  } else {
    const firstMerge = (prevList || []).findIndex(
      (r) => r.enabled && r.merge && catalog[r.id]?.supports_merge !== false,
    );
    let splitIdx = -1;
    if (firstMerge === -1) {
      let i = standaloneRules.length;
      while (i > 0 && MEDIA_TAIL_IDS.has(standaloneRules[i - 1].id)) {
        i -= 1;
      }
      splitIdx = i < standaloneRules.length ? i : -1;
    } else {
      const prevBeforeIds = new Set(
        prevList
          .slice(0, firstMerge)
          .filter((r) => r.enabled && !r.merge)
          .map((r) => r.id),
      );
      const prevAfterIds = new Set(
        prevList
          .slice(firstMerge + 1)
          .filter((r) => r.enabled && !r.merge)
          .map((r) => r.id),
      );
      let lastBeforeIdx = -1;
      standaloneRules.forEach((r, idx) => {
        if (prevBeforeIds.has(r.id)) lastBeforeIdx = idx;
      });
      for (let i = lastBeforeIdx + 1; i < standaloneRules.length; i += 1) {
        const nid = standaloneRules[i].id;
        if (prevAfterIds.has(nid) || MEDIA_TAIL_IDS.has(nid)) {
          splitIdx = i;
          break;
        }
      }
    }

    if (splitIdx === -1) {
      activeRules = [...standaloneRules, ...mergeRules];
    } else {
      activeRules = [
        ...standaloneRules.slice(0, splitIdx),
        ...mergeRules,
        ...standaloneRules.slice(splitIdx),
      ];
    }
  }

  const defaultActive = (defList || []).filter((r) => r.enabled);
  const sameActive =
    activeRules.length === defaultActive.length &&
    activeRules.every(
      (r, idx) =>
        r.id === defaultActive[idx].id &&
        r.enabled === defaultActive[idx].enabled &&
        r.merge === (catalog[r.id]?.supports_merge !== false && Boolean(defaultActive[idx].merge)),
    );
  if (sameActive) {
    return cloneNodeRules(defList);
  }

  return [...activeRules, ...disabledRules];
}

export function moveNodeBetweenZones({
  rawRules,
  nodeSchema,
  mode,
  nodeId,
  targetZone,
  targetIndex = null,
}) {
  const catalog = nodeSchema?.catalog || {};
  const defaults = nodeSchema?.defaults || {};
  const meta = catalog[nodeId] || {};

  if (targetZone === "merge" && meta.supports_merge === false) {
    return {
      ok: false,
      reason: meta.merge_note || "该节点不支持放入合并转发",
      serialized: serializeNodeRules(normalizeNodeRulesClient(rawRules, nodeSchema), nodeSchema),
    };
  }

  const current = normalizeNodeRulesClient(rawRules, nodeSchema);
  const prevList = current[mode] || [];
  const buckets = splitNodeBuckets(prevList, catalog);

  let fromZone = null;
  let fromIndex = -1;
  for (const z of NODE_ZONES) {
    const idx = buckets[z.id].indexOf(nodeId);
    if (idx >= 0) {
      fromZone = z.id;
      fromIndex = idx;
      break;
    }
  }
  if (!fromZone) {
    return { ok: false, reason: "未找到目标节点", serialized: serializeNodeRules(current, nodeSchema) };
  }

  buckets[fromZone].splice(fromIndex, 1);

  let insertAt = targetIndex == null ? buckets[targetZone].length : Number(targetIndex);
  if (fromZone === targetZone && insertAt > fromIndex) {
    insertAt -= 1;
  }
  insertAt = Math.max(0, Math.min(buckets[targetZone].length, insertAt));
  buckets[targetZone].splice(insertAt, 0, nodeId);

  current[mode] = rebuildRulesFromBuckets(buckets, prevList, defaults[mode] || [], catalog);
  return {
    ok: true,
    rules: current,
    serialized: serializeNodeRules(current, nodeSchema),
  };
}

export function buildOrderSummary(list, catalog) {
  const enabled = (list || []).filter((entry) => entry.enabled);
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
