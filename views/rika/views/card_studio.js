import { buildControlRow, clear, h, icon } from "../ui.js";

const DELIVERY_CACHE_KEYS = [
  "WEBPAGE_FALLBACK_ENABLED",
  "WEBPAGE_TDOCS_JUMP",
  "CACHE_TTL_HOURS",
  "CACHE_CLEANUP_INTERVAL_MINUTES",
];

export function createCardStudioView(store) {
  const root = h("div", { class: "page-stack" });

  let sampleId = "video";
  let previewPersonaName = "达妮娅";
  let previewState = { loading: false, error: "", data: null };
  let thumbsState = { theme: "", personaKey: "", items: null, loading: false };
  let modalImageUrl = null;
  let debounceTimer = null;
  let previewReqSeq = 0;

  function itemsMap() {
    const map = new Map();
    for (const item of store.meta?.items || []) map.set(item.key, item);
    return map;
  }

  function schedulePreview(delayMs = 0) {
    if (debounceTimer) window.clearTimeout(debounceTimer);
    if (delayMs <= 0) {
      fetchLivePreview();
      return;
    }
    debounceTimer = window.setTimeout(() => {
      debounceTimer = null;
      fetchLivePreview();
    }, delayMs);
  }

  async function fetchStyleThumbs(force = false) {
    const theme = store.draft.RENDER_THEME === "light" ? "light" : "dark";
    const pOn = Boolean(store.draft.RENDER_PERSONA_WATERMARK);
    const pName = previewPersonaName.trim() || "达妮娅";
    const bName = String(store.draft.RENDER_BRAND_NAME || "").trim() || "莉卡解析";
    const personaKey = pOn ? `p:${pName}:${bName}` : `b:${bName}`;
    if (!force && thumbsState.theme === theme && thumbsState.personaKey === personaKey && thumbsState.items) {
      return;
    }
    if (thumbsState.loading) return;
    thumbsState.loading = true;
    try {
      const res = await store.bridge.apiGet("preview/styles", {
        theme,
        persona_watermark: pOn ? "1" : "0",
        persona_name: pName,
        brand_name: bName,
      });
      thumbsState = {
        theme,
        personaKey,
        loading: false,
        items: res?.styles || [],
      };
      render();
    } catch {
      thumbsState.loading = false;
    }
  }

  async function fetchLivePreview() {
    const seq = ++previewReqSeq;
    previewState = { ...previewState, loading: true, error: "" };
    updatePreviewStage();

    try {
      const data = await store.bridge.apiPost("preview/card", {
        sample: sampleId,
        style: store.draft.RENDER_STYLE || "standard",
        theme: store.draft.RENDER_THEME === "light" ? "light" : "dark",
        width: Number(store.draft.RENDER_WIDTH || 800),
        cover_full_size: Boolean(store.draft.RENDER_COVER_FULL_SIZE),
        font_path: String(store.draft.RENDER_FONT_PATH || ""),
        persona_watermark: Boolean(store.draft.RENDER_PERSONA_WATERMARK),
        persona_name: previewPersonaName.trim() || "达妮娅",
        brand_name: String(store.draft.RENDER_BRAND_NAME || "").trim() || "莉卡解析",
      });
      if (seq !== previewReqSeq) return;
      previewState = { loading: false, error: "", data };
    } catch (err) {
      if (seq !== previewReqSeq) return;
      previewState = {
        loading: false,
        error: err?.message || String(err),
        data: previewState.data,
      };
    }
    updatePreviewStage();
  }

  const stageHost = h("aside", { class: "studio-preview-pane" });

  function updatePreviewStage() {
    clear(stageHost);
    const samples = store.meta?.preview_samples || [
      { id: "video", label: "B站视频（横幅封面）" },
      { id: "gallery", label: "小红书 7 图集" },
      { id: "repost", label: "微博转发（无图动态）" },
    ];
    const d = previewState.data;
    const renderEnabled = Boolean(store.draft.RENDER_ENABLED);

    const sampleBar = h(
      "div",
      { class: "sample-tabs" },
      samples.map((sp) =>
        h(
          "button",
          {
            type: "button",
            class: `seg-btn ${sampleId === sp.id ? "is-active" : ""}`,
            title: sp.description || sp.label,
            onclick: () => {
              sampleId = sp.id;
              schedulePreview(0);
            },
          },
          sp.label.replace(/（.*）/, ""),
        ),
      ),
    );

    const statusPills = h(
      "div",
      { class: "preview-meta-pills" },
      d
        ? [
            h("span", { class: "pill pill-info" }, `样式：${d.used_style}`),
            d.fallback
              ? h("span", { class: "pill pill-warn" }, `无图自动回退 (${d.requested_style} → ${d.used_style})`)
              : null,
            h("span", { class: "pill" }, `署名：${d.watermark}`),
            h("span", { class: "pill" }, `${d.width}px · ${d.render_ms} ms`),
          ]
        : null,
    );

    const frame = h("div", { class: "preview-canvas-frame" });
    if (!renderEnabled) {
      frame.appendChild(
        h("div", { class: "preview-disabled-banner" }, "图片渲染开关已关闭 · 以下仅预览排版参数效果"),
      );
    }
    if (previewState.error) {
      frame.appendChild(
        h("div", { class: "notice notice-err" }, `实时渲染出错：${previewState.error}`),
      );
    }
    if (d?.image) {
      const img = h("img", {
        class: "live-card-img",
        src: d.image,
        alt: "分享卡片实时渲染样貌",
        onclick: () => {
          modalImageUrl = d.image;
          renderModal();
        },
      });
      frame.appendChild(img);
    } else if (!previewState.error) {
      frame.appendChild(h("div", { class: "preview-skeleton" }, "正在向后端渲染真实卡片…"));
    }
    if (previewState.loading) {
      frame.appendChild(
        h("div", { class: "preview-loading-chip" }, h("span", { class: "boot-ring sm" }), "渲染中"),
      );
    }

    stageHost.appendChild(
      h(
        "div",
        { class: "surface-panel preview-sticky-box" },
        h(
          "div",
          { class: "preview-toolbar" },
          h("span", { class: "surface-title" }, "实时真卡片预览"),
          h(
            "button",
            {
              type: "button",
              class: "btn btn-ghost btn-sm",
              disabled: previewState.loading,
              onclick: () => schedulePreview(0),
            },
            icon("refresh", 14),
            "重绘",
          ),
        ),
        sampleBar,
        statusPills,
        frame,
        d?.image
          ? h("p", { class: "preview-tip" }, "点击预览图可放大查看像素与字体渲染细节（支持热插拔自定义样式）")
          : null,
      ),
    );
  }

  const modalHost = h("div", { class: "preview-lightbox is-hidden" });
  function renderModal() {
    clear(modalHost);
    modalHost.classList.toggle("is-hidden", !modalImageUrl);
    if (!modalImageUrl) return;
    modalHost.appendChild(
      h(
        "div",
        {
          class: "lightbox-backdrop",
          onclick: () => {
            modalImageUrl = null;
            renderModal();
          },
        },
        h("img", { src: modalImageUrl, class: "lightbox-img", alt: "卡片大图预览" }),
        h("span", { class: "lightbox-close-hint" }, "点击任意位置关闭放大预览"),
      ),
    );
  }

  function renderStyleGrid() {
    const currentStyle = String(store.draft.RENDER_STYLE || "standard");
    const stylesMeta = store.meta?.styles || [];
    const realThumbs = thumbsState.items || [];
    const thumbByName = new Map(realThumbs.map((t) => [t.name, t.image]));

    return h(
      "div",
      { class: "real-style-grid" },
      stylesMeta.map((st) => {
        const active = st.name === currentStyle;
        const thumbUrl = thumbByName.get(st.name);
        return h(
          "button",
          {
            type: "button",
            class: `real-style-card ${active ? "is-active" : ""}`,
            onclick: () => {
              store.setDraftValue("RENDER_STYLE", st.name);
              render();
              schedulePreview(0);
            },
          },
          h(
            "div",
            { class: "real-style-thumb" },
            thumbUrl
              ? h("img", { src: thumbUrl, alt: st.display_name })
              : h("span", { class: "thumb-placeholder" }, thumbsState.loading ? "渲染样图中…" : st.display_name),
          ),
          h(
            "div",
            { class: "real-style-info" },
            h(
              "div",
              { class: "real-style-name-row" },
              h("strong", null, st.display_name),
              h("code", null, st.name),
            ),
            h("p", null, st.description || ""),
          ),
        );
      }),
    );
  }

  function render() {
    clear(root);
    const map = itemsMap();
    const showKey = Boolean(store.showDevKeys);

    const widthVal = Number(store.draft.RENDER_WIDTH || 800);
    const widthSlider = h("input", {
      type: "range",
      class: "range-slider",
      min: 520,
      max: 1080,
      step: 20,
      oninput: (e) => {
        const n = Number.parseInt(e.target.value, 10);
        if (!Number.isNaN(n)) {
          widthValSpan.textContent = `${n} px`;
          store.setDraftValue("RENDER_WIDTH", n, { rerender: false });
          schedulePreview(220);
        }
      },
    });
    widthSlider.value = String(widthVal);
    const widthValSpan = h("span", { class: "range-readout" }, `${widthVal} px`);

    const personaInput = h("input", {
      type: "text",
      class: "ctrl-input ctrl-sm",
      placeholder: "输入人格名预览（如 达妮娅）",
      oninput: (e) => {
        previewPersonaName = e.target.value;
        schedulePreview(240);
        fetchStyleThumbs(true);
      },
    });
    personaInput.value = previewPersonaName;

    const brandInput = h("input", {
      type: "text",
      class: "ctrl-input ctrl-sm",
      maxlength: 16,
      placeholder: "莉卡解析",
      oninput: (e) => {
        store.setDraftValue("RENDER_BRAND_NAME", e.target.value, { rerender: false });
        schedulePreview(240);
      },
    });
    brandInput.value = String(store.draft.RENDER_BRAND_NAME ?? "莉卡解析");

    const fontItem = map.get("RENDER_FONT_PATH");
    const fontInput = h("input", {
      type: "text",
      class: "ctrl-input",
      placeholder: fontItem?.placeholder || "留空自动探测系统中文字体",
      oninput: (e) => {
        store.setDraftValue("RENDER_FONT_PATH", e.target.value, { rerender: false });
        schedulePreview(350);
      },
    });
    fontInput.value = String(store.draft.RENDER_FONT_PATH || "");

    const leftPane = h(
      "div",
      { class: "studio-controls-pane" },
      // 卡片开关 + 样式选择器
      h(
        "section",
        { class: "surface-panel" },
        h(
          "div",
          { class: "surface-head" },
          h(
            "div",
            null,
            h("h2", { class: "surface-title" }, "卡片渲染与真实版式"),
            h("p", { class: "surface-desc" }, "缩略图由后台真实渲染引擎实时生成；后续新增自定义样式会自动在此呈现"),
          ),
          h(
            "label",
            { class: "switch" },
            h("input", {
              type: "checkbox",
              checked: Boolean(store.draft.RENDER_ENABLED),
              onchange: (e) => {
                store.setDraftValue("RENDER_ENABLED", Boolean(e.target.checked));
                render();
                updatePreviewStage();
              },
            }),
            h("span", { class: "switch-track" }),
            h("span", { class: "switch-text" }, store.draft.RENDER_ENABLED ? "卡片开启" : "纯文本"),
          ),
        ),
        renderStyleGrid(),
      ),
      // 尺寸 / 深浅 / 人格动态署名 / 字体
      h(
        "section",
        { class: "surface-panel" },
        h(
          "div",
          { class: "surface-head" },
          h(
            "div",
            null,
            h("h2", { class: "surface-title" }, "版面参数与会话人格署名"),
            h("p", { class: "surface-desc" }, "右侧预览画布会随每次调整实时重绘"),
          ),
        ),
        h(
          "div",
          { class: "settings-list" },
          h(
            "div",
            { class: "setting-item" },
            h(
              "div",
              { class: "setting-meta" },
              h(
                "div",
                { class: "setting-label-row" },
                h("span", { class: "setting-label" }, "卡片浅 / 深色主题"),
                showKey ? h("code", { class: "dev-key" }, "RENDER_THEME") : null,
              ),
              h("p", { class: "setting-hint" }, "部分固定配色自定义样式会忽略此项"),
            ),
            h(
              "div",
              { class: "seg-group" },
              [
                { id: "dark", label: "深色 Dark" },
                { id: "light", label: "浅色 Light" },
              ].map((m) =>
                h(
                  "button",
                  {
                    type: "button",
                    class: `seg-btn ${store.draft.RENDER_THEME === m.id ? "is-active" : ""}`,
                    onclick: () => {
                      store.setDraftValue("RENDER_THEME", m.id);
                      render();
                      fetchStyleThumbs();
                      schedulePreview(0);
                    },
                  },
                  m.label,
                ),
              ),
            ),
          ),
          h(
            "div",
            { class: "setting-item" },
            h(
              "div",
              { class: "setting-meta" },
              h(
                "div",
                { class: "setting-label-row" },
                h("span", { class: "setting-label" }, "卡片像素宽度"),
                showKey ? h("code", { class: "dev-key" }, "RENDER_WIDTH") : null,
              ),
              h("p", { class: "setting-hint" }, "范围 520 – 1080 px，建议 720 – 900"),
            ),
            h("div", { class: "range-wrap" }, widthSlider, widthValSpan),
          ),
          h(
            "div",
            { class: "setting-item" },
            h(
              "div",
              { class: "setting-meta" },
              h(
                "div",
                { class: "setting-label-row" },
                h("span", { class: "setting-label" }, "封面全尺寸展示"),
                showKey ? h("code", { class: "dev-key" }, "RENDER_COVER_FULL_SIZE") : null,
              ),
              h("p", { class: "setting-hint" }, "开启后不再裁切封面，按原图宽高比完整显示"),
            ),
            h(
              "label",
              { class: "switch" },
              h("input", {
                type: "checkbox",
                checked: Boolean(store.draft.RENDER_COVER_FULL_SIZE),
                onchange: (e) => {
                  store.setDraftValue("RENDER_COVER_FULL_SIZE", Boolean(e.target.checked));
                  schedulePreview(0);
                },
              }),
              h("span", { class: "switch-track" }),
              h("span", { class: "switch-text" }, store.draft.RENDER_COVER_FULL_SIZE ? "原比完整" : "固定横幅"),
            ),
          ),
          h(
            "div",
            { class: "setting-item is-wide persona-box", dataset: { key: "RENDER_BRAND_NAME" } },
            h(
              "div",
              { class: "setting-meta" },
              h(
                "div",
                { class: "setting-label-row" },
                h("span", { class: "setting-label" }, "解析署名与人格跟随"),
                showKey
                  ? h("code", { class: "dev-key" }, "RENDER_PERSONA_WATERMARK / RENDER_BRAND_NAME")
                  : null,
                h("span", { class: "dirty-pill" }, "已更改"),
              ),
              h(
                "p",
                { class: "setting-hint" },
                store.draft.RENDER_PERSONA_WATERMARK
                  ? `已开启人格跟随：卡片水印与文本头跟随当前会话人格，未命中人格时回退「${String(store.draft.RENDER_BRAND_NAME || "莉卡解析").trim() || "莉卡解析"}」。`
                  : "开启后跟随当前会话人格名称（跨人格共享底卡缓存）；关闭后可在下方直接自定义解析署名。",
              ),
            ),
            h(
              "div",
              { class: "persona-controls" },
              h(
                "label",
                { class: "switch" },
                h("input", {
                  type: "checkbox",
                  checked: Boolean(store.draft.RENDER_PERSONA_WATERMARK),
                  onchange: (e) => {
                    store.setDraftValue("RENDER_PERSONA_WATERMARK", Boolean(e.target.checked));
                    render();
                    fetchStyleThumbs();
                    schedulePreview(0);
                  },
                }),
                h("span", { class: "switch-track" }),
                h("span", { class: "switch-text" }, store.draft.RENDER_PERSONA_WATERMARK ? "跟随人格" : "自定义固定署名"),
              ),
              store.draft.RENDER_PERSONA_WATERMARK
                ? h(
                    "div",
                    { class: "persona-sim-box" },
                    h("span", { class: "persona-sim-label" }, "预览试看人格："),
                    personaInput,
                  )
                : h(
                    "div",
                    { class: "persona-sim-box" },
                    h("span", { class: "persona-sim-label" }, "自定义署名："),
                    brandInput,
                  ),
            ),
          ),
          h(
            "div",
            { class: "setting-item is-wide" },
            h(
              "div",
              { class: "setting-meta" },
              h(
                "div",
                { class: "setting-label-row" },
                h("span", { class: "setting-label" }, "自定义渲染字体路径（可选）"),
                showKey ? h("code", { class: "dev-key" }, "RENDER_FONT_PATH") : null,
              ),
            ),
            h("div", { class: "setting-ctrl" }, fontInput),
          ),
        ),
      ),
      // 分发与缓存（同属内容产出流，集中收纳于此）
      h(
        "section",
        { class: "surface-panel" },
        h(
          "div",
          { class: "surface-head" },
          h(
            "div",
            null,
            h("h2", { class: "surface-title" }, "非 OneBot 分发与缓存清理"),
            h("p", { class: "surface-desc" }, "控制合并转发转临时网页行为及磁盘缓存有效期"),
          ),
        ),
        h(
          "div",
          { class: "settings-list two-col" },
          DELIVERY_CACHE_KEYS.map((k) => map.get(k))
            .filter(Boolean)
            .map((it) => buildControlRow(store, it, { showKey, onAfterChange: render })),
        ),
      ),
    );

    root.appendChild(h("div", { class: "studio-split" }, leftPane, stageHost));
    root.appendChild(modalHost);
    updatePreviewStage();
    renderModal();
    fetchStyleThumbs();
  }

  function onActivated() {
    fetchStyleThumbs();
    if (!previewState.data && !previewState.loading) {
      schedulePreview(0);
    }
  }

  render();
  return { element: root, sync: render, onActivated, refreshPreview: () => schedulePreview(0) };
}
