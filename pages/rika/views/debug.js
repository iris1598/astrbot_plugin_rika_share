/* 链接调试页：输入链接 → 跑一遍完整解析流程 → 导出可下载的日志。
 *
 * 流程本身全在后端（`link_parser/services/debug_probe.py`）：页面只负责收参数、
 * 把步骤结果摆出来、提供下载入口。调试信息宁可多不可少，所以步骤的失败原因、
 * 耗时、以及插件自己的日志都在这里露出来。
 */

import { h, clear, card, toast, withBusy, switchControl, emptyBox } from "../ui.js";

const STEP_STATUS = {
  ok: { cls: "ok", label: "通过" },
  fail: { cls: "err", label: "失败" },
  skip: { cls: "warn", label: "跳过" },
};

export function createDebugView(ctx) {
  let container = null;
  let url = "";
  let downloadMedia = true;
  let renderCard = true;
  let running = false;
  let report = null;
  let error = "";

  /* ---------------- 渲染 ---------------- */

  function render() {
    if (!container) return;
    clear(container);

    container.appendChild(renderForm());
    if (error) container.appendChild(renderError());
    if (running) container.appendChild(renderRunning());
    if (report) {
      container.appendChild(renderSteps());
      container.appendChild(renderSummary());
      container.appendChild(renderLog());
    }
  }

  function renderForm() {
    const input = h("input", {
      class: "input",
      type: "text",
      value: url,
      placeholder: "粘贴分享链接，例如 https://www.bilibili.com/video/BV1xx411c7mD",
      spellcheck: "false",
      onInput: (event) => {
        url = event.target.value;
      },
      onKeydown: (event) => {
        if (event.key === "Enter") run(event.currentTarget);
      },
    });

    const options = h("div", { class: "toolbar" }, [
      optionToggle("下载媒体", downloadMedia, (next) => {
        downloadMedia = next;
        render();
      }),
      optionToggle("渲染卡片", renderCard, (next) => {
        renderCard = next;
        render();
      }),
    ]);

    const runButton = h(
      "button",
      {
        class: "btn primary",
        type: "button",
        disabled: running ? true : null,
        onClick: (event) => run(event.currentTarget),
      },
      running ? "测试中…" : "开始测试",
    );

    return card(
      "链接调试",
      "把解析主流程逐步跑一遍，导出可直接贴出的日志",
      [
        h("div", { class: "toolbar" }, [h("div", { class: "grow" }, [input]), runButton]),
        h("div", { class: "toolbar", style: { marginTop: "10px" } }, [options]),
        h("p", {
          class: "muted",
          text: "开关真会执行：下载媒体会真的下、渲染卡片会真的出图（文件名带调试标识，不会覆盖正常卡片）。解析结果不写入缓存，也不会向任何会话发消息。",
        }),
      ],
    );
  }

  function optionToggle(label, checked, onChange) {
    return h("div", { class: "inline" }, [
      h("span", { class: "muted", text: label }),
      switchControl(checked, onChange, "", ""),
    ]);
  }

  function renderRunning() {
    return card("测试中", "正在按真实流程解析，耗时取决于媒体大小", [
      emptyBox("请稍候…（大视频可能需要几十秒）"),
    ]);
  }

  function renderError() {
    return card(
      "测试失败",
      "后端没能完成这次调试",
      [h("p", { class: "card-note", style: { color: "var(--err)" }, text: error })],
      null,
      "err",
    );
  }

  function renderSteps() {
    const steps = report.steps || [];
    const head = h("div", { class: "card-head" }, [
      h("h2", { text: "流程步骤" }),
      h("span", {
        class: `pill ${report.ok ? "ok" : "err"}`,
        text: report.ok ? "全部通过" : "存在失败",
      }),
      h("span", {
        class: "sub",
        text: `${report.started_at} · 共 ${steps.length} 步 · ${report.elapsed_ms} ms`,
      }),
    ]);
    const list = h(
      "div",
      { class: "step-list" },
      steps.map((step) => {
        const meta = STEP_STATUS[step.status] || { cls: "", label: step.status };
        return h("div", { class: `step is-${step.status}` }, [
          h("span", { class: `pill ${meta.cls}`.trim(), text: meta.label }),
          h("span", { class: "step-name", text: step.name }),
          h("span", { class: "step-detail", text: step.detail || "" }),
          h("span", { class: "step-ms", text: `${step.elapsed_ms} ms` }),
        ]);
      }),
    );
    return h("section", { class: "card" }, [head, list]);
  }

  function renderSummary() {
    const entries = Object.entries(report.summary || {});
    if (!entries.length) {
      return card("解析结果", "流程没走到产出结果", [emptyBox("没有可展示的解析结果")]);
    }
    return card(
      "解析结果",
      report.platform ? `平台：${report.platform}` : "",
      [
        h(
          "dl",
          { class: "detail-grid" },
          entries.map(([key, value]) => [
            h("dt", { text: key }),
            h("dd", { text: String(value) }),
          ]),
        ),
      ],
    );
  }

  function renderLog() {
    const downloadButton = h(
      "button",
      {
        class: "btn",
        type: "button",
        onClick: (event) => download(event.currentTarget),
      },
      "下载日志",
    );
    return card(
      "完整报告",
      `${report.log_name} · 含运行环境、流程步骤、解析结果与流程日志 · 已打码 Cookie / Token，可直接贴出`,
      [h("pre", { class: "log-view", text: report.text || "（空）" })],
      h("div", { class: "toolbar" }, [downloadButton]),
    );
  }

  /* ---------------- 行为 ---------------- */

  async function run(button) {
    const target = String(url || "").trim();
    if (!target) {
      toast("请先填写链接", "warn");
      return;
    }
    if (!/^https?:\/\//i.test(target)) {
      toast("链接需要以 http:// 或 https:// 开头", "warn");
      return;
    }

    running = true;
    error = "";
    report = null;
    const restore = withBusy(button, true, "测试中…");
    render();
    try {
      report = await ctx.api.post("debug/run", {
        url: target,
        download_media: downloadMedia,
        render_card: renderCard,
      });
      if (report.ok) {
        // 跳过是「按设计不做」而不是故障，单独说明，免得被当成失败
        const skipped = report.steps.filter((step) => step.status === "skip").length;
        const suffix = skipped ? `，${skipped} 步按设计跳过` : "";
        toast(`测试完成，${report.steps.length - skipped} 步通过${suffix}`, "ok");
      } else {
        const failed = report.steps.filter((step) => step.status === "fail").map((step) => step.name);
        toast(`测试完成，失败步骤：${failed.join("、")}`, "err");
      }
    } catch (err) {
      error = err.message || String(err);
      toast(`测试失败：${error}`, "err");
    } finally {
      running = false;
      restore();
      render();
    }
  }

  async function download(button) {
    if (!report) return;
    const restore = withBusy(button, true, "下载中…");
    try {
      await ctx.api.download(
        "debug/log",
        { token: report.token },
        `rika_debug_${report.token}.log`,
      );
    } catch (err) {
      toast(`下载失败：${err.message || err}`, "err");
    } finally {
      restore();
    }
  }

  return {
    async mount(node) {
      container = node;
      render();
    },
    /** 顶栏「刷新」：清掉上一次结果，回到干净状态（不动已填的链接）。 */
    async refresh() {
      report = null;
      error = "";
      running = false;
      render();
    },
  };
}
