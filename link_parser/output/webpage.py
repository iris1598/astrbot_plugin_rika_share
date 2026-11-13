"""合并转发内容 → 一个可点开的网页，群里只发一条链接通知。

仅用于不支持 Comp.Nodes（合并转发）的平台：把「标题头 + 节点内容」渲染成一个
自包含的聊天记录式页面（浅/深色自适应、图片网格、灯箱），页面与图集图片都经
AstrBot 文件服务（``/api/file/{token}``，免鉴权路由，token 即访问凭据）下发，
链接用 AstrBot 的「对外可达的回调接口地址」（``callback_api_base``）拼出。

- 页面无外部资源；脚本用 CSP sha256 放行；``noindex,nofollow``。
- 图片不复制、不 base64：注册缓存目录里现成文件的 token 直接热链。链接时效与
  缓存共用（``CACHE_TTL_HOURS``），图片文件必然活得和链接一样久；token 是内存态，
  AstrBot 重启后旧链接失效。
- 同一内容复用同一网页：调用方以「内容标识 → (原始链接, 页面 token)」做复用表，
  token 失效自动重建（:func:`webpage_token_expired` 自校验）。
- QQ 官方平台（qq_official_full 适配器）把通知做成**原生图文卡片**（msg_type=8，
  经 ``Comp.Json`` raw 透传，卡片 url 经腾讯文档跳转页包装，封面取图集第一张压制），
  失败回退 markdown 链接（``use_markdown(True)``，无权限时适配器自动降级纯文本），
  再回退纯文本。其他平台发纯文本链接。

实现为独立编写；页面形态与交互设计参考 qbob（https://github.com/Loping151/qbob，
AGPL-3.0）的同名功能，未包含其代码文本——qbob 的许可证与本项目（MIT）不兼容，
当初借用的灯箱脚本 / CSS / autolink 已全部重写为本插件的独立实现。
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import html
import re
import time
import uuid
from pathlib import Path
from urllib.parse import quote, urlsplit

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
import astrbot.api.message_components as Comp

from ..config import get_config
from ..utils.cache import cleanup_cache_dir

__all__ = [
    "build_official_card",
    "build_official_card_assets",
    "create_webpage",
    "format_share_message",
    "tdocs_jump",
    "webpage_token_expired",
]

#: 页面里的说话人名称（解析者身份）
BOT_NAME = "莉卡解析"

# 头像底色候选（HSL 色相值）：按名字哈希取一个，同一名字整页同色
_HUES = (206, 152, 28, 338, 258, 176, 40, 296)

# 裸链接自动成链：在「已转义」的文本上扫描，不会误入标签内部
_URL_RE = re.compile(r"https?://[^\s<>\"']+")
#: URL 尾部应当剥出去的标点（中文/英文成对符号与句读）
_URL_TRAIL = "。，、；：！？…）】》」』.,;:!?)\"'"

# 腾讯文档的外链跳转页：经它打开的网页可在 QQ 内直接浏览
DOCS_JUMP = "https://docs.qq.com/scenario/link.html?url="

# QQ 官方图文卡片（card.type=tuwen）字段口径：四项必填，title/desc 按字符计
CARD_TITLE_MAX = 50
CARD_DESC_MAX = 200
# 封面高宽比夹在这个范围：再长只取顶部（图集长图很常见，不硬塞全图），再宽取中间
COVER_MAX_RATIO = 4 / 3
COVER_MIN_RATIO = 1 / 2
# 封面压小些：平台发送时当场下载转存 pic_url，字节越少越稳
COVER_MAX_WIDTH = 800


def tdocs_jump(url: str) -> str:
    """网址改为经腾讯文档的外链跳转页打开。

    已经是 docs.qq.com 的（包括已经是跳转页的）原样返回。
    """
    try:
        host = (urlsplit(url).hostname or "").lower()
    except Exception:
        host = ""
    if host == "docs.qq.com":
        return url
    return DOCS_JUMP + quote(url, safe="")


def _esc(text: object) -> str:
    return html.escape(str(text or ""), quote=True)


def _autolink(escaped: str) -> str:
    """把已转义文本里的裸 http(s) 链接替换成 <a>。

    链接尾部粘住的句读/收尾括号剥到 <a> 外面；转义产生的 ``&amp;`` 等实体
    不会被正则截断（排除集里没有 ``&``，查询串里的 ``&`` 是合法成分）。
    """
    pieces: list[str] = []
    cursor = 0
    for match in _URL_RE.finditer(escaped):
        raw = match.group(0)
        url = raw.rstrip(_URL_TRAIL)
        tail = raw[len(url):]
        pieces.append(escaped[cursor:match.start()])
        pieces.append(
            f'<a href="{url}" rel="noreferrer noopener" target="_blank">{url}</a>{tail}'
        )
        cursor = match.end()
    pieces.append(escaped[cursor:])
    return "".join(pieces)


def _hue_of(name: str) -> int:
    """名字 → _HUES 下标（CRC32 取模，稳定且分布均匀）。"""
    return binascii.crc32(name.encode("utf-8")) % len(_HUES)


def _tone_styles() -> str:
    """每个色相候选的头像底色（浅/深各一套）。"""
    light = "".join(
        f".tone-{i}{{--avatar-bg:hsl({h} 58% 92%);--avatar-fg:hsl({h} 44% 36%)}}"
        for i, h in enumerate(_HUES)
    )
    dark = "".join(
        f".tone-{i}{{--avatar-bg:hsl({h} 30% 26%);--avatar-fg:hsl({h} 56% 76%)}}"
        for i, h in enumerate(_HUES)
    )
    return f"{light}@media(prefers-color-scheme:dark){{{dark}}}"


_STYLE = """
:root{color-scheme:light dark;--page:#eef1f6;--card:#fff;--fg:#242830;--dim:#828b98;
--hair:rgba(36,40,48,.1);--chip:#e7eaf1;--chip-2:#d5d9e2;--accent:#2f7cf6;
--top:rgba(240,243,248,.86);--shadow:0 1px 3px rgba(18,22,30,.06),0 12px 30px rgba(18,22,30,.08);
--avatar-bg:var(--chip);--avatar-fg:var(--dim)}
@media(prefers-color-scheme:dark){:root{--page:#0e1013;--card:#1d2026;--fg:#e7e9ee;--dim:#8b93a1;
--hair:rgba(231,233,238,.09);--chip:#2a2e36;--chip-2:#343945;--accent:#5c9dff;
--top:rgba(14,16,19,.78);--shadow:0 12px 30px rgba(0,0,0,.45)}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--page);color:var(--fg);
font:15.5px/1.65 -apple-system,"PingFang SC","HarmonyOS Sans SC","MiSans",
"Noto Sans CJK SC","Microsoft YaHei",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
.topbar{position:sticky;top:0;z-index:3;background:var(--top);
-webkit-backdrop-filter:blur(16px) saturate(1.6);backdrop-filter:blur(16px) saturate(1.6);
border-bottom:1px solid var(--hair)}
.topbar-in{max-width:660px;margin:0 auto;padding:12px 18px;display:flex;
align-items:baseline;gap:10px}
h1{margin:0;font-size:16.5px;font-weight:650;letter-spacing:-.01em}
.meta{margin-left:auto;color:var(--dim);font-size:12.5px;white-space:nowrap;
font-variant-numeric:tabular-nums}
.card{max-width:660px;margin:14px auto 0;background:var(--card);border-radius:16px;
padding:6px 0 10px;box-shadow:var(--shadow)}
@media(max-width:700px){.card{margin:8px 8px 0}}
.notice{display:table;margin:10px auto 0;padding:2px 12px;border-radius:999px;
background:var(--chip);color:var(--dim);font-size:12px}
.thread{display:flex;gap:12px;padding:12px 18px 6px}
.avatar{flex:none;width:38px;height:38px;border-radius:50%;display:flex;align-items:center;
justify-content:center;font-weight:600;font-size:15px;background:var(--avatar-bg);
color:var(--avatar-fg);user-select:none}
.thread-main{flex:1;min-width:0}
.who{display:block;font-size:12.5px;font-weight:600;color:var(--avatar-fg);margin-bottom:2px}
.bubble{padding:3px 0}
.bubble+.bubble{margin-top:6px}
.bubble-text{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}
.bubble-text a{color:var(--accent);text-decoration:none}
.img-grid{display:grid;gap:4px;margin:6px 0 2px}
.img-grid.cols-2{grid-template-columns:1fr 1fr}
.img-grid.cols-3{grid-template-columns:1fr 1fr 1fr}
.img-grid a.shot{display:block;min-width:0;border-radius:10px;overflow:hidden;
background:var(--chip) center/cover no-repeat;box-shadow:inset 0 0 0 1px var(--hair)}
.img-grid a.shot:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.img-grid img{display:block;width:100%;height:100%;object-fit:cover;aspect-ratio:1}
.img-grid.cols-1 a.shot{width:fit-content;max-width:100%;min-width:96px;min-height:96px}
.img-grid.cols-1 img{width:auto;max-width:100%;height:auto;aspect-ratio:auto;
object-fit:fill;background:var(--chip)}
.img-lost{display:flex;align-items:center;justify-content:center;height:82px;
border-radius:10px;color:var(--dim);font-size:12.5px;background:repeating-linear-gradient(
135deg,var(--chip) 0 8px,var(--chip-2) 8px 9px)}
.img-grid .img-lost{height:auto;aspect-ratio:1}
.img-grid.cols-1 .img-lost{aspect-ratio:auto;height:82px}
.colophon{padding:18px 16px 30px;color:var(--dim);font-size:12px;text-align:center;
font-variant-numeric:tabular-nums}
.viewer{position:fixed;inset:0;z-index:9;display:none;background:#000}
.viewer.open{display:flex;align-items:center;justify-content:center;touch-action:none}
.viewer-img{max-width:100vw;max-height:100vh;object-fit:contain;user-select:none;
-webkit-user-drag:none;transition:transform .18s ease-out;will-change:transform}
.viewer-count{position:fixed;top:14px;left:0;right:0;text-align:center;color:#98999e;
font-size:13px;pointer-events:none}
.viewer button{position:fixed;z-index:2;border:0;background:rgba(20,20,22,.5);color:#f1f2f4;
font:20px/1 system-ui;width:42px;height:42px;border-radius:21px;cursor:pointer}
.viewer button:focus-visible{outline:2px solid #fff}
.viewer-close{top:12px;right:14px}
.viewer-prev,.viewer-next{top:50%;margin-top:-21px}
.viewer-prev{left:12px}.viewer-next{right:12px}
.viewer.single .viewer-prev,.viewer.single .viewer-next{display:none}
@media(prefers-reduced-motion:reduce){.viewer-img{transition:none}}
""".strip()

# 灯箱：点图开全屏层，左右按钮/方向键/横滑切图，双击缩放，点背景或 × 关闭。
# CSP 哈希在运行时按内容计算，改脚本无需手动更新。
_SCRIPT = """
(function () {
  var shots = [].slice.call(document.querySelectorAll('a.shot'));
  var box = document.getElementById('viewer');
  if (!shots.length || !box) return;
  var pic = box.querySelector('.viewer-img');
  var counter = box.querySelector('.viewer-count');
  var current = 0;
  var zoomed = false;

  function show(n) {
    current = (n + shots.length) % shots.length;
    pic.src = shots[current].getAttribute('href');
    counter.textContent = (current + 1) + ' / ' + shots.length;
    box.classList.add('open');
    document.documentElement.style.overflow = 'hidden';
  }
  function resetZoom() {
    if (!zoomed) return;
    zoomed = false;
    pic.style.transform = '';
  }
  function close() {
    box.classList.remove('open');
    pic.removeAttribute('src');
    document.documentElement.style.overflow = '';
  }
  function move(delta) {
    resetZoom();
    show(current + delta);
  }

  shots.forEach(function (a, index) {
    a.addEventListener('click', function (event) {
      event.preventDefault();
      resetZoom();
      show(index);
    });
  });
  box.addEventListener('click', function (event) {
    var button = event.target.closest('button');
    if (button) {
      if (button.classList.contains('viewer-prev')) move(-1);
      else if (button.classList.contains('viewer-next')) move(1);
      else close();
      return;
    }
    if (event.target !== pic) close();
  });
  document.addEventListener('keydown', function (event) {
    if (!box.classList.contains('open')) return;
    if (event.key === 'Escape') close();
    else if (event.key === 'ArrowLeft') move(-1);
    else if (event.key === 'ArrowRight') move(1);
  });
  pic.addEventListener('dblclick', function (event) {
    event.preventDefault();
    zoomed = !zoomed;
    pic.style.transform = zoomed ? 'scale(2.5)' : '';
  });
  var touchX = 0;
  box.addEventListener('touchstart', function (event) {
    touchX = event.touches[0].clientX;
  }, { passive: true });
  box.addEventListener('touchend', function (event) {
    var dx = event.changedTouches[0].clientX - touchX;
    if (Math.abs(dx) > 60) move(dx < 0 ? 1 : -1);
  }, { passive: true });
  if (shots.length === 1) box.classList.add('single');
})();
""".strip()


def _csp(script: str) -> str:
    """只放行指定哈希的脚本。

    页面经 AstrBot 文件服务下发，没有响应头可用，CSP 由 ``<meta>`` 标签承载
    （frame-ancestors 在 meta 里会被忽略，干脆不写）；``callback_api_base`` 允许
    填 http://（内网 / 未配 TLS），所以 img-src 也放开 http:。
    """
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    return ("default-src 'none'; img-src https: http: data:; "
            "style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; "
            f"script-src 'sha256-{digest}'")


def _summarize(total_items: int, n_pics: int) -> str:
    """一行摘要, 如 "5 条内容 · 8 张图片"。"""
    parts = [f"{total_items} 条内容"]
    if n_pics:
        parts.append(f"{n_pics} 张图片")
    return " · ".join(parts)


def summarize_items(text_items: list[list]) -> str:
    """一行摘要, 如 "5 条内容 · 8 张图片"（复用链接时也要拼通知文案, 故公开）。"""
    n_pics = sum(
        1
        for item in text_items
        for kind, _ in _collect_blocks(item)
        if kind == "pic"
    )
    return _summarize(len(text_items), n_pics)


def _render_pics(urls: list[str]) -> str:
    """相邻图片排成一格：1 张满栏不限高，2/4 张两列，其余三列。空串 = 已失效占位。"""
    cols = 1 if len(urls) == 1 else 2 if len(urls) in (2, 4) else 3
    cells: list[str] = []
    for url in urls:
        if url:
            # decoding=async: 大图解码不阻塞滚动
            cells.append(f'<a class="shot" href="{_esc(url)}">'
                         f'<img src="{_esc(url)}" alt="" loading="lazy" '
                         f'decoding="async"></a>')
        else:
            cells.append('<span class="img-lost">图片 · 已失效</span>')
    return f'<div class="img-grid cols-{cols}">{"".join(cells)}</div>'


def _collect_blocks(item: list) -> list[tuple[str, str]]:
    """一个节点内容 -> [(kind, value)]。

    kind: ``text``（value 为文本）或 ``pic``（value 为本地路径，可能为空串 = 失效）。
    相邻图片留在相邻的 pic 块里, 渲染时并成一格; 文本块先落盘再切换, 顺序不变。
    """
    blocks: list[tuple[str, str]] = []
    text_buf: list[str] = []

    def flush_text() -> None:
        text = "\n".join(text_buf).strip()
        text_buf.clear()
        if text:
            blocks.append(("text", text))

    for comp in item:
        if getattr(comp, "text", None):
            text_buf.append(str(comp.text))
            continue
        if isinstance(comp, Comp.Image):
            flush_text()
            # 同 estimate_item_bytes 的取法: fromFileSystem 的本地路径在 .path 上
            blocks.append(("pic", str(getattr(comp, "path", "") or "")))
    flush_text()
    return blocks


def _render_item(blocks: list[tuple[str, str]], urls: dict[str, str]) -> str:
    """单个节点 -> 气泡内容；相邻图片并成一格。"""
    out: list[str] = []
    pic_buf: list[str] = []

    def flush_pics() -> None:
        if pic_buf:
            out.append(_render_pics(pic_buf))
            pic_buf.clear()

    for kind, value in blocks:
        if kind == "pic":
            pic_buf.append(urls.get(value, "") if value else "")
            continue
        flush_pics()
        out.append(f'<p class="bubble-text">{_autolink(_esc(value))}</p>')
    flush_pics()
    return "".join(out)


def _shell(body: str, title: str) -> str:
    csp = _csp(_SCRIPT)
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        # 不开 viewport-fit=cover, 页面无需铺到刘海下
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow">'
        # 经 AstrBot 文件服务下发, CSP 只能写在 meta 里
        f'<meta http-equiv="Content-Security-Policy" content="{_esc(csp)}">'
        f"<title>{_esc(title)}</title>"
        f"<style>{_STYLE}{_tone_styles()}</style></head>"
        f"<body>{body}<script>{_SCRIPT}</script></body></html>"
    )


def render_share_page(
    header: str,
    summary: str,
    items_html: list[str],
    gone_pics: int,
    ttl_hours: int,
) -> str:
    """整页 HTML（不含图片地址解析，纯同步）。"""
    hue = _hue_of(BOT_NAME)
    bubbles = "".join(f'<div class="bubble">{part}</div>' for part in items_html)
    thread = (
        f'<section class="thread tone-{hue}">'
        f'<span class="avatar">{_esc(BOT_NAME[:1])}</span>'
        f'<div class="thread-main"><span class="who">{_esc(BOT_NAME)}</span>{bubbles}</div>'
        f"</section>"
    )
    notice = '<div class="notice">部分图片已失效</div>' if gone_pics else ""
    made = time.strftime("%Y-%m-%d %H:%M")
    if int(ttl_hours) > 0:
        ttl_note = f"链接约 {int(ttl_hours)} 小时内有效"
    else:
        ttl_note = "链接在 AstrBot 重启前有效"
    body = (
        '<header class="topbar"><div class="topbar-in">'
        f"<h1>{_esc(header or BOT_NAME)}</h1>"
        f'<span class="meta">{_esc(summary)}</span></div></header>'
        f'<main class="card">{notice}{thread}</main>'
        f'<footer class="colophon">{made} 生成 · {ttl_note}</footer>'
        '<div class="viewer" id="viewer"><span class="viewer-count"></span>'
        '<img class="viewer-img" alt="" draggable="false">'
        '<button class="viewer-prev" aria-label="上一张">‹</button>'
        '<button class="viewer-next" aria-label="下一张">›</button>'
        '<button class="viewer-close" aria-label="关闭">×</button></div>'
    )
    return _shell(body, title=header or BOT_NAME)


def _file_token_service():
    """AstrBot 文件服务全局单例（``/api/file/{token}``）。

    函数内导入（仓库惯例）：文件服务是较新版本 AstrBot 才有的全局单例，
    缺失时抛 ``RuntimeError``，由调用方回退纯文本输出。
    """
    try:
        from astrbot.core import file_token_service
    except Exception as e:  # noqa: BLE001 - 老版本 AstrBot 没有文件服务
        raise RuntimeError(f"AstrBot 文件服务不可用: {e}") from e
    return file_token_service


def _wants_tdocs(event: AstrMessageEvent) -> bool:
    """当前平台是否经腾讯文档跳转页打开链接。

    只对 QQ 系平台生效（平台名含 ``qq``；``aiocqhttp`` 不含该子串，且此路径
    本就只在非 OneBot 下到达），覆盖 qq_official / qq_official_webhook / qqguild / qq。
    """
    pconfig = get_config()
    if not pconfig.WEBPAGE_TDOCS_JUMP:
        return False
    try:
        name = (event.get_platform_name() or "").lower()
    except Exception:
        return False
    return "qq" in name


def _token_ttl_seconds(ttl_hours: int) -> float:
    """token 时效（秒）。

    ``ttl_hours`` 与缓存共用（``CACHE_TTL_HOURS``）：图片文件必然活得和链接一样久。
    ``0`` 表示「缓存永不清理」→ 链接也到 AstrBot 重启为止（文件服务没有永久项，用 10 年代替）。
    """
    return ttl_hours * 3600 if ttl_hours > 0 else 10 * 365 * 24 * 3600


async def create_webpage(
    event: AstrMessageEvent,
    header: str,
    text_items: list[list],
    *,
    page_dir: Path,
    base_url: str,
    ttl_hours: int,
) -> tuple[str, str]:
    """把「标题头 + 节点内容」全部转成网页并注册到文件服务。

    返回 ``(原始链接, 页面 token)``。页面与页内图片同批同时效注册（``single_use=False``），
    因此**页面 token 有效即整页可看**——调用方可据此对同一内容复用同一链接。
    任何失败都直接抛异常，由调用方回退 :func:`send_plain_output`。
    """
    if not text_items:
        raise ValueError("text_items 为空，无可转换内容")
    service = _file_token_service()
    # 防御性归一：main.py 已剥尾斜杠，这里再兜一层，避免拼出 //api/file/…
    base_url = str(base_url or "").strip().rstrip("/")
    if not base_url:
        raise RuntimeError("callback_api_base 为空，网页链接无处可拼")
    ttl_hours = max(int(ttl_hours), 0)
    timeout = _token_ttl_seconds(ttl_hours)

    # 机会式清理过期页面文件（页面很小, 目录里只有本插件生成的 .html；ttl=0 表示永不清理）
    if ttl_hours > 0:
        try:
            await cleanup_cache_dir(page_dir, ttl_hours=ttl_hours)
        except Exception:  # noqa: BLE001 - 清理失败不影响发送
            pass

    # 节点 -> 块, 并登记需要注册 token 的图片
    per_item_blocks = [_collect_blocks(item) for item in text_items]
    pic_paths: list[str] = []
    for blocks in per_item_blocks:
        for kind, value in blocks:
            if kind == "pic" and value:
                pic_paths.append(value)
    n_pics = sum(1 for blocks in per_item_blocks for kind, _ in blocks if kind == "pic")

    # 注册图片 token（同一文件只注册一次, 重复出现共用同一地址）
    urls: dict[str, str] = {}
    for path in dict.fromkeys(pic_paths):
        try:
            token = await service.register_file(path, timeout=timeout, single_use=False)
        except Exception as e:  # noqa: BLE001 - 单张失效不连累整页
            logger.warning(f"[link_parser] 网页图片注册失败（将显示为已失效）: {e}")
            continue
        urls[path] = f"{base_url}/api/file/{token}"

    items_html = [_render_item(blocks, urls) for blocks in per_item_blocks]
    gone_pics = len(pic_paths) - len(urls)
    page_html = render_share_page(
        header, _summarize(len(text_items), n_pics), items_html, gone_pics, ttl_hours
    )

    page_dir.mkdir(parents=True, exist_ok=True)
    page_path = page_dir / f"{int(time.time())}-{uuid.uuid4().hex[:8]}.html"
    await _write_page(page_path, page_html)

    token = await service.register_file(str(page_path), timeout=timeout, single_use=False)
    return f"{base_url}/api/file/{token}", token


def format_share_message(
    event: AstrMessageEvent,
    header: str,
    text_items: list[list],
    url: str,
    *,
    markdown: bool = False,
) -> str:
    """聊天里的链接通知文案。

    ``url`` 必须传**原始链接**（复用与新建都一样）：QQ 系平台在发送时现判并经
    腾讯文档跳转页包装，其他平台原样发出——同一链接在不同平台能以各自合适的形态出现。

    ``markdown=True``（QQ 官方平台）：链接拼成 ``[文案](链接)``，配
    ``MessageChain.use_markdown(True)`` 走 msg_type=2，QQ 内可直接点开；
    markdown 链接的文案里不能有 ``[ ] ( )``，先洗掉。
    """
    link = tdocs_jump(url) if _wants_tdocs(event) else url
    summary = summarize_items(text_items)
    if markdown:
        label = _clip_line(f"📄 {summary}，点击查看", 60)
        label = re.sub(r"[\[\]()]", " ", label).strip() or "点击查看"
        lines = [p for p in [header] if p]
        lines.append(f"[{label}]({link})")
        return "\n".join(lines)
    lines = []
    if header:
        lines.append(header)
    lines.append(f"📄 {summary}，点击查看：{link}")
    return "\n".join(lines)


def _clip_line(text: str, limit: int) -> str:
    """压成一行（换行在卡片上不显示），超长截断补省略号。"""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_official_card(title: str, desc: str, url: str, pic_url: str) -> dict | None:
    """QQ 官方 msg_type=8 图文卡片（``card.type=tuwen``）的 ``card`` 请求体。

    口径（实测）：四项必填；title ≤50、desc ≤200（按字符计）；**url 必须 https**
    （http 报 40011021）；pic_url 必须有——平台发送时当场下载转存，下不到整卡被拒
    （40034141）。条件不满足返回 None，由调用方回退 markdown / 纯文本。
    """
    url = str(url or "").strip()
    pic_url = str(pic_url or "").strip()
    if not url.startswith("https://"):
        return None
    if not pic_url.startswith(("https://", "http://")):
        return None
    title = _clip_line(title, CARD_TITLE_MAX) or BOT_NAME
    desc = _clip_line(desc, CARD_DESC_MAX) or "点击查看"
    return {
        "type": "tuwen",
        "content": {"title": title, "description": desc, "url": url, "pic_url": pic_url},
    }


def _make_cover_jpeg(src: str, out_dir: Path) -> Path | None:
    """任意图片 → 卡片封面 JPEG（同步，走线程池）。

    动图取首帧；高宽比夹到 [1/2, 4/3]（长图只取顶部，宽图取中间）；宽度压到
    800。文件名按来源稳定派生（同源复用），失败返回 None。
    """
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001 - Pillow 缺失（理论上不会，渲染依赖它）
        return None
    try:
        src_path = Path(src)
        digest = hashlib.md5(f"{src}:{src_path.stat().st_size}".encode()).hexdigest()[:12]
        out = Path(out_dir) / f"cover-{digest}.jpg"
        if out.exists():
            return out
        with Image.open(src_path) as im:
            if getattr(im, "n_frames", 1) > 1:
                im.seek(0)  # 动图取首帧
            frame = im.convert("RGB")
            w, h = frame.size
            if w <= 0 or h <= 0:
                return None
            if h / w > COVER_MAX_RATIO:  # 太长：只取顶部
                frame = frame.crop((0, 0, w, max(int(w * COVER_MAX_RATIO), 1)))
            elif h / w < COVER_MIN_RATIO:  # 太宽：取中间
                nh = max(int(w * COVER_MIN_RATIO), 1)
                top = max((h - nh) // 2, 0)
                frame = frame.crop((0, top, w, top + nh))
            if frame.width > COVER_MAX_WIDTH:
                frame = frame.resize(
                    (COVER_MAX_WIDTH, max(int(frame.height * COVER_MAX_WIDTH / frame.width), 1)),
                    Image.LANCZOS,
                )
            out_dir.mkdir(parents=True, exist_ok=True)
            frame.save(out, "JPEG", quality=85)
            return out
    except Exception as e:  # noqa: BLE001 - 封面做不出来就退级，不抛
        logger.warning(f"[link_parser] 卡片封面压制失败: {e}")
        return None


async def build_official_card_assets(
    event: AstrMessageEvent,
    header: str,
    text_items: list[list],
    *,
    page_url: str,
    page_dir: Path,
    base_url: str,
    ttl_hours: int,
) -> dict | None:
    """为网页链接构建 QQ 官方图文卡片（msg_type=8），条件不满足返回 None。

    封面取图集第一张可用图片（缓存目录里的原文件），压制后经文件服务下发——
    平台发送时当场下载转存，因此 ``callback_api_base`` 必须公网可达；
    跳转链接经腾讯文档包装后须 https（原始页 http 也行，包装后外层即 https）。
    """
    page_url = str(page_url or "").strip()
    # 卡片跳转只认 https（http 报 40011021）。经腾讯文档跳转页包装后外层已是
    # https://docs.qq.com/…，故校验包装后的 jump，原始页 http 也能成卡。
    jump = tdocs_jump(page_url) if _wants_tdocs(event) else page_url
    if not jump.startswith("https://"):
        return None

    cover_src = ""
    for item in text_items:
        for kind, value in _collect_blocks(item):
            if kind == "pic" and value and Path(value).is_file():
                cover_src = value
                break
        if cover_src:
            break
    if not cover_src:
        return None  # 没图：把文字渲成封面成本太高，直接退级
    cover_path = await asyncio.to_thread(_make_cover_jpeg, cover_src, Path(page_dir))
    if cover_path is None:
        return None

    service = _file_token_service()
    token = await service.register_file(
        str(cover_path), timeout=_token_ttl_seconds(ttl_hours), single_use=False
    )
    pic_url = f"{base_url.rstrip('/')}/api/file/{token}"
    return build_official_card(header, summarize_items(text_items), jump, pic_url)


async def webpage_token_expired(token: str) -> bool:
    """页面 token 是否已失效（过期 / AstrBot 重启丢失 / 文件服务不可用）。

    用于「同一内容复用同一网页」：失效即重建，因此调用方的复用表不需要
    跟着 ``_content_cache`` 一起清空。
    """
    try:
        service = _file_token_service()
        return await service.check_token_expired(token)
    except Exception:  # noqa: BLE001 - 老版本 AstrBot 没有文件服务
        return True


async def _write_page(path: Path, content: str) -> None:
    try:
        path.write_text(content, encoding="utf-8")
    except Exception as e:
        raise RuntimeError(f"网页文件写入失败: {path.name}: {e}") from e
