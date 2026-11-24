import { clear, h, icon, swapContent } from "../../../core/dom.js";
import { buildControlRow } from "../widgets.js";
import { createStudioNodeRulesPanel } from "./node_editor.js";

const CARD_RENDER_KEYS = [
  "RENDER_ENABLED",
  "RENDER_STYLE",
  "RENDER_THEME",
  "RENDER_WIDTH",
  "RENDER_COVER_FULL_SIZE",
  "RENDER_BRAND_NAME",
  "RENDER_PERSONA_WATERMARK",
  "RENDER_FONT_PATH",
];

const DELIVERY_CACHE_KEYS = [
  "WEBPAGE_FALLBACK_ENABLED",
  "WEBPAGE_TDOCS_JUMP",
  "CACHE_TTL_HOURS",
  "CACHE_CLEANUP_INTERVAL_MINUTES",
];

export function createStudioCardView(appCtx) {
  const { store, preview } = appCtx;
  const root = h("div", { class: "page-stack" });
  const nodeEditor = createStudioNodeRulesPanel(store);
  let modalImageUrl = null;

  const styleGridHost = h("div", { class: "real-style-grid" });
  const cardTagHost = h("span", { class: "setting-label-tags" });
  const cardRevertHost = h("span", { class: "setting-label-tags" });
  const stageHost = h("aside", { class: "studio-preview-pane" });
  const modalHost = h("div", { class: "preview-lightbox is-hidden" });

  function syncCardHeaderStatus() {
    const isGroup = Boolean(store.scope);
    const cardOverridden =
      isGroup && CARD_RENDER_KEYS.some((k) => store.isKeyOverridden(k));
    clear(cardTagHost);
    clear(cardRevertHost);
    if (isGroup) {
      cardTagHost.appendChild(
        cardOverridden
          ? h("span", { class: "pill pill-info" }, "本群独立卡片样式")
          : h("span", { class: "pill" }, "继承全局卡片样式"),
      );
    }
    if (isGroup && cardOverridden) {
      cardRevertHost.appendChild(
        h(
          "button",
          {
            type: "button",
            class: "btn btn-ghost btn-sm",
            onclick: () => {
              for (const k of CARD_RENDER_KEYS) {
                if (store.overrideKeys?.has(k)) {
                  store.revertKeyToInherit(k);
                }
              }
            },
          },
          "卡片配置恢复继承",
        ),
      );
    }
  }

  function syncStyleGrid() {
    const pState = preview.getState();
    const currentStyle = String(store.draft.RENDER_STYLE || "standard");
    const stylesMeta = store.meta?.styles || [];
    const thumbByName = new Map((pState.thumbs || []).map((t) => [t.name, t.image]));

    const cards = stylesMeta.map((st) => {
      const active = st.name === currentStyle;
      const thumbUrl = thumbByName.get(st.name);
      return h(
        "button",
        {
          type: "button",
          class: `real-style-card ${active ? "is-active" : ""}`,
          dataset: { styleName: st.name },
          onclick: () => {
            store.setDraftValue("RENDER_STYLE", st.name);
            for (const el of styleGridHost.querySelectorAll(".real-style-card")) {
              el.classList.toggle("is-active", el.getAttribute("data-style-name") === st.name);
            }
            syncCardHeaderStatus();
            preview.scheduleCard(0);
          },
        },
        h(
          "div",
          { class: "real-style-thumb" },
          thumbUrl
            ? h("img", { src: thumbUrl, alt: st.display_name })
            : h("span", { class: "thumb-placeholder" }, pState.thumbsLoading ? "渲染样图中…" : st.display_name),
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
    });
    swapContent(styleGridHost, cards);
  }

  function updatePreviewStage() {
    const pState = preview.getState();
    const samples = store.meta?.preview_samples || [
      { id: "video", label: "B站视频（横幅封面）" },
      { id: "gallery", label: "小红书 7 图集" },
      { id: "repost", label: "微博转发（无图动态）" },
    ];
    const d = pState.data;
    const renderEnabled = Boolean(store.draft.RENDER_ENABLED);

    const sampleBar = h(
      "div",
      { class: "sample-tabs" },
      samples.map((sp) =>
        h(
          "button",
          {
            type: "button",
            class: `seg-btn ${pState.sampleId === sp.id ? "is-active" : ""}`,
            title: sp.description || sp.label,
            onclick: () => preview.setSampleId(sp.id),
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
    if (pState.error) {
      frame.appendChild(
        h("div", { class: "notice notice-err" }, `实时渲染出错：${pState.error}`),
      );
    }
    if (d?.image) {
      frame.appendChild(
        h("img", {
          class: "live-card-img",
          src: d.image,
          alt: "分享卡片实时渲染样貌",
          onclick: () => {
            modalImageUrl = d.image;
            renderModal();
          },
        }),
      );
    } else if (!pState.error) {
      frame.appendChild(h("div", { class: "preview-skeleton" }, "正在向后端渲染真实卡片…"));
    }
    if (pState.loading) {
      frame.appendChild(
        h("div", { class: "preview-loading-chip" }, h("span", { class: "boot-ring sm" }), "渲染中"),
      );
    }

    swapContent(stageHost, [
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
              disabled: pState.loading,
              onclick: () => preview.scheduleCard(0),
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
    ]);
  }

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

  function render() {
    const map = store.itemMap();
    const showKey = Boolean(store.showDevKeys);
    const pState = preview.getState();

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
          preview.scheduleCard(220);
        }
      },
    });
    widthSlider.value = String(widthVal);
    const widthValSpan = h("span", { class: "range-readout" }, `${widthVal} px`);

    const personaInput = h("input", {
      type: "text",
      class: "ctrl-input ctrl-sm",
      placeholder: "输入人格名预览（如 达妮娅）",
      oninput: (e) => preview.setPersonaName(e.target.value),
    });
    personaInput.value = pState.personaName;

    let personaHintEl = null;
    const brandInput = h("input", {
      type: "text",
      class: "ctrl-input ctrl-sm",
      maxlength: 16,
      placeholder: "莉卡解析",
      oninput: (e) => {
        store.setDraftValue("RENDER_BRAND_NAME", e.target.value, { rerender: false });
        if (personaHintEl) {
          const curBrand = String(e.target.value || "莉卡解析").trim() || "莉卡解析";
          personaHintEl.textContent = store.draft.RENDER_PERSONA_WATERMARK
            ? `已开启人格跟随：卡片水印与文本头跟随当前会话人格，未命中人格时回退「${curBrand}」。`
            : "开启后跟随当前会话人格名称（跨人格共享底卡缓存）；关闭后可在下方直接自定义解析署名。";
        }
        preview.scheduleCard(240);
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
        preview.scheduleCard(350);
      },
    });
    fontInput.value = String(store.draft.RENDER_FONT_PATH || "");

    syncCardHeaderStatus();
    syncStyleGrid();

    const cardEnableText = h(
      "span",
      { class: "switch-text" },
      store.draft.RENDER_ENABLED ? "卡片开启" : "纯文本",
    );

    const themeSegEl = h("div", { class: "seg-group" });
    const themeBtns = [
      { id: "dark", label: "深色 Dark" },
      { id: "light", label: "浅色 Light" },
    ].map((m) => {
      const btn = h(
        "button",
        {
          type: "button",
          class: `seg-btn ${store.draft.RENDER_THEME === m.id ? "is-active" : ""}`,
          onclick: () => {
            store.setDraftValue("RENDER_THEME", m.id);
            for (const b of themeBtns) b.el.classList.toggle("is-active", b.id === m.id);
            syncCardHeaderStatus();
            preview.fetchStyleThumbs();
            preview.scheduleCard(0);
          },
        },
        m.label,
      );
      themeSegEl.appendChild(btn);
      return { id: m.id, el: btn };
    });

    const coverSwitchText = h(
      "span",
      { class: "switch-text" },
      store.draft.RENDER_COVER_FULL_SIZE ? "原比完整" : "固定横幅",
    );

    const personaSwitchText = h(
      "span",
      { class: "switch-text" },
      store.draft.RENDER_PERSONA_WATERMARK ? "跟随人格" : "自定义固定署名",
    );
    personaHintEl = h(
      "p",
      { class: "setting-hint" },
      store.draft.RENDER_PERSONA_WATERMARK
        ? `已开启人格跟随：卡片水印与文本头跟随当前会话人格，未命中人格时回退「${String(store.draft.RENDER_BRAND_NAME || "莉卡解析").trim() || "莉卡解析"}」。`
        : "开启后跟随当前会话人格名称（跨人格共享底卡缓存）；关闭后可在下方直接自定义解析署名。",
    );
    const personaSimHost = h("div", { class: "persona-sim-host" });
    const renderPersonaSimHost = () => {
      const box = store.draft.RENDER_PERSONA_WATERMARK
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
          );
      swapContent(personaSimHost, [box]);
    };
    renderPersonaSimHost();

    const leftPane = h(
      "div",
      { class: "studio-controls-pane" },
      h(
        "section",
        { class: "surface-panel" },
        h(
          "div",
          { class: "surface-head" },
          h(
            "div",
            null,
            h(
              "div",
              { class: "setting-label-row" },
              h("h2", { class: "surface-title" }, "卡片渲染与真实版式"),
              cardTagHost,
            ),
            h("p", { class: "surface-desc" }, "缩略图由后台真实渲染引擎实时生成；后续新增自定义样式会自动在此呈现"),
          ),
          h(
            "div",
            { class: "btn-group" },
            cardRevertHost,
            h(
              "label",
              { class: "switch" },
              h("input", {
                type: "checkbox",
                checked: Boolean(store.draft.RENDER_ENABLED),
                onchange: (e) => {
                  const checked = Boolean(e.target.checked);
                  store.setDraftValue("RENDER_ENABLED", checked);
                  cardEnableText.textContent = checked ? "卡片开启" : "纯文本";
                  syncCardHeaderStatus();
                  updatePreviewStage();
                },
              }),
              h("span", { class: "switch-track" }),
              cardEnableText,
            ),
          ),
        ),
        styleGridHost,
      ),
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
            themeSegEl,
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
                  const checked = Boolean(e.target.checked);
                  store.setDraftValue("RENDER_COVER_FULL_SIZE", checked);
                  coverSwitchText.textContent = checked ? "原比完整" : "固定横幅";
                  syncCardHeaderStatus();
                  preview.scheduleCard(0);
                },
              }),
              h("span", { class: "switch-track" }),
              coverSwitchText,
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
              personaHintEl,
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
                    const checked = Boolean(e.target.checked);
                    store.setDraftValue("RENDER_PERSONA_WATERMARK", checked);
                    personaSwitchText.textContent = checked ? "跟随人格" : "自定义固定署名";
                    const curBrand = String(store.draft.RENDER_BRAND_NAME || "莉卡解析").trim() || "莉卡解析";
                    personaHintEl.textContent = checked
                      ? `已开启人格跟随：卡片水印与文本头跟随当前会话人格，未命中人格时回退「${curBrand}」。`
                      : "开启后跟随当前会话人格名称（跨人格共享底卡缓存）；关闭后可在下方直接自定义解析署名。";
                    renderPersonaSimHost();
                    syncCardHeaderStatus();
                    preview.fetchStyleThumbs();
                    preview.scheduleCard(0);
                  },
                }),
                h("span", { class: "switch-track" }),
                personaSwitchText,
              ),
              personaSimHost,
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
    );

    const deliveryPanel = h(
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
          .map((it) => buildControlRow(store, it, { showKey, onAfterChange: () => nodeEditor.sync() })),
      ),
    );

    swapContent(root, [
      h("div", { class: "studio-split" }, leftPane, stageHost),
      nodeEditor.element,
      deliveryPanel,
      modalHost,
    ]);
    updatePreviewStage();
    renderModal();
    preview.fetchStyleThumbs();
  }

  function onActivated() {
    preview.fetchStyleThumbs();
    const pState = preview.getState();
    if (!pState.data && !pState.loading) {
      preview.scheduleCard(0);
    }
  }

  function sync() {
    render();
    nodeEditor.sync();
  }

  render();
  nodeEditor.sync();
  return {
    element: root,
    sync,
    syncStyleGrid,
    updatePreviewStage,
    onActivated,
    syncNodeEditor: () => nodeEditor.sync(),
  };
}
