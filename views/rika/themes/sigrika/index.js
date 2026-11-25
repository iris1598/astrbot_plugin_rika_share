/**
 * 西格莉卡 · 符文手账（Sigrika Rune Journal）
 *
 * 《鸣潮》角色「西格莉卡」与伴生「日灵」的专属整页网页主题：
 * - 页面骨架：手账扉页 Hero（头像 + 星芒风车发饰徽记 + 旅途絮语）
 *   → 吸顶「旅途路线」导航（启程 / 同行 / 符文 / 归家 四站）
 *   → 作用域横栏 → 当前站点舞台 → 星轨尾注；
 * - 装饰层：固定星芒、符文碎片与两枝荆棘藤蔓（纯 SVG，DOM 构建，零外链资源）；
 * - 日灵伙伴常驻右下角，点击会根据未保存改动给出提醒。
 *
 * 业务视图复用 studio 主题的四个无头视图工厂，本主题只负责整页结构与视觉。
 */
import { createInlineConfirmButton, h, preserveScroll, swapContent } from "../../core/dom.js";
import { subscribeThemes } from "../registry.js";
import { createStudioCardView } from "../studio/views/card_studio.js";
import { createStudioPlatformsView } from "../studio/views/platforms.js";
import { createStudioSystemView } from "../studio/views/system.js";
import { createStudioWorkbenchView } from "../studio/views/workbench.js";

const AVATAR_URL = new URL("./assets/avatar.png", import.meta.url).href;
const SVG_NS = "http://www.w3.org/2000/svg";

const STOPS = [
  { id: "workbench", no: "I", stop: "启程", label: "总览与诊断", desc: "看看运行状态，再用一条链接试试脚下的路" },
  { id: "platforms", no: "II", stop: "同行", label: "平台与账号", desc: "决定与哪些平台结伴同行，备好账号凭据与代理" },
  { id: "studio", no: "III", stop: "符文", label: "卡片工作室", desc: "以样式与节点编排刻下属于你的解析卡片符文" },
  { id: "system", no: "IV", stop: "归家", label: "主题与兜底", desc: "整页主题、昼暮配色与 Cloudflare 兜底设定" },
];

const STORY_LINES = [
  "通往浮光林的道路，不长也不短。",
  "碰到拦路的阻碍，就用符文开辟道路吧。",
  "遇见亲切的小动物，便与它们同行。",
  "浮光林的阳光，软软地晒在脸上。",
  "那些热切的期待，暂时先放在脑后吧！",
  "日灵与西格莉卡，烦恼着走在回家的路上。",
];

const COLOR_MODES = [
  { id: "light", label: "昼", title: "浮光林昼（浅色）" },
  { id: "dark", label: "暮", title: "星憩暮云（深色）" },
  { id: "auto", label: "随", title: "跟随系统" },
];

/* ------------------------------ SVG 小工具 ------------------------------ */

function s(tag, attrs = {}, children = []) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v != null) el.setAttribute(k, String(v));
  }
  for (const c of children) if (c) el.appendChild(c);
  return el;
}

/** 凹四角星芒 ✦（24×24 视窗） */
const STAR_D = "M12 0C12.9 7.6 16.4 11.1 24 12C16.4 12.9 12.9 16.4 12 24C11.1 16.4 7.6 12.9 0 12C7.6 11.1 11.1 7.6 12 0Z";

function starSvg(cls = "sg-star", size = 14) {
  return s("svg", { class: cls, viewBox: "0 0 24 24", width: size, height: size, "aria-hidden": "true" }, [
    s("path", { d: STAR_D }),
  ]);
}

/** 浮光林符文碎片（角状折线，呼应插画中飞舞的回纹符文） */
const RUNE_PATHS = [
  "M4 4h16v16H8V8h8v8h-4",
  "M4 20L12 4l8 16H9l3-6",
  "M5 5h14L5 19h14",
  "M7 3v18M7 12l10-8M7 12l10 8",
  "M4 8l8-4 8 4v8l-8 4-8-4zM12 4v16",
  "M5 19V5l7 7 7-7v14",
];

function runeSvg(idx, cls = "sg-rune", size = 22) {
  return s(
    "svg",
    {
      class: cls,
      viewBox: "0 0 24 24",
      width: size,
      height: size,
      fill: "none",
      "stroke-width": "2.2",
      "stroke-linecap": "square",
      "stroke-linejoin": "miter",
      "aria-hidden": "true",
    },
    [s("path", { d: RUNE_PATHS[idx % RUNE_PATHS.length] })],
  );
}

/** 西格莉卡标志性「机械四角风车星芒发饰」徽记 */
function pinwheelSvg(cls = "sg-pinwheel", size = 64) {
  const blades = [0, 90, 180, 270].map((deg) =>
    s("g", { transform: `rotate(${deg + 18})` }, [
      s("polygon", { class: "pw-blade", points: "0,-4 15,-12 7,-47 -6,-19" }),
      s("polygon", { class: "pw-shade", points: "0,-4 7,-47 -6,-19" }),
      s("line", { class: "pw-edge", x1: 0, y1: -8, x2: 6, y2: -40 }),
    ]),
  );
  return s("svg", { class: cls, viewBox: "-50 -50 100 100", width: size, height: size, "aria-hidden": "true" }, [
    ...blades,
    s("path", { class: "pw-core", d: STAR_D, transform: "translate(-11 -11) scale(0.92)" }),
    s("circle", { class: "pw-dot", cx: 0, cy: 0, r: 2.6 }),
  ]);
}

/** 沿三次贝塞尔曲线生成一枝带刺荆棘藤蔓 */
function thornBranch(p0, p1, p2, p3, { thorns = 12, len = 14, base = 4.5, width = 5 } = {}) {
  const bez = (t, a, b, c, d) => {
    const u = 1 - t;
    return u * u * u * a + 3 * u * u * t * b + 3 * u * t * t * c + t * t * t * d;
  };
  const der = (t, a, b, c, d) => {
    const u = 1 - t;
    return 3 * u * u * (b - a) + 6 * u * t * (c - b) + 3 * t * t * (d - c);
  };
  const g = s("g", { class: "sg-thorn" });
  g.appendChild(
    s("path", {
      class: "sg-thorn-stem",
      d: `M${p0[0]} ${p0[1]}C${p1[0]} ${p1[1]} ${p2[0]} ${p2[1]} ${p3[0]} ${p3[1]}`,
      fill: "none",
      "stroke-width": width,
      "stroke-linecap": "round",
    }),
  );
  for (let i = 1; i <= thorns; i += 1) {
    const t = i / (thorns + 1);
    const x = bez(t, p0[0], p1[0], p2[0], p3[0]);
    const y = bez(t, p0[1], p1[1], p2[1], p3[1]);
    let dx = der(t, p0[0], p1[0], p2[0], p3[0]);
    let dy = der(t, p0[1], p1[1], p2[1], p3[1]);
    const n = Math.hypot(dx, dy) || 1;
    dx /= n;
    dy /= n;
    const side = i % 2 ? 1 : -1;
    const l = len * (0.75 + ((i * 37) % 10) / 20);
    const tipX = x - dy * side * l + dx * l * 0.45;
    const tipY = y + dx * side * l + dy * l * 0.45;
    const pts = [
      [x - dx * base, y - dy * base],
      [x + dx * base, y + dy * base],
      [tipX, tipY],
    ]
      .map((p) => p.map((v) => v.toFixed(1)).join(","))
      .join(" ");
    g.appendChild(s("polygon", { class: "sg-thorn-spike", points: pts }));
  }
  return g;
}

/** 「• • • ◇ ── ✦」星轨装饰线 */
function starRail(cls = "") {
  return h(
    "div",
    { class: `sg-rail ${cls}`.trim(), "aria-hidden": "true" },
    h("i", { class: "sg-rail-dot" }),
    h("i", { class: "sg-rail-dot" }),
    h("i", { class: "sg-rail-dot" }),
    h("i", { class: "sg-rail-diamond" }),
    h("i", { class: "sg-rail-line" }),
    starSvg("sg-rail-star", 14),
  );
}

/* ------------------------------ 背景装饰层 ------------------------------ */

const SKY_STARS = [
  [6, 14, 18], [14, 62, 12], [22, 30, 9], [33, 86, 14], [47, 8, 10],
  [58, 72, 16], [71, 22, 11], [79, 54, 9], [88, 12, 20], [93, 78, 12],
  [40, 44, 8], [64, 92, 10],
];
const SKY_RUNES = [
  [10, 40, 0, -12], [27, 12, 1, 8], [52, 90, 2, -6], [76, 36, 3, 14], [90, 66, 4, -10], [36, 68, 5, 6],
];

function buildSky() {
  const sky = h("div", { class: "sg-sky", "aria-hidden": "true" });
  SKY_STARS.forEach(([x, y, size], i) => {
    const st = starSvg(`sg-sky-star ${i % 3 === 0 ? "is-gold" : i % 3 === 1 ? "is-lilac" : "is-orange"}`, size);
    st.style.left = `${x}%`;
    st.style.top = `${y}%`;
    st.style.animationDelay = `${(i * 0.73) % 5}s`;
    sky.appendChild(st);
  });
  SKY_RUNES.forEach(([x, y, idx, rot], i) => {
    const r = runeSvg(idx, "sg-sky-rune", 26);
    r.style.left = `${x}%`;
    r.style.top = `${y}%`;
    r.style.transform = `rotate(${rot}deg)`;
    r.style.animationDelay = `${i * 1.3}s`;
    sky.appendChild(r);
  });

  const vineBL = s("svg", { class: "sg-vine sg-vine-bl", viewBox: "0 0 360 360", preserveAspectRatio: "xMinYMax meet" }, [
    thornBranch([-10, 330], [80, 300], [120, 220], [210, 200], { thorns: 11 }),
    thornBranch([-10, 250], [40, 240], [70, 160], [40, 90], { thorns: 8, len: 11, width: 4 }),
    thornBranch([60, 370], [110, 330], [210, 330], [300, 352], { thorns: 9, len: 12, width: 4 }),
  ]);
  const vineTR = s("svg", { class: "sg-vine sg-vine-tr", viewBox: "0 0 360 360", preserveAspectRatio: "xMaxYMin meet" }, [
    thornBranch([370, 20], [290, 40], [250, 110], [170, 120], { thorns: 10 }),
    thornBranch([370, 110], [330, 120], [300, 190], [330, 260], { thorns: 7, len: 11, width: 4 }),
  ]);
  sky.appendChild(vineBL);
  sky.appendChild(vineTR);
  return sky;
}

/* ------------------------------ 日灵伙伴 ------------------------------ */

let soliSeq = 0;

function buildSoliskinEar(isRight, ids) {
  const wrapAttrs = isRight ? { transform: "translate(184 0) scale(-1 1)" } : {};
  /* 头顶高耸尖长棱角晶耳 + 发光耳尖 + 折线符文脉络 + 耳根前置小圆绒球 */
  return s("g", wrapAttrs, [
    s("g", { transform: "translate(68 58)" }, [
      s("g", { class: "sg-soli-ear" }, [
        s("path", {
          class: "sg-soli-fill",
          fill: `url(#${ids.body})`,
          d: "M8 2L5 -22L-7 -50L-15 -22L-6 5Q1 7 8 2Z",
        }),
        s("path", {
          class: "sg-soli-ear-facet",
          d: "M-7 -50L-1.5 -21L-6 5L-15 -22Z",
        }),
        s("path", {
          class: "sg-soli-ear-tip",
          fill: `url(#${ids.earTip})`,
          d: "M5 -22L-7 -50L-15 -22Q-5 -17 5 -22Z",
        }),
        s("path", {
          class: "sg-soli-outline",
          d: "M7.2 0L5 -22L-7 -50L-15 -22L-6.5 3.5",
        }),
        s("path", {
          class: "sg-soli-ear-vein",
          d: "M0 0L-2.2 -15L-6.8 -23L-6.8 -39",
        }),
        s("circle", { class: "sg-soli-mark-dot", cx: -2.2, cy: -15, r: 1.7 }),
        s("ellipse", {
          class: "sg-soli-ear-bud",
          fill: `url(#${ids.body})`,
          cx: -9.5,
          cy: 3.5,
          rx: 6.8,
          ry: 5.4,
          transform: "rotate(-22 -9.5 3.5)",
        }),
        s("ellipse", {
          class: "sg-soli-bud-shine",
          cx: -11.2,
          cy: 1.8,
          rx: 2.6,
          ry: 1.5,
          transform: "rotate(-22 -11.2 1.8)",
        }),
      ]),
    ]),
  ]);
}

function buildSoliskinArm(isRight, ids) {
  const wrapAttrs = isRight ? { transform: "translate(184 0) scale(-1 1)" } : {};
  /* 身体中下部向两侧伸展的宽袖耳翼（肩部无接缝融合）+ 暖白双环纹与圆环符文 */
  return s("g", wrapAttrs, [
    s("g", { transform: "translate(56 106)" }, [
      s("g", { class: "sg-soli-arm" }, [
        s("path", {
          class: "sg-soli-fill",
          fill: `url(#${ids.body})`,
          d: "M6 -12C-8 -7 -26 1 -41 -5Q-48 -8 -50 -2C-51 9 -37 21 -20 19C-8 17 1 15 7 13Z",
        }),
        s("path", {
          class: "sg-soli-tip-glow",
          fill: `url(#${ids.armTip})`,
          d: "M-24 -1C-32 0 -38 -3 -41 -5Q-48 -8 -50 -2C-51 8 -39 19 -24 19C-21 12 -21 5 -24 -1Z",
        }),
        s("path", { class: "sg-soli-mark-line", d: "M-47 -1Q-31 6 -11 6" }),
        s("path", { class: "sg-soli-mark-band", d: "M-38 -3.5Q-33 7 -37.5 15.5" }),
        s("path", { class: "sg-soli-mark-band", d: "M-24.5 -1Q-19.5 8.5 -24 18" }),
        s("circle", { class: "sg-soli-mark-ring", cx: -31.5, cy: 11.2, r: 2.8 }),
        s("circle", { class: "sg-soli-mark-dot", cx: -42.5, cy: 4.5, r: 1.5 }),
        s("path", {
          class: "sg-soli-outline",
          d: "M2 -10.5C-10 -6 -27 1 -41 -5Q-48 -8 -50 -2C-51 9 -37 21 -20 19C-9 17.5 -1 15.5 4 14",
        }),
      ]),
    ]),
  ]);
}

function buildSoliskin(onClick) {
  const uid = `sg-soli-${++soliSeq}`;
  const ids = {
    body: `${uid}-body`,
    dawn: `${uid}-dawn`,
    earTip: `${uid}-ear-tip`,
    armTip: `${uid}-arm-tip`,
    clip: `${uid}-clip`,
  };

  /* 八芒朝霞太阳纹（饱满八瓣日光芒 + 圆润日核） */
  const sunRays = Array.from({ length: 8 }, (_, i) => {
    const outer = i % 2 === 0 ? -16.2 : -14.6;
    return s("polygon", {
      class: "sg-soli-sun-ray",
      points: `0,${outer} 2.8,-9.8 0,-7.5 -2.8,-9.8`,
      transform: `rotate(${i * 45})`,
    });
  });

  const svg = s(
    "svg",
    { class: "sg-soli-svg", viewBox: "0 0 184 168", "aria-hidden": "true" },
    [
      s("defs", {}, [
        s("radialGradient", { id: ids.body, cx: "38%", cy: "26%", r: "74%" }, [
          s("stop", { offset: "0%", class: "sg-stop-body-hi" }),
          s("stop", { offset: "55%", class: "sg-stop-body-mid" }),
          s("stop", { offset: "100%", class: "sg-stop-body-low" }),
        ]),
        s("linearGradient", { id: ids.dawn, x1: "20%", y1: "6%", x2: "80%", y2: "96%" }, [
          s("stop", { offset: "0%", class: "sg-stop-dawn-top" }),
          s("stop", { offset: "48%", class: "sg-stop-dawn-mid" }),
          s("stop", { offset: "100%", class: "sg-stop-dawn-bot" }),
        ]),
        s("linearGradient", { id: ids.earTip, x1: "35%", y1: "0%", x2: "55%", y2: "100%" }, [
          s("stop", { offset: "0%", class: "sg-stop-tip-hi" }),
          s("stop", { offset: "100%", class: "sg-stop-tip-fade" }),
        ]),
        s("radialGradient", { id: ids.armTip, cx: "12%", cy: "36%", r: "85%" }, [
          s("stop", { offset: "0%", class: "sg-stop-tip-hi" }),
          s("stop", { offset: "100%", class: "sg-stop-tip-fade" }),
        ]),
        s("clipPath", { id: ids.clip }, [
          s("circle", { cx: 92, cy: 86, r: 19.8 }),
        ]),
      ]),

      /* 地面投影与背后柔光 */
      s("ellipse", { class: "sg-soli-shadow", cx: 92, cy: 155, rx: 35, ry: 6 }),
      s("circle", { class: "sg-soli-aura", cx: 92, cy: 96, r: 60 }),

      /* 主体悬浮组 */
      s("g", { class: "sg-soli-float" }, [
        /* 头顶双层透视金色日冕光环 */
        s("g", { class: "sg-soli-crown" }, [
          s("ellipse", { class: "sg-soli-crown-outer", cx: 92, cy: 10.5, rx: 40, ry: 8.2 }),
          s("ellipse", { class: "sg-soli-crown-inner", cx: 92, cy: 10.5, rx: 26, ry: 5 }),
          s("path", {
            class: "sg-soli-crown-spokes",
            d: "M52 10.5H66M118 10.5H132M64 5.2L73.5 7.5M120 5.2L110.5 7.5M64 15.8L73.5 13.5M120 15.8L110.5 13.5M92 5.5V15.5",
          }),
          s("polygon", { class: "sg-soli-crown-gem", points: "92,7.4 96.5,10.5 92,13.6 87.5,10.5" }),
        ]),

        /* 圆润糯米团状青玉躯干 + 双层脸颊小绒毛 + 敦实小短足 */
        s("path", {
          class: "sg-soli-torso",
          fill: `url(#${ids.body})`,
          d:
            "M92 51C112 51 124 61 126.5 74L133 70.5Q131 76 128 79L131.5 79.5Q129.5 83.5 127.5 85.5" +
            "C132.5 102 130.5 123 118 135Q114.5 142.5 106 142.5Q99.5 142.5 97.5 138.5" +
            "Q92 139.5 86.5 138.5Q84.5 142.5 78 142.5Q69.5 142.5 66 135" +
            "C53.5 123 51.5 102 56.5 85.5Q54.5 83.5 52.5 79.5L56 79Q53 76 51 70.5L57.5 74" +
            "C60 61 72 51 92 51Z",
        }),

        /* 两侧无缝衔接的长袖耳翼与头顶晶耳（含前置耳根圆绒球） */
        buildSoliskinArm(false, ids),
        buildSoliskinArm(true, ids),
        buildSoliskinEar(false, ids),
        buildSoliskinEar(true, ids),

        /* 躯干柔和高光与星尘细闪 */
        s("ellipse", {
          class: "sg-soli-torso-shine",
          cx: 74,
          cy: 63,
          rx: 11.5,
          ry: 5,
          transform: "rotate(-24 74 63)",
        }),
        s("g", { class: "sg-soli-sparkles" }, [
          s("circle", { cx: 64, cy: 93, r: 1.25 }),
          s("circle", { cx: 120, cy: 91, r: 1.15 }),
          s("circle", { cx: 68, cy: 121, r: 1.35 }),
          s("circle", { cx: 116, cy: 119, r: 1.25 }),
          s("circle", { cx: 79, cy: 132, r: 1.05 }),
          s("circle", { cx: 92, cy: 57.5, r: 1.15 }),
        ]),

        /* 腹部对称荧光符文脉络与眼下托环 */
        s("g", { class: "sg-soli-belly-runes" }, [
          s("path", { class: "sg-soli-cradle", d: "M68 99A27.2 27.2 0 0 0 116 99" }),
          s("circle", { class: "sg-soli-cradle-node", cx: 67.2, cy: 97.5, r: 2.2 }),
          s("circle", { class: "sg-soli-cradle-node", cx: 116.8, cy: 97.5, r: 2.2 }),
          s("path", { class: "sg-soli-leaf", d: "M62.5 103.5Q59.5 108.5 63.5 112.5Q66.5 107.5 62.5 103.5Z" }),
          s("path", { class: "sg-soli-leaf", d: "M121.5 103.5Q124.5 108.5 120.5 112.5Q117.5 107.5 121.5 103.5Z" }),
          s("path", {
            class: "sg-soli-circuit",
            d: "M69 116Q78.5 124 88.2 125V135.5M115 116Q105.5 124 95.8 125V135.5M74 125Q79.5 129.5 85 130.5M110 125Q104.5 129.5 99 130.5",
          }),
          s("circle", { class: "sg-soli-circuit-dot", cx: 88.2, cy: 137.8, r: 1.5 }),
          s("circle", { class: "sg-soli-circuit-dot", cx: 95.8, cy: 137.8, r: 1.5 }),
        ]),

        /* 正中央「朝霞暖阳」大圆盘核心独眼 */
        s("circle", { class: "sg-soli-socket", cx: 92, cy: 86, r: 23 }),
        s("g", { "clip-path": `url(#${ids.clip})` }, [
          s("circle", { class: "sg-soli-orb", fill: `url(#${ids.dawn})`, cx: 92, cy: 86, r: 19.8 }),
          s("g", { transform: "translate(92 86)" }, [
            s("g", { class: "sg-soli-sun" }, [
              ...sunRays,
              s("circle", { class: "sg-soli-sun-disc", cx: 0, cy: 0, r: 6.1 }),
            ]),
          ]),
          /* 未保存改动时浮现的微垂烦恼眼睑 */
          s("path", { class: "sg-soli-worry-lid", d: "M70 64H114V77Q92 84 70 77Z" }),
          s("ellipse", {
            class: "sg-soli-orb-gloss",
            cx: 83.8,
            cy: 76.5,
            rx: 6,
            ry: 3.2,
            transform: "rotate(-30 83.8 76.5)",
          }),
        ]),
        s("circle", { class: "sg-soli-orb-rim", cx: 92, cy: 86, r: 19.8 }),
      ]),
    ],
  );

  const badge = h(
    "span",
    { class: "sg-soli-alert", "aria-hidden": "true" },
    starSvg("sg-soli-alert-star", 9),
    h("b", null, "!"),
  );

  return h(
    "button",
    { type: "button", class: "sg-soli", title: "日灵 · 小哆", "aria-label": "日灵伙伴：查看保存提醒", onclick: onClick },
    svg,
    badge,
  );
}

/* ================================ 主题 ================================ */

export default {
  id: "sigrika",
  name: "西格莉卡 · 符文手账",
  subtitle: "Sigrika Rune Journal · 浮光林旅途路线导航",
  description:
    "《鸣潮》西格莉卡角色专属整页设计：羊皮纸手账卡面 + 星芒风车发饰徽记 + 星轨荆棘框；四个页签化作「启程 / 同行 / 符文 / 归家」旅途站点，日灵伙伴常驻右下角。",
  badge: "角色",
  preview: "sigrika",
  order: 40,
  styles: ["themes/sigrika/theme.css"],

  mount(mountEl, appCtx) {
    const { store, bili, preview, debug, cache, onDispose } = appCtx;

    let activeTab = "workbench";
    let addingGroup = false;
    let newGroupInput = "";
    let newGroupLabel = "";
    let storyIdx = 0;

    const stopButtons = new Map();
    const viewHosts = new Map();

    /* ---------- Hero 扉页 ---------- */

    const quoteEl = h("p", { class: "sg-quote", title: "点击翻到下一句" }, STORY_LINES[0]);
    const nextQuote = () => {
      storyIdx = (storyIdx + 1) % STORY_LINES.length;
      quoteEl.classList.remove("is-turn");
      void quoteEl.offsetWidth;
      quoteEl.textContent = STORY_LINES[storyIdx];
      quoteEl.classList.add("is-turn");
    };
    quoteEl.addEventListener("click", nextQuote);
    const quoteTimer = window.setInterval(nextQuote, 12000);
    onDispose(() => window.clearInterval(quoteTimer));

    const scopeChipEl = h("span", { class: "sg-chip" });
    const modeWrap = h("div", { class: "sg-mode", role: "group", "aria-label": "昼暮配色" });
    const saveStripEl = h("div", { class: "save-strip sg-save" });

    const themePill = h(
      "button",
      { type: "button", class: "theme-badge-btn sg-theme-pill", onclick: () => switchTab("system") },
      starSvg("sg-pill-star", 11),
      appCtx.theme?.name || "西格莉卡 · 符文手账",
    );

    const hero = h(
      "header",
      { class: "sg-hero" },
      h("span", { class: "sg-corner is-tl", "aria-hidden": "true" }),
      h("span", { class: "sg-corner is-br", "aria-hidden": "true" }),
      h(
        "div",
        { class: "sg-portrait" },
        h("span", { class: "sg-portrait-ring", "aria-hidden": "true" }),
        h("img", { class: "sg-avatar", src: AVATAR_URL, alt: "西格莉卡", draggable: "false" }),
        pinwheelSvg("sg-pinwheel", 58),
      ),
      h(
        "div",
        { class: "sg-hero-text" },
        h("span", { class: "sg-kicker" }, "SIGRIKA", h("i", null, "·"), "RUNE JOURNAL", h("i", null, "·"), "莉卡解析"),
        h("h1", { class: "sg-title" }, "西格莉卡的", h("em", null, "符文手账")),
        quoteEl,
        h("div", { class: "sg-hero-meta" }, scopeChipEl, themePill, modeWrap),
      ),
      h("div", { class: "sg-hero-actions" }, saveStripEl),
      starRail("sg-hero-rail"),
    );

    /* ---------- 旅途路线导航 ---------- */

    const trail = h(
      "nav",
      { class: "sg-trail", role: "tablist", "aria-label": "旅途站点" },
      h("span", { class: "sg-trail-path", "aria-hidden": "true" }),
      STOPS.map((t, i) => {
        const btn = h(
          "button",
          {
            type: "button",
            role: "tab",
            class: `sg-stop ${t.id === activeTab ? "is-active" : ""}`,
            onclick: () => switchTab(t.id),
          },
          h("span", { class: "sg-stop-node", "aria-hidden": "true" }, h("i", { class: "sg-stop-diamond" }), starSvg("sg-stop-star", 22)),
          h(
            "span",
            { class: "sg-stop-text" },
            h("span", { class: "sg-stop-no" }, `第 ${t.no} 站 · ${t.stop}`),
            h("strong", { class: "sg-stop-label" }, t.label),
          ),
          runeSvg(i, "sg-stop-rune", 16),
        );
        stopButtons.set(t.id, btn);
        return btn;
      }),
    );

    /* ---------- 舞台 ---------- */

    const stageNoEl = h("span", { class: "sg-stage-no" });
    const stageTitleEl = h("h2", { class: "stage-title sg-stage-title" });
    const stageDescEl = h("p", { class: "stage-sub sg-stage-desc" });
    const stageHead = h(
      "div",
      { class: "sg-stage-head" },
      stageNoEl,
      h("div", { class: "sg-stage-heading" }, stageTitleEl, stageDescEl),
      runeSvg(2, "sg-stage-rune", 30),
    );

    const scopeBarEl = h("section", { class: "scope-bar sg-scope", "aria-label": "分群配置作用域" });

    const views = {
      workbench: createStudioWorkbenchView(appCtx, { navigate: switchTab }),
      platforms: createStudioPlatformsView(appCtx),
      studio: createStudioCardView(appCtx),
      system: createStudioSystemView(appCtx),
    };

    const stageBody = h("main", { class: "stage-body sg-stage-body" });
    for (const t of STOPS) {
      const holder = h(
        "div",
        { class: `tab-panel ${t.id === activeTab ? "" : "is-hidden"}`, role: "tabpanel" },
        views[t.id].element,
      );
      viewHosts.set(t.id, holder);
      stageBody.appendChild(holder);
    }

    const footer = h(
      "footer",
      { class: "sg-foot" },
      starRail("sg-foot-rail"),
      h("p", null, "在短暂的小憩中，会不会梦到大家的期望都获得实现的明天呢？"),
      h("span", { class: "sg-foot-sign" }, "— Sigrika & Soliskin"),
    );

    /* ---------- 日灵伙伴 ---------- */

    const soli = buildSoliskin(() => {
      const dirty = store.dirtyKeys().length;
      soli.classList.remove("is-hop");
      void soli.offsetWidth;
      soli.classList.add("is-hop");
      if (store.saving) {
        store.toast("日灵：正在努力把符文刻进配置里…", "info");
      } else if (dirty > 0) {
        store.toast(`日灵：咕噜！还有 ${dirty} 项改动没保存哦`, "warn");
      } else {
        const lines = [
          "日灵：一切都同步好啦，可以安心小憩～",
          "日灵：哆的声音，是太阳，是朝霞的颜色～ ✦",
          "日灵蹭了蹭你的手心 ✦",
          "日灵：今天也一起走回家吧！",
        ];
        store.toast(lines[Math.floor(Math.random() * lines.length)], "ok");
      }
    });

    const shell = h(
      "div",
      { class: "app-shell sg-shell" },
      buildSky(),
      h(
        "div",
        { class: "sg-page" },
        hero,
        trail,
        scopeBarEl,
        h("section", { class: "sg-stage" }, stageHead, stageBody),
        footer,
      ),
      soli,
    );

    /* ---------- 渲染函数 ---------- */

    function syncAllViews() {
      preserveScroll(() => {
        for (const v of Object.values(views)) v?.sync?.();
      });
    }

    function renderStageHead() {
      const t = STOPS.find((x) => x.id === activeTab) || STOPS[0];
      stageNoEl.textContent = t.no;
      stageTitleEl.textContent = `${t.stop} · ${t.label}`;
      stageDescEl.textContent = t.desc;
    }

    function renderModeToggle() {
      const current = String(store.draft?.WEBUI_COLOR_MODE || "auto").toLowerCase();
      const locked = Boolean(store.scope);
      swapContent(
        modeWrap,
        COLOR_MODES.map((m) =>
          h(
            "button",
            {
              type: "button",
              class: `sg-mode-btn ${current === m.id ? "is-active" : ""}`,
              title: locked ? `${m.title}（仅全局可修改）` : m.title,
              disabled: locked || store.saving,
              "aria-pressed": current === m.id ? "true" : "false",
              onclick: () => appCtx.setColorModePreference?.(m.id),
            },
            m.label,
          ),
        ),
      );
    }

    function renderScopeChip() {
      scopeChipEl.classList.toggle("is-group", Boolean(store.scope));
      scopeChipEl.textContent = store.scope ? `分群 · ${store.scopeLabel || store.scope}` : "全局 · 所有群聊";
    }

    function renderSaveStrip() {
      const changed = store.dirtyKeys();
      saveStripEl.classList.toggle("has-dirty", changed.length > 0);
      soli.classList.toggle("is-worried", changed.length > 0);
      const nodes = [];
      if (changed.length > 0) {
        nodes.push(
          h(
            "div",
            { class: "save-info" },
            h("span", { class: "dirty-dot" }),
            h("strong", null, `${changed.length} 枚符文待刻印`),
          ),
          h(
            "button",
            { type: "button", class: "btn btn-ghost btn-sm", disabled: store.saving, onclick: () => store.discardDraft() },
            "放弃",
          ),
        );
      }
      nodes.push(
        createInlineConfirmButton({
          label: store.scope ? "清空覆写" : "恢复默认",
          confirmLabel: store.scope ? "确认清空" : "确认重置",
          variant: "ghost",
          size: "sm",
          onConfirm: () => store.resetConfig(),
        }),
        h(
          "button",
          {
            type: "button",
            class: "btn btn-primary btn-sm sg-save-btn",
            disabled: store.saving || changed.length === 0,
            onclick: () => store.saveDirty(),
          },
          starSvg("sg-btn-star", 12),
          store.saving ? "刻印中…" : changed.length > 0 ? "保存并生效" : "已同步",
        ),
      );
      swapContent(saveStripEl, nodes);
    }

    function renderScopeBar() {
      const profiles = Array.isArray(store.groupProfiles) ? store.groupProfiles : [];
      const overridden = profiles.filter((p) => p.has_override);
      const known = profiles.filter((p) => !p.has_override);
      const inProfiles = profiles.some((p) => p.scope_id === store.scope);

      const selectEl = h(
        "select",
        {
          class: "ctrl-input ctrl-sm scope-select",
          disabled: store.scopeBusy || store.saving,
          onchange: (e) => store.switchScope(e.target.value),
        },
        h("option", { value: "" }, "全局默认（所有未单独配置的群）"),
        overridden.length > 0
          ? h(
              "optgroup",
              { label: "已独立配置的分群" },
              overridden.map((p) =>
                h("option", { value: p.scope_id }, `${p.display_name || p.scope_id}（独立 ${p.override_count || 0} 项 · ${p.scope_id}）`),
              ),
            )
          : null,
        known.length > 0
          ? h(
              "optgroup",
              { label: "已知 / 活跃群聊" },
              known.map((p) => h("option", { value: p.scope_id }, `${p.display_name || p.scope_id}（${p.scope_id}）`)),
            )
          : null,
        store.scope && !inProfiles ? h("option", { value: store.scope }, `${store.scopeLabel}（${store.scope}）`) : null,
      );
      selectEl.value = store.scope;

      const statusBadge = store.scope
        ? h(
            "span",
            { class: `pill ${store.overrideKeys.size > 0 ? "pill-info" : ""}` },
            store.overrideKeys.size > 0 ? `本群独立 ${store.overrideKeys.size} 项` : "继承全局（尚未单独覆盖）",
          )
        : h(
            "span",
            { class: `pill ${overridden.length > 0 ? "pill-info" : ""}` },
            overridden.length > 0 ? `已单独配置 ${overridden.length} 个分群` : "全局生效",
          );

      scopeBarEl.classList.toggle("is-group-scope", Boolean(store.scope));
      const nodes = [
        h(
          "div",
          { class: "scope-bar-row" },
          h(
            "div",
            { class: "scope-bar-left" },
            h("span", { class: "scope-label" }, runeSvg(4, "sg-scope-rune", 15), "作用域"),
            selectEl,
            statusBadge,
            store.scope
              ? h("span", { class: "scope-tip" }, "仅分群可覆写零重解析代价项，账号凭据/清晰度/代理/网页主题锁定为全局")
              : null,
          ),
          h(
            "div",
            { class: "scope-bar-actions" },
            store.scope
              ? h(
                  "button",
                  { type: "button", class: "btn btn-ghost btn-sm", disabled: store.scopeBusy, onclick: () => store.switchScope("") },
                  "返回全局",
                )
              : null,
            h(
              "button",
              {
                type: "button",
                class: "btn btn-soft btn-sm",
                disabled: store.scopeBusy,
                onclick: () => {
                  addingGroup = !addingGroup;
                  renderScopeBar();
                },
              },
              addingGroup ? "收起添加" : "+ 添加分群",
            ),
            store.scope
              ? createInlineConfirmButton({
                  label: "移除档案",
                  confirmLabel: "确认移除",
                  variant: "ghost",
                  size: "sm",
                  onConfirm: () => store.deleteGroupScope(store.scope),
                })
              : null,
          ),
        ),
      ];

      if (addingGroup) {
        const submitNewGroup = async () => {
          const ok = await store.createGroupScope(newGroupInput, newGroupLabel);
          if (ok) {
            addingGroup = false;
            newGroupInput = "";
            newGroupLabel = "";
            renderScopeBar();
          }
        };
        const idInp = h("input", {
          type: "text",
          class: "ctrl-input ctrl-sm mono scope-add-id",
          placeholder: "群号（如 123456）或 UMO（如 napcat:GroupMessage:123456）",
          oninput: (e) => {
            newGroupInput = e.target.value;
          },
          onkeydown: (e) => {
            if (e.key === "Enter" && !store.scopeBusy) submitNewGroup();
          },
        });
        idInp.value = newGroupInput;
        const labelInp = h("input", {
          type: "text",
          class: "ctrl-input ctrl-sm scope-add-label",
          placeholder: "群备注名称（可选，如 测试群）",
          oninput: (e) => {
            newGroupLabel = e.target.value;
          },
          onkeydown: (e) => {
            if (e.key === "Enter" && !store.scopeBusy) submitNewGroup();
          },
        });
        labelInp.value = newGroupLabel;
        nodes.push(
          h(
            "div",
            { class: "scope-add-form" },
            idInp,
            labelInp,
            h(
              "button",
              { type: "button", class: "btn btn-primary btn-sm", disabled: store.scopeBusy, onclick: submitNewGroup },
              store.scopeBusy ? "创建中…" : "创建并切换",
            ),
            h(
              "button",
              {
                type: "button",
                class: "btn btn-ghost btn-sm",
                disabled: store.scopeBusy,
                onclick: () => {
                  addingGroup = false;
                  renderScopeBar();
                },
              },
              "取消",
            ),
          ),
        );
      }
      swapContent(scopeBarEl, nodes);
    }

    function switchTab(tabId) {
      if (!viewHosts.has(tabId)) return;
      activeTab = tabId;
      for (const [id, holder] of viewHosts.entries()) holder.classList.toggle("is-hidden", id !== tabId);
      let passed = true;
      for (const t of STOPS) {
        const btn = stopButtons.get(t.id);
        const isActive = t.id === tabId;
        btn.classList.toggle("is-active", isActive);
        btn.classList.toggle("is-passed", passed && !isActive);
        btn.setAttribute("aria-selected", isActive ? "true" : "false");
        if (isActive) passed = false;
      }
      trail.style.setProperty("--sg-progress", String(STOPS.findIndex((t) => t.id === tabId) / (STOPS.length - 1)));
      renderStageHead();
      views[tabId]?.onActivated?.();
      views[tabId]?.sync?.();
    }

    function renderChrome() {
      renderScopeChip();
      renderModeToggle();
      renderSaveStrip();
      renderScopeBar();
    }

    switchTab(activeTab);
    renderChrome();
    mountEl.appendChild(shell);

    /* ---------- 订阅 ---------- */

    onDispose(
      store.subscribe((ev) => {
        if (ev.type === "draft") {
          for (const row of mountEl.querySelectorAll(`.setting-item[data-key="${ev.key}"]`)) {
            row.classList.toggle("is-dirty", store.isKeyDirty(ev.key));
          }
          renderSaveStrip();
          if (ev.key === "WEBUI_COLOR_MODE") renderModeToggle();
          if (ev.reverted) {
            syncAllViews();
            preview.scheduleCard(0);
          } else if (ev.rerender && (ev.key === "RENDER_PERSONA_WATERMARK" || ev.key === "NODE_RULES")) {
            views.workbench?.sync?.();
          }
        } else if (ev.type === "snapshot" || ev.type === "discard") {
          renderChrome();
          syncAllViews();
          if (activeTab === "studio") preview.scheduleCard(0);
        } else if (ev.type === "scope" || ev.type === "saving") {
          renderChrome();
        } else if (ev.type === "overview" || ev.type === "devkeys") {
          syncAllViews();
        }
      }),
    );
    onDispose(
      bili.subscribe(() => {
        views.workbench?.sync?.();
        views.platforms?.syncBiliBox?.();
      }),
    );
    onDispose(
      preview.subscribe(() => {
        views.studio?.syncStyleGrid?.();
        views.studio?.updatePreviewStage?.();
      }),
    );
    onDispose(debug.subscribe(() => views.workbench?.sync?.()));
    onDispose(cache.subscribe(() => views.workbench?.sync?.()));
    onDispose(subscribeThemes(() => views.system?.sync?.()));

    return {
      unmount() {
        bili.stopPolling?.();
        shell.remove();
      },
      onColorModeChange() {
        renderModeToggle();
      },
    };
  },
};
