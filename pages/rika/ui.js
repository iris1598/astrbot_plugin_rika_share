/* 通用 UI 小工具：DOM 构造、提示条、确认框、忙碌态、表单片段。
 * 全部零依赖，避免在受限 iframe 里受 CSP 与网络影响。
 */

/** 建元素。props 里的函数值会当作事件监听，其余当属性；style 支持对象。 */
export function h(tag, props = null, children = null) {
  const node = document.createElement(tag);
  if (props) {
    for (const [key, value] of Object.entries(props)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key === "html") node.innerHTML = value;
      // value 必须写成 DOM 属性值，不能用 setAttribute：textarea 的值来自子文本，
      // 对它设 value 属性完全不生效（表单会显示成空框，一保存就把原内容清掉）。
      // option 的 value 属性会反射到 attribute，两种元素都正确。
      else if (key === "value") node.value = value === null || value === undefined ? "" : value;
      else if (key === "style" && typeof value === "object") {
        Object.assign(node.style, value);
      } else if (key.startsWith("on") && typeof value === "function") {
        node.addEventListener(key.slice(2).toLowerCase(), value);
      } else if (key === "dataset" && typeof value === "object") {
        Object.assign(node.dataset, value);
      } else if (value === true) {
        node.setAttribute(key, "");
      } else {
        node.setAttribute(key, String(value));
      }
    }
  }
  append(node, children);
  return node;
}

/**
 * 追加子节点，自动跳过 null / false，字符串转文本节点。
 *
 * **数组会递归展开**：`h("dl", {}, [[dt, dd], [dt, dd]])` 这种「成对节点」写法很自然，
 * 不展开的话整个子数组会被 `String()` 成一个 `"[object HTMLxxxElement]"` 文本节点
 * —— 页面不报错，但内容变成乱码。
 */
export function append(parent, children) {
  if (children === null || children === undefined || children === false) return parent;
  if (Array.isArray(children)) {
    for (const child of children) append(parent, child);
    return parent;
  }
  parent.appendChild(
    children instanceof Node ? children : document.createTextNode(String(children)),
  );
  return parent;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

/**
 * 卡片块：标题 + 说明 + 内容。
 *
 * tone 为 "warn" / "err" 时给整张卡加一道状态色边框与角标 —— 用于「这张卡里
 * 有需要用户处理的事」。
 */
export function card(title, subtitle, children, actions = null, tone = "") {
  const head = h("div", { class: "card-head" }, [
    h("h2", { text: title || "" }),
    tone ? h("span", { class: `pill ${tone}`, text: tone === "err" ? "异常" : "需处理" }) : null,
    subtitle ? h("span", { class: "sub", text: subtitle }) : null,
    actions || null,
  ]);
  return h(
    "section",
    { class: `card${tone ? ` card-${tone}` : ""}` },
    [head, append(h("div"), children)],
  );
}

export function pill(text, kind = "") {
  return h("span", { class: `pill ${kind}`.trim(), text });
}

export function emptyBox(text) {
  return h("div", { class: "empty", text });
}

export function spinner() {
  return h("span", { class: "spinner" });
}

/* ---------------- 提示条 ---------------- */

const TOAST_MS = 3600;

export function toast(message, kind = "") {
  const host = document.getElementById("toast-host");
  if (!host) return;
  const node = h("div", { class: `toast ${kind}`.trim(), text: message });
  host.appendChild(node);
  setTimeout(() => node.remove(), TOAST_MS);
}

/* ---------------- 确认框 ---------------- */

export function confirmDialog({ title, body, confirmText = "确认", danger = false }) {
  return new Promise((resolve) => {
    const host = document.getElementById("modal-host");
    const close = (result) => {
      host.hidden = true;
      host.onclick = null;
      clear(host);
      resolve(result);
    };
    const modal = h("div", { class: "modal" }, [
      h("h2", { text: title }),
      h("p", { class: "card-note", text: body }),
      h("div", { class: "modal-foot" }, [
        h("button", { class: "btn", type: "button", onClick: () => close(false) }, "取消"),
        h(
          "button",
          {
            class: `btn ${danger ? "danger" : "primary"}`.trim(),
            type: "button",
            onClick: () => close(true),
          },
          confirmText,
        ),
      ]),
    ]);
    clear(host);
    host.appendChild(modal);
    host.hidden = false;
    host.onclick = (event) => {
      if (event.target === host) close(false);
    };
  });
}

/* ---------------- 忙碌态 ---------------- */

export function withBusy(button, busy, busyText = "处理中…") {
  if (!button) return () => {};
  if (busy) {
    const original = button.textContent;
    button.disabled = true;
    button.textContent = busyText;
    return () => {
      button.disabled = false;
      button.textContent = original;
    };
  }
  button.disabled = false;
  return () => {};
}

/* ---------------- 表单片段 ---------------- */

/** 开关。onText / offText 是开关右侧的状态文字。 */
export function switchControl(checked, onChange, onText = "开启", offText = "关闭") {
  const label = h("label", { class: "switch" });
  const input = h("input", {
    type: "checkbox",
    onChange: (event) => onChange(event.target.checked),
  });
  input.checked = Boolean(checked);
  const text = h("span", { class: "switch-text", text: checked ? onText : offText });
  // 状态文字要在开关切换后跟着变，否则用户看不到自己改成功了
  input.addEventListener("change", () => {
    text.textContent = input.checked ? onText : offText;
  });
  append(label, [input, h("span", { class: "track" }), text]);
  return label;
}

/** 密码框 + 显示/隐藏按钮。Cookie / Token 用得上。 */
export function secretInput(value, onInput, placeholder = "") {
  let visible = false;
  const input = h("input", {
    class: "input",
    type: "password",
    value: value || "",
    placeholder,
    spellcheck: "false",
    onInput: (event) => onInput(event.target.value),
  });
  const toggle = h(
    "button",
    {
      class: "secret-toggle",
      type: "button",
      title: "显示 / 隐藏",
      onClick: () => {
        visible = !visible;
        input.type = visible ? "text" : "password";
        toggle.textContent = visible ? "隐藏" : "显示";
      },
    },
    "显示",
  );
  return h("div", { class: "secret-wrap" }, [input, toggle]);
}
