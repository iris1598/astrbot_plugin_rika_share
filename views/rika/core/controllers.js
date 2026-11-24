/**
 * 纯无头（Headless）异步业务控制器集合。
 *
 * 包含 B站账号/扫码轮询、实时卡片与样式预览、只读链接诊断探针、缓存清理；
 * 不假设任何 DOM 结构，供所有主题复用或定制交互流程。
 */

function makeEmitter() {
  const subs = new Set();
  return {
    subscribe(fn) {
      if (typeof fn !== "function") return () => {};
      subs.add(fn);
      return () => subs.delete(fn);
    },
    emit(state) {
      for (const fn of Array.from(subs)) {
        try {
          fn(state);
        } catch (err) {
          console.error("[RikaWebUI] controller subscriber error:", err);
        }
      }
    },
    clear() {
      subs.clear();
    },
  };
}

export function createBiliController(store) {
  const bus = makeEmitter();
  const state = {
    busyCheck: false,
    busyQr: false,
    qrSession: null,
  };
  let pollTimer = null;

  function applyBiliOverview(res) {
    if (res?.bili) {
      store.overview = { ...(store.overview || {}), bili: res.bili };
      bus.emit(state);
    }
  }

  function stopPolling() {
    if (pollTimer) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  async function pollOnce() {
    if (!state.qrSession?.qrcode_key) return;
    try {
      const res = await store.bridge.apiGet("bili/status", {
        qrcode_key: state.qrSession.qrcode_key,
      });
      applyBiliOverview(res);
      if (res?.qr) {
        state.qrSession = { ...state.qrSession, ...res.qr };
        if (!res.qr.active) {
          stopPolling();
          if (res.qr.state === "success") {
            store.toast(res.qr.message || "B站扫码登录成功！", "ok", 4200);
            store.refreshOverview(false);
          } else if (res.qr.state === "expired") {
            store.toast("登录二维码已过期，请点击刷新", "warn");
          }
        }
        bus.emit(state);
      }
    } catch {
      // 网络短暂抖动等待下次轮询
    }
  }

  function startPolling() {
    stopPolling();
    if (!state.qrSession?.active || !state.qrSession?.qrcode_key) return;
    pollTimer = window.setInterval(pollOnce, 2500);
  }

  return {
    getState: () => ({ ...state, bili: store.overview?.bili || {} }),
    subscribe: bus.subscribe,

    async refreshStatus() {
      try {
        const res = await store.bridge.apiGet("bili/status", {});
        applyBiliOverview(res);
        if (res?.qr && res.qr.active) {
          state.qrSession = { ...(state.qrSession || {}), ...res.qr };
          startPolling();
        }
        bus.emit(state);
      } catch (err) {
        store.toast(`获取B站状态失败：${err.message || err}`, "err");
      }
    },

    async checkCookie() {
      if (state.busyCheck) return;
      state.busyCheck = true;
      bus.emit(state);
      try {
        const res = await store.bridge.apiPost("bili/check", {});
        applyBiliOverview(res);
        if (res?.checked === false) {
          store.toast(res.message || "尚未配置B站 Cookie", "warn");
        } else if (res?.result?.valid) {
          store.toast(`B站 Cookie 有效（${res.result.username || "已登录"}）`, "ok");
        } else {
          store.toast(`Cookie 已失效：${res?.result?.error || "请重新扫码"}`, "err");
        }
      } catch (err) {
        store.toast(`检测失败：${err.message || err}`, "err");
      } finally {
        state.busyCheck = false;
        bus.emit(state);
      }
    },

    async startQrLogin() {
      if (state.busyQr) return;
      state.busyQr = true;
      bus.emit(state);
      try {
        const res = await store.bridge.apiPost("bili/login", { action: "start" });
        applyBiliOverview(res);
        state.qrSession = res?.qr || null;
        if (state.qrSession?.active) {
          startPolling();
        }
      } catch (err) {
        store.toast(`获取二维码失败：${err.message || err}`, "err");
      } finally {
        state.busyQr = false;
        bus.emit(state);
      }
    },

    async cancelQrLogin() {
      stopPolling();
      state.qrSession = null;
      bus.emit(state);
      try {
        const res = await store.bridge.apiPost("bili/login", { action: "cancel" });
        applyBiliOverview(res);
      } catch {
        // 关闭面板不阻塞前端交互
      }
    },

    stopPolling,

    dispose() {
      stopPolling();
      bus.clear();
    },
  };
}

export function createPreviewController(store) {
  const bus = makeEmitter();
  const state = {
    sampleId: "video",
    personaName: "达妮娅",
    loading: false,
    error: "",
    data: null,
    thumbsLoading: false,
    thumbsTheme: "",
    thumbsPersonaKey: "",
    thumbs: [],
  };
  let debounceTimer = null;
  let previewReqSeq = 0;

  async function fetchCardNow() {
    const seq = ++previewReqSeq;
    state.loading = true;
    state.error = "";
    bus.emit(state);
    try {
      const data = await store.bridge.apiPost("preview/card", {
        sample: state.sampleId,
        style: store.draft.RENDER_STYLE || "standard",
        theme: store.draft.RENDER_THEME === "light" ? "light" : "dark",
        width: Number(store.draft.RENDER_WIDTH || 800),
        cover_full_size: Boolean(store.draft.RENDER_COVER_FULL_SIZE),
        font_path: String(store.draft.RENDER_FONT_PATH || ""),
        persona_watermark: Boolean(store.draft.RENDER_PERSONA_WATERMARK),
        persona_name: state.personaName.trim() || "达妮娅",
        brand_name: String(store.draft.RENDER_BRAND_NAME || "").trim() || "莉卡解析",
      });
      if (seq !== previewReqSeq) return;
      state.loading = false;
      state.error = "";
      state.data = data;
    } catch (err) {
      if (seq !== previewReqSeq) return;
      state.loading = false;
      state.error = err?.message || String(err);
    }
    bus.emit(state);
  }

  function scheduleCard(delayMs = 0) {
    if (debounceTimer) window.clearTimeout(debounceTimer);
    if (delayMs <= 0) {
      fetchCardNow();
      return;
    }
    debounceTimer = window.setTimeout(() => {
      debounceTimer = null;
      fetchCardNow();
    }, delayMs);
  }

  async function fetchStyleThumbs(force = false) {
    const theme = store.draft.RENDER_THEME === "light" ? "light" : "dark";
    const pOn = Boolean(store.draft.RENDER_PERSONA_WATERMARK);
    const pName = state.personaName.trim() || "达妮娅";
    const bName = String(store.draft.RENDER_BRAND_NAME || "").trim() || "莉卡解析";
    const personaKey = pOn ? `p:${pName}:${bName}` : `b:${bName}`;
    if (
      !force &&
      state.thumbsTheme === theme &&
      state.thumbsPersonaKey === personaKey &&
      state.thumbs.length > 0
    ) {
      return;
    }
    if (state.thumbsLoading) return;
    state.thumbsLoading = true;
    bus.emit(state);
    try {
      const res = await store.bridge.apiGet("preview/styles", {
        theme,
        persona_watermark: pOn ? "1" : "0",
        persona_name: pName,
        brand_name: bName,
      });
      state.thumbsTheme = theme;
      state.thumbsPersonaKey = personaKey;
      state.thumbsLoading = false;
      state.thumbs = res?.styles || [];
    } catch {
      state.thumbsLoading = false;
    }
    bus.emit(state);
  }

  return {
    getState: () => ({ ...state }),
    subscribe: bus.subscribe,
    scheduleCard,
    fetchStyleThumbs,

    setSampleId(id) {
      state.sampleId = id;
      scheduleCard(0);
    },

    setPersonaName(name) {
      state.personaName = String(name ?? "");
      scheduleCard(240);
      fetchStyleThumbs(true);
    },

    dispose() {
      if (debounceTimer) {
        window.clearTimeout(debounceTimer);
        debounceTimer = null;
      }
      bus.clear();
    },
  };
}

export function createDebugController(store) {
  const bus = makeEmitter();
  const state = {
    url: "",
    downloadMedia: true,
    renderCard: true,
    running: false,
    error: "",
    report: null,
  };

  return {
    getState: () => ({ ...state }),
    subscribe: bus.subscribe,

    setUrl(url) {
      state.url = String(url ?? "");
    },

    setDownloadMedia(enabled) {
      state.downloadMedia = Boolean(enabled);
      bus.emit(state);
    },

    setRenderCard(enabled) {
      state.renderCard = Boolean(enabled);
      bus.emit(state);
    },

    async runProbe() {
      const trimmed = state.url.trim();
      if (!trimmed) {
        store.toast("请先输入需要诊断的链接", "warn");
        return false;
      }
      state.running = true;
      state.error = "";
      bus.emit(state);
      try {
        state.report = await store.bridge.apiPost("debug/run", {
          scope: store.scope,
          url: trimmed,
          download_media: state.downloadMedia,
          render_card: state.renderCard,
        });
        return true;
      } catch (err) {
        state.error = err?.message || String(err);
        store.toast(`诊断执行失败：${state.error}`, "err");
        return false;
      } finally {
        state.running = false;
        bus.emit(state);
      }
    },

    async downloadLog(token, logName) {
      try {
        await store.bridge.download(
          "debug/log",
          { token },
          logName || `rika_debug_${token}.log`,
        );
      } catch (err) {
        store.toast(`下载日志失败：${err.message || err}`, "err");
      }
    },

    dispose() {
      bus.clear();
    },
  };
}

export function createCacheController(store) {
  const bus = makeEmitter();
  const state = { clearing: false };

  return {
    getState: () => ({ ...state }),
    subscribe: bus.subscribe,

    async clearAll() {
      if (state.clearing) return;
      state.clearing = true;
      bus.emit(state);
      try {
        const res = await store.bridge.apiPost("cache/clear", {});
        if (store.overview && res?.cache) {
          store.overview = {
            ...store.overview,
            cache: res.cache,
            webpage_share: {
              ...(store.overview.webpage_share || {}),
              active_links: res.cache.active_webpage_links ?? 0,
            },
          };
        }
        store.toast(`已清理 ${res?.cleaned ?? 0} 个缓存文件`, "ok");
        store.refreshOverview(false);
      } catch (err) {
        store.toast(`清理缓存失败：${err.message || err}`, "err");
      } finally {
        state.clearing = false;
        bus.emit(state);
      }
    },

    dispose() {
      bus.clear();
    },
  };
}
