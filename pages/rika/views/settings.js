/* 设置页：把后端 CONFIG_META 描述的全部配置项渲染成表单。
 *
 * 页面是插件配置的**唯一维护入口**（_conf_schema.json 里除功能开关外的条目都标了
 * invisible），所以这里必须把配置项完整覆盖到，并做前端校验 + 脏值跟踪。
 *
 * 职责边界：只读写配置，不做解析 / 缓存 / 预览 —— 那些是插件在聊天侧的能力。
 */

import {
  h,
  append,
  clear,
  card,
  toast,
  confirmDialog,
  withBusy,
  switchControl,
  secretInput,
  emptyBox,
} from "../ui.js";

const ALL = "__all__";

/** 导航里「解析器开关」视图的 id（app.js 也用它）。 */
export const PLATFORM_VIEW = "__platforms__";

/** 解析器开关对应的存储键：一个逗号串，页面按注册表渲染成开关。 */
const PLATFORM_KEY = "DISABLED_PLATFORMS";

export function createSettingsView(ctx) {
  let container = null;
  let meta = { groups: [], items: [], problems: [], version: "" };
  let values = {};
  let draft = {};
  let filter = "";
  let groupName = ALL;
  let collapsed = new Set();
  let savebar = null;
  // 分组名 -> 组内配置键，供「N 项待保存」角标复用（不用每次遍历 items）
  let keysByGroup = new Map();
  // 解析器开关：平台清单由后端从适配器注册表下发，这里不写死
  let platforms = [];
  let platformChips = new Map();
  let platformMeta = null;

  /* ---------------- 数据 ---------------- */

  /** 收纳后端返回的配置元数据（首屏由 app.js 取好传进来，避免多拉一次）。 */
  function adopt(payload) {
    meta = {
      groups: payload.groups || [],
      items: payload.items || [],
      problems: payload.problems || [],
      version: payload.version || "",
    };
    values = payload.values || {};
    draft = {};
    // control 项（解析器开关）由专门的卡片渲染，不计入普通分组的字段与角标
    keysByGroup = new Map(
      meta.groups.map((group) => [
        group.name,
        (group.keys || []).filter((key) => !itemOf(key)?.control),
      ]),
    );
    platforms = payload.platforms || [];
    // 解析器开关的文案与说明沿用 CONFIG_META 里 DISABLED_PLATFORMS 那一项
    platformMeta = meta.items.find((item) => item.key === PLATFORM_KEY) || null;
    if (meta.version) ctx.setVersion(`v${meta.version}`);
  }

  /** 当前被禁用（开关为关）的平台名集合，读的是草稿优先的当前值。 */
  function disabledSet() {
    const raw = currentValue(PLATFORM_KEY);
    return new Set(
      String(raw || "")
        .split(",")
        .map((name) => name.trim().toLowerCase())
        .filter(Boolean),
    );
  }

  function matchPlatform(platform) {
    if (!filter) return true;
    const haystack = [platform.name, platform.label, platformMeta?.label, platformMeta?.hint]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(filter);
  }

  async function load() {
    ctx.setHead("加载中…");
    adopt(await ctx.api.get("config"));
  }

  function itemOf(key) {
    return meta.items.find((item) => item.key === key);
  }

  function currentValue(key) {
    return Object.prototype.hasOwnProperty.call(draft, key) ? draft[key] : values[key];
  }

  /** 把 textarea 里的多行文本切成列表（兼容单行内用逗号分隔的写法）。 */
  function splitList(raw) {
    const rows = [];
    for (const line of String(raw || "").split("\n")) {
      for (const part of line.split(",")) {
        const text = part.trim();
        if (text && !rows.includes(text)) rows.push(text);
      }
    }
    return rows;
  }

  /** 值比较。列表（黑名单）逐项比，否则改回原值也会被当成「已修改」。 */
  function sameValue(a, b) {
    if (Array.isArray(a) && Array.isArray(b)) {
      return a.length === b.length && a.every((row, index) => row === b[index]);
    }
    return a === b;
  }

  function setDraft(key, value) {
    if (sameValue(value, values[key])) delete draft[key];
    else draft[key] = value;
  }

  function dirtyKeys() {
    return Object.keys(draft);
  }

  function matchesFilter(item) {
    if (!filter) return true;
    const haystack = [item.key, item.label, item.hint, item.group]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(filter);
  }

  /** 当前导航下要显示的组；ALL 表示全部。搜索时忽略分组限制。 */
  function visibleGroups() {
    if (!filter && groupName !== ALL) {
      if (groupName === PLATFORM_VIEW) return [];
      return meta.groups.filter((group) => group.name === groupName);
    }
    return meta.groups;
  }

  /** 当前导航下是否显示解析器开关卡（搜索时跨视图显示，命中由 matchPlatform 过滤）。 */
  function platformCardVisible() {
    if (!platforms.length) return false;
    if (filter) return true;
    return groupName === ALL || groupName === PLATFORM_VIEW;
  }

  /* ---------------- 渲染 ---------------- */

  function render() {
    if (!container) return;
    clear(container);

    if (meta.problems.length) {
      container.appendChild(
        card("配置契约有问题", "请先把下面这些改好，否则保存的值可能被丢弃", [
          ...meta.problems.map((text) =>
            h("p", { class: "card-note", style: { color: "var(--err)" }, text }),
          ),
        ], null, "err"),
      );
    }

    container.appendChild(renderToolbar());

    let rendered = 0;
    if (platformCardVisible()) {
      const card = renderPlatformCard();
      if (card) {
        rendered += platformChips.size;
        container.appendChild(card);
      }
    }
    for (const group of visibleGroups()) {
      const items = group.keys
        .map(itemOf)
        .filter((item) => item && !item.control && matchesFilter(item));
      if (!items.length) continue;
      rendered += items.length;
      container.appendChild(renderGroup(group, items));
    }

    if (rendered === 0) {
      container.appendChild(
        card("没有匹配的配置项", null, [
          emptyBox(`没有找到包含「${filter}」的配置项。`),
        ]),
      );
    }

    savebar = renderSaveBar();
    container.appendChild(savebar);
    ctx.setHead("");
  }

  function renderToolbar() {
    const search = h("input", {
      class: "input",
      type: "search",
      value: filter,
      placeholder: "搜索配置项（名称 / 键 / 说明）",
      onInput: (event) => {
        filter = event.target.value.trim().toLowerCase();
        render();
        focusSearch();
      },
    });

    return card("配置项", `${meta.items.length} 项，保存后立即生效`, [
      h("div", { class: "toolbar" }, [
        h("div", { class: "grow" }, [search]),
        h(
          "button",
          {
            class: "btn",
            type: "button",
            onClick: () => {
              collapsed = collapsed.size
                ? new Set()
                : new Set(meta.groups.map((group) => group.name));
              render();
            },
          },
          collapsed.size ? "展开全部" : "收起全部",
        ),
      ]),
    ]);
  }

  /** 重渲染会让搜索框失焦，把光标还回去，否则输一个字就没法继续输入。 */
  function focusSearch() {
    const input = container && container.querySelector('input[type="search"]');
    if (!input) return;
    input.focus();
    const end = input.value.length;
    try {
      input.setSelectionRange(end, end);
    } catch {
      /* search 类型部分浏览器不支持 setSelectionRange，忽略 */
    }
  }

  /**
   * 解析器开关卡：平台清单由后端从适配器注册表下发，**页面不写死任何平台**。
   * 开关结果写回 `DISABLED_PLATFORMS` 逗号串（AstrBot 的配置完整性检查只认
   * schema 里的静态键，动态的 `PLATFORM_*_ENABLED` 键存不住）。
   */
  function renderPlatformCard() {
    platformChips = new Map();
    const shown = platforms.filter(matchPlatform);
    if (!shown.length) return null;

    const grid = h("div", { class: "platform-grid" }, shown.map(renderPlatformChip));
    const dirty = dirtyKeys().includes(PLATFORM_KEY);
    return h("section", { class: "card", dataset: { platform: "1" } }, [
      h("div", { class: "card-head" }, [
        h("h2", { text: platformMeta?.label || "解析器开关" }),
        dirty ? h("span", { class: "pill primary", text: "待保存" }) : null,
        h("span", {
          class: "sub",
          text: platformMeta?.hint || `共 ${shown.length} 个平台，关闭后不再解析对应链接`,
        }),
      ]),
      h("div", {}, [grid]),
    ]);
  }

  function renderPlatformChip(platform) {
    const enabled = !disabledSet().has(platform.name);
    const chip = h("div", {
      class: `platform-chip${enabled ? " is-on" : ""}`,
      role: "switch",
      tabindex: "0",
      title: `${platform.name} · ${enabled ? "点击关闭" : "点击启用"}`,
      "aria-checked": enabled ? "true" : "false",
      "aria-label": platform.label,
    });
    // 开关只作状态显示：点击由整块 chip 处理（CSS 里给 .switch 关了 pointer-events），
    // 这样鼠标点标签、点开关、键盘回车都是同一个入口
    const toggleText = { on: "启用", off: "关闭" };
    append(chip, [
      h("span", { class: "platform-chip-label", text: platform.label }),
      switchControl(enabled, () => {}, toggleText.on, toggleText.off),
    ]);
    // 必须按「点击那一刻」的状态翻转，不能闭包捕获这里的 enabled：
    // 切完只做就地刷新（不整页重渲染），闭包里的值会一直是首次渲染时的旧值，
    // 表现为同一个开关点第二次没反应。
    const toggle = () => flipPlatform(platform.name);
    chip.addEventListener("click", toggle);
    chip.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggle();
      }
    });
    platformChips.set(platform.name, chip);
    return chip;
  }

  /** 切换单个平台的启用状态（按当前草稿翻转）。 */
  function flipPlatform(name) {
    const disabled = disabledSet();
    if (disabled.has(name)) disabled.delete(name);
    else disabled.add(name);
    // 按注册表顺序拼回去，保证「关掉再打开」能回到原字符串，脏值判断才准
    const ordered = platforms.map((p) => p.name).filter((n) => disabled.has(n));
    onChange(PLATFORM_KEY, ordered.join(","));
    refreshPlatformChips();
  }

  /** 就地更新 chip，不整页重渲染（否则正在输入搜索框的光标会被打断）。 */
  function refreshPlatformChips() {
    const disabled = disabledSet();
    for (const [name, chip] of platformChips) {
      const enabled = !disabled.has(name);
      chip.classList.toggle("is-on", enabled);
      chip.setAttribute("aria-checked", enabled ? "true" : "false");
      chip.title = `${name} · ${enabled ? "点击关闭" : "点击启用"}`;
      const input = chip.querySelector('input[type="checkbox"]');
      if (input) input.checked = enabled;
      const text = chip.querySelector(".switch-text");
      if (text) text.textContent = enabled ? "启用" : "关闭";
    }
  }

  function renderGroup(group, items) {
    const isCollapsed = collapsed.has(group.name);

    const head = h(
      "button",
      {
        class: "card-head",
        type: "button",
        style: {
          width: "100%",
          background: "transparent",
          border: "0",
          cursor: "pointer",
          textAlign: "left",
          padding: "0",
        },
        onClick: () => {
          if (isCollapsed) collapsed.delete(group.name);
          else collapsed.add(group.name);
          render();
        },
      },
      [
        h("h2", { text: `${isCollapsed ? "＋" : "－"} ${group.name}` }),
        dirtyBadge(group.name),
        h("span", { class: "sub", text: `${items.length} 项 · ${group.description || ""}` }),
      ],
    );

    const section = h("section", { class: "card", dataset: { group: group.name } }, [head]);
    if (!isCollapsed) {
      section.appendChild(h("div", {}, items.map(renderField)));
    }
    return section;
  }

  /** 分组待保存角标；没有改动时返回 null（h() 会跳过 null）。 */
  function dirtyBadge(name) {
    const dirty = dirtyKeys();
    const count = (keysByGroup.get(name) || []).filter((key) => dirty.includes(key)).length;
    return count ? h("span", { class: "pill primary", text: `${count} 项待保存` }) : null;
  }

  function renderField(item) {
    return h("div", { class: "field" }, [
      h("div", { class: "field-label" }, [item.label, h("code", { text: item.key })]),
      h("div", { class: "field-body" }, [
        buildControl(item),
        item.hint ? h("div", { class: "field-hint", text: item.hint }) : null,
      ]),
    ]);
  }

  /** 开关状态要即时反馈，其余控件交给 refreshSaveBar 更新底部保存条。 */
  function onChange(key, value) {
    setDraft(key, value);
    refreshSaveBar();
  }

  function buildControl(item) {
    const value = currentValue(item.key);

    if (item.type === "bool") {
      return switchControl(Boolean(value), (next) => onChange(item.key, next));
    }

    if (item.type === "int" || item.type === "float") {
      const input = h("input", {
        class: "input",
        type: "number",
        value: value === null || value === undefined ? "" : String(value),
        min: item.min !== undefined ? String(item.min) : null,
        max: item.max !== undefined ? String(item.max) : null,
        step: item.type === "float" ? "0.5" : "1",
        style: { maxWidth: "160px" },
        onInput: (event) => {
          const raw = event.target.value;
          if (raw === "") return onChange(item.key, "");
          onChange(item.key, item.type === "float" ? Number(raw) : parseInt(raw, 10));
        },
      });
      return h("div", { class: "inline" }, [
        input,
        item.unit ? h("span", { class: "unit", text: item.unit }) : null,
      ]);
    }

    if (item.type === "select") {
      const options = item.options || [];
      const labels = item.labels || [];
      const select = h(
        "select",
        {
          class: "select",
          style: { maxWidth: "320px" },
          onChange: (event) => onChange(item.key, event.target.value),
        },
        options.map((option, index) =>
          h("option", { value: option, text: labels[index] || option }),
        ),
      );
      select.value = value === null || value === undefined ? "" : String(value);
      return select;
    }

    // secret 判断必须放在 text 之前：XHS_CK 是 type="text" + secret=true，
    // 命中下面的 textarea 分支会让遮罩与「显示/隐藏」按钮对它失效。
    if (item.secret) {
      return secretInput(
        value === null || value === undefined ? "" : String(value),
        (next) => onChange(item.key, next),
        item.placeholder || "",
      );
    }

    if (item.type === "list") {
      const rows = Array.isArray(value) ? value : [];
      return h("textarea", {
        class: "input",
        value: rows.join("\n"),
        rows: 3,
        spellcheck: "false",
        placeholder: item.placeholder || "一行一条",
        // 前端先切成数组再交给后端，这样「改回原样」能被认出来、不算待保存
        onInput: (event) => onChange(item.key, splitList(event.target.value)),
      });
    }

    if (item.type === "text") {
      return h("textarea", {
        class: "input",
        value: value === null || value === undefined ? "" : String(value),
        rows: 3,
        spellcheck: "false",
        placeholder: item.placeholder || "",
        onInput: (event) => onChange(item.key, event.target.value),
      });
    }

    return h("input", {
      class: "input",
      type: "text",
      value: value === null || value === undefined ? "" : String(value),
      placeholder: item.placeholder || "",
      spellcheck: "false",
      onInput: (event) => onChange(item.key, event.target.value),
    });
  }

  /* ---------------- 保存条 ---------------- */

  function renderSaveBar() {
    return buildSaveBar();
  }

  function refreshSaveBar() {
    if (!savebar || !savebar.parentNode) return;
    const next = buildSaveBar();
    savebar.replaceWith(next);
    savebar = next;
    refreshBadges();
  }

  /** 只更新分组标题上的「N 项待保存」角标，不重建整张卡（避免输入框失焦）。 */
  function refreshBadges() {
    if (!container) return;
    for (const section of container.querySelectorAll("section.card[data-group]")) {
      syncBadge(section, dirtyBadge(section.dataset.group));
    }
    const platformCard = container.querySelector('section.card[data-platform]');
    if (platformCard) {
      syncBadge(
        platformCard,
        dirtyKeys().includes(PLATFORM_KEY)
          ? h("span", { class: "pill primary", text: "待保存" })
          : null,
      );
    }
  }

  function syncBadge(section, next) {
    const head = section.querySelector(".card-head");
    if (!head) return;
    const sub = head.querySelector(".sub");
    const badge = head.querySelector(".pill.primary");
    if (!next) {
      if (badge) badge.remove();
      return;
    }
    if (badge) badge.replaceWith(next);
    else if (sub) head.insertBefore(next, sub);
    else head.appendChild(next);
  }

  function buildSaveBar() {
    const keys = dirtyKeys();
    const text = keys.length
      ? `已修改 ${keys.length} 项：${keys.slice(0, 3).join("、")}${keys.length > 3 ? " 等" : ""}`
      : "没有未保存的改动";

    return h("div", { class: "savebar" }, [
      h("span", { class: "grow", text }),
      h(
        "button",
        {
          class: "btn",
          type: "button",
          disabled: keys.length === 0,
          onClick: () => {
            draft = {};
            render();
          },
        },
        "放弃更改",
      ),
      h(
        "button",
        {
          class: "btn danger",
          type: "button",
          onClick: (event) => resetAll(event.currentTarget),
        },
        "恢复默认",
      ),
      h(
        "button",
        {
          class: "btn primary",
          type: "button",
          disabled: keys.length === 0,
          onClick: (event) => save(event.currentTarget),
        },
        `保存更改${keys.length ? `（${keys.length}）` : ""}`,
      ),
    ]);
  }

  /* ---------------- 保存 / 恢复 ---------------- */

  async function save(button) {
    const keys = dirtyKeys();
    if (!keys.length) return;

    // 数值项被清空时草稿是空串，直接提交会被后端判为「需要是整数」。
    // 这里先挑出来跳过，避免一个空输入框拖累整批保存。
    const skipped = [];
    const valuesToSave = {};
    for (const key of keys) {
      const item = itemOf(key);
      if (item && (item.type === "int" || item.type === "float") && draft[key] === "") {
        skipped.push(item.label || key);
        delete draft[key];
        continue;
      }
      valuesToSave[key] = draft[key];
    }
    if (!Object.keys(valuesToSave).length) {
      toast(`数值项为空，已跳过：${skipped.join("、")}`, "warn");
      render();
      return;
    }

    const restore = withBusy(button, true, "保存中…");
    try {
      const result = await ctx.api.post("config", { values: valuesToSave });
      values = result.values || values;
      draft = {};

      if (skipped.length) {
        toast(`已跳过空值项：${skipped.join("、")}`, "warn");
      }

      if (result.errors && result.errors.length) {
        toast(`部分配置未保存：${result.errors.join("；")}`, "err");
      } else if (result.changed && result.changed.length) {
        toast(`已保存 ${result.changed.length} 项配置`, "ok");
      } else {
        toast("配置没有变化", "");
      }
      render();
    } catch (error) {
      toast(`保存失败：${error.message}`, "err");
    } finally {
      restore();
    }
  }

  async function resetAll(button) {
    const ok = await confirmDialog({
      title: "恢复默认配置",
      body:
        "所有配置项都会回到默认值，包括 Cookie、Token 与黑名单设置。这一步不能撤销。",
      confirmText: "恢复默认",
      danger: true,
    });
    if (!ok) return;

    const restore = withBusy(button, true, "恢复中…");
    try {
      const result = await ctx.api.post("config/reset", {});
      values = result.values || values;
      draft = {};
      toast(`已恢复默认（改动 ${result.changed ? result.changed.length : 0} 项）`, "ok");
      render();
    } catch (error) {
      toast(`恢复失败：${error.message}`, "err");
    } finally {
      restore();
    }
  }

  /* ---------------- 对外接口 ---------------- */

  return {
    adopt,
    /** 挂载。调用前必须先 adopt() 一次；有未保存改动时会先让用户确认。 */
    async mount(node) {
      container = node;
      render();
    },
    async refresh() {
      if (dirtyKeys().length) {
        const ok = await confirmDialog({
          title: "有未保存的改动",
          body: "刷新会丢弃当前未保存的修改，确定继续吗？",
          confirmText: "刷新并丢弃",
          danger: true,
        });
        if (!ok) return;
      }
      await load();
      render();
    },
    /** 切换左侧导航选中的分组（ALL 表示全部）。 */
    showGroup(name) {
      groupName = name || ALL;
      // 切换分组时清掉搜索词，否则「当前分组没匹配项」会让人以为配置丢了
      filter = "";
      render();
    },
    groupNames() {
      return meta.groups.map((group) => group.name);
    },
    /** 注册表里有平台时才显示「解析器开关」导航项。 */
    hasPlatforms() {
      return platforms.length > 0;
    },
    dirtyCount() {
      return dirtyKeys().length;
    },
  };
}
