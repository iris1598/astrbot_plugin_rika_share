import { valuesEqual } from "./dom.js";

export function cloneValues(values) {
  const out = {};
  for (const [k, v] of Object.entries(values || {})) {
    out[k] = Array.isArray(v) ? [...v] : v;
  }
  return out;
}

export function parseDisabledPlatforms(raw) {
  return new Set(
    String(raw || "")
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean),
  );
}

/**
 * 创建纯无头应用状态仓库（Store）。
 *
 * 维护配置草稿、分群稀疏覆写作用域、平台列表、状态总览与保存/重置工作流，
 * 通过订阅机制向当前挂载的网页主题广播状态变化。
 */
export function createAppStore({ bridge, toast, context, configPayload, overviewPayload }) {
  const listeners = new Set();

  function emit(event) {
    for (const fn of Array.from(listeners)) {
      try {
        fn(event);
      } catch (err) {
        console.error("[RikaWebUI] store subscriber error:", err);
      }
    }
  }

  const store = {
    bridge,
    toast,
    context: context || {},
    systemIsDark: Boolean(context?.isDark),
    meta: configPayload,
    scope: String(configPayload.scope || ""),
    scopeLabel: String(configPayload.scope_label || "全局默认"),
    globalValues: cloneValues(configPayload.global_values || configPayload.values),
    overrideKeys: new Set(configPayload.override_keys || []),
    overridableSet: new Set(configPayload.group_overridable_keys || []),
    pendingUnset: new Set(),
    groupProfiles: Array.isArray(configPayload.group_profiles) ? configPayload.group_profiles : [],
    draft: cloneValues(configPayload.values),
    overview: overviewPayload || null,
    showDevKeys: false,
    scopeBusy: false,
    saving: false,

    subscribe(listener) {
      if (typeof listener !== "function") return () => {};
      listeners.add(listener);
      return () => listeners.delete(listener);
    },

    itemMap() {
      const map = new Map();
      for (const item of store.meta?.items || []) map.set(item.key, item);
      return map;
    },

    itemsByGroup() {
      const groups = new Map();
      for (const item of store.meta?.items || []) {
        const g = item.group || "default";
        if (!groups.has(g)) groups.set(g, []);
        groups.get(g).push(item);
      }
      return groups;
    },

    isOverridable(key) {
      return store.overridableSet.has(key);
    },

    isKeyOverridden(key) {
      return (
        Boolean(store.scope) &&
        store.overridableSet.has(key) &&
        store.overrideKeys.has(key) &&
        !store.pendingUnset.has(key)
      );
    },

    isKeyDirty(key) {
      if (store.scope && !store.overridableSet.has(key)) return false;
      const saved = store.meta?.values?.[key];
      return store.pendingUnset.has(key) || !valuesEqual(store.draft[key], saved);
    },

    dirtyKeys() {
      const saved = store.meta?.values || {};
      const changed = [];
      for (const item of store.meta?.items || []) {
        const k = item.key;
        if (store.scope && !store.overridableSet.has(k)) continue;
        if (store.pendingUnset.has(k) || !valuesEqual(store.draft[k], saved[k])) {
          changed.push(k);
        }
      }
      return changed;
    },

    disabledPlatformSet() {
      return parseDisabledPlatforms(store.draft.DISABLED_PLATFORMS);
    },

    isPlatformEnabled(name) {
      return !store.disabledPlatformSet().has(String(name || "").toLowerCase());
    },

    togglePlatform(name) {
      const next = store.disabledPlatformSet();
      const key = String(name || "").toLowerCase();
      if (!key) return;
      if (next.has(key)) next.delete(key);
      else next.add(key);
      store.setDraftValue("DISABLED_PLATFORMS", Array.from(next).sort().join(", "));
    },

    setAllPlatformsEnabled(enabled) {
      if (enabled) {
        store.setDraftValue("DISABLED_PLATFORMS", "");
      } else {
        const all = (store.meta?.platforms || []).map((p) => p.name.toLowerCase()).sort().join(", ");
        store.setDraftValue("DISABLED_PLATFORMS", all);
      }
    },

    setShowDevKeys(enabled) {
      store.showDevKeys = Boolean(enabled);
      emit({ type: "devkeys", showDevKeys: store.showDevKeys });
    },

    updateContext(nextCtx) {
      store.context = nextCtx || {};
      store.systemIsDark = Boolean(nextCtx?.isDark);
      emit({ type: "context", context: store.context, systemIsDark: store.systemIsDark });
    },

    applyConfigSnapshot(res) {
      if (!res) return;
      if (res.scope !== undefined) {
        store.scope = String(res.scope || "");
      }
      store.scopeLabel = String(res.scope_label || (store.scope ? store.scope : "全局默认"));
      if (res.values) {
        store.meta.values = res.values;
        store.draft = cloneValues(res.values);
      }
      if (res.global_values) {
        store.globalValues = cloneValues(res.global_values);
      } else if (!store.scope && res.values) {
        store.globalValues = cloneValues(res.values);
      }
      if (Array.isArray(res.override_keys)) {
        store.overrideKeys = new Set(res.override_keys);
      } else if (!store.scope) {
        store.overrideKeys = new Set();
      }
      store.pendingUnset.clear();
      if (Array.isArray(res.group_overridable_keys)) {
        store.overridableSet = new Set(res.group_overridable_keys);
      }
      if (Array.isArray(res.group_profiles)) {
        store.groupProfiles = res.group_profiles;
      }
      if (res.node_schema) {
        store.meta.node_schema = res.node_schema;
      }
      if (Array.isArray(res.webui_themes)) {
        store.meta.webui_themes = res.webui_themes;
      }
      if (Array.isArray(store.meta.platforms)) {
        const disabledSet = parseDisabledPlatforms(store.meta.values?.DISABLED_PLATFORMS);
        store.meta.platforms = store.meta.platforms.map((p) => ({
          ...p,
          enabled: !disabledSet.has(p.name.toLowerCase()),
        }));
      }
      emit({ type: "snapshot" });
    },

    setDraftValue(key, val, { rerender = true } = {}) {
      if (store.scope && !store.overridableSet.has(key)) {
        toast("该配置项仅全局生效，请切回「全局默认」修改", "warn");
        return false;
      }
      store.pendingUnset.delete(key);
      store.draft[key] = val;
      emit({ type: "draft", key, value: val, rerender });
      return true;
    },

    revertKeyToInherit(key) {
      if (!store.scope || !store.overridableSet.has(key)) return;
      const gVal = store.globalValues?.[key];
      store.draft[key] = Array.isArray(gVal) ? [...gVal] : gVal;
      if (store.overrideKeys.has(key)) {
        store.pendingUnset.add(key);
      } else {
        store.pendingUnset.delete(key);
      }
      emit({ type: "draft", key, value: store.draft[key], rerender: true, reverted: true });
    },

    discardDraft() {
      store.pendingUnset.clear();
      store.draft = cloneValues(store.meta.values);
      emit({ type: "discard" });
      toast("已放弃未保存改动", "info");
    },

    async switchScope(nextScope) {
      const target = String(nextScope || "").trim();
      if (target === store.scope) {
        emit({ type: "scope" });
        return false;
      }
      if (store.dirtyKeys().length > 0) {
        toast("当前作用域有未保存改动，请先保存或点击放弃后再切换", "warn");
        emit({ type: "scope" });
        return false;
      }
      store.scopeBusy = true;
      emit({ type: "scope" });
      try {
        const [cfgRes, ovRes] = await Promise.all([
          bridge.apiGet("config", { scope: target }),
          bridge.apiGet("overview", { scope: target }).catch(() => null),
        ]);
        if (ovRes) store.overview = ovRes;
        if (cfgRes) store.applyConfigSnapshot(cfgRes);
        toast(`已切换配置作用域：${store.scopeLabel}`, "info");
        return true;
      } catch (err) {
        toast(`切换作用域失败：${err.message || err}`, "err");
        return false;
      } finally {
        store.scopeBusy = false;
        emit({ type: "scope" });
      }
    },

    async createGroupScope(rawScope, label) {
      const trimmed = String(rawScope || "").trim();
      if (!trimmed) {
        toast("请输入群号（如 123456）或 UMO 标识", "warn");
        return false;
      }
      if (store.dirtyKeys().length > 0) {
        toast("当前作用域有未保存改动，请先保存或点击放弃", "warn");
        return false;
      }
      store.scopeBusy = true;
      emit({ type: "scope" });
      try {
        const res = await bridge.apiPost("groups", {
          action: "create",
          scope: trimmed,
          label: String(label || "").trim(),
        });
        if (res?.errors?.length) {
          toast(res.errors[0], "err");
          return false;
        }
        if (Array.isArray(res?.groups)) {
          store.groupProfiles = res.groups;
        }
        store.scopeBusy = false;
        await store.switchScope(res.scope || trimmed);
        return true;
      } catch (err) {
        toast(`添加分群失败：${err.message || err}`, "err");
        return false;
      } finally {
        store.scopeBusy = false;
        emit({ type: "scope" });
      }
    },

    async deleteGroupScope(targetScope) {
      const target = String(targetScope || "").trim();
      if (!target) return false;
      store.scopeBusy = true;
      emit({ type: "scope" });
      try {
        const res = await bridge.apiPost("groups", { action: "delete", scope: target });
        if (res?.errors?.length) {
          toast(res.errors[0], "err");
          return false;
        }
        if (Array.isArray(res?.groups)) {
          store.groupProfiles = res.groups;
        }
        if (target === store.scope) {
          store.pendingUnset.clear();
          store.draft = cloneValues(store.meta.values);
          store.scopeBusy = false;
          await store.switchScope("");
        } else {
          emit({ type: "scope" });
          toast("已移除该分群档案", "ok");
        }
        return true;
      } catch (err) {
        toast(`移除分群档案失败：${err.message || err}`, "err");
        return false;
      } finally {
        store.scopeBusy = false;
        emit({ type: "scope" });
      }
    },

    async refreshOverview(notify = false) {
      try {
        store.overview = await bridge.apiGet("overview", { scope: store.scope });
        emit({ type: "overview" });
        if (notify) toast("运行状态已刷新", "ok");
        return true;
      } catch (err) {
        if (notify) toast(`刷新失败：${err.message || err}`, "err");
        return false;
      }
    },

    async saveDirty() {
      const changed = store.dirtyKeys();
      if (changed.length === 0 || store.saving) return false;
      store.saving = true;
      emit({ type: "saving", saving: true });
      try {
        const payload = {};
        const unset = [];
        for (const k of changed) {
          if (store.scope && store.pendingUnset.has(k)) {
            unset.push(k);
          } else {
            payload[k] = store.draft[k];
          }
        }
        const res = await bridge.apiPost("config", {
          scope: store.scope,
          values: payload,
          ...(unset.length ? { unset } : {}),
        });
        if (res?.values) {
          store.applyConfigSnapshot(res);
        }
        store.refreshOverview(false);
        const errs = res?.errors || [];
        if (errs.length > 0) {
          toast(`保存提醒：${errs[0]}`, "warn", 4800);
        } else if (store.scope) {
          toast(`已更新「${store.scopeLabel}」分群设置并热生效`, "ok");
        } else {
          toast(`已保存 ${res?.changed?.length ?? changed.length} 项全局设置并热更新`, "ok");
        }
        return true;
      } catch (err) {
        toast(`保存失败：${err.message || err}`, "err");
        return false;
      } finally {
        store.saving = false;
        emit({ type: "saving", saving: false });
      }
    },

    async resetConfig() {
      if (store.saving) return false;
      store.saving = true;
      emit({ type: "saving", saving: true });
      try {
        const res = await bridge.apiPost("config/reset", { scope: store.scope });
        if (res?.values) {
          store.applyConfigSnapshot(res);
        }
        store.refreshOverview(false);
        toast(store.scope ? "已清空本群独立覆写并恢复继承全局" : "已恢复全部默认设置", "ok");
        return true;
      } catch (err) {
        toast(`恢复默认失败：${err.message || err}`, "err");
        return false;
      } finally {
        store.saving = false;
        emit({ type: "saving", saving: false });
      }
    },
  };

  return store;
}
