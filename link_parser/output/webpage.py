"""合并转发内容 → 一个可点开的网页，群里只发一条链接通知。

仅用于不支持 Comp.Nodes（合并转发）的平台：把「标题头 + 节点内容」渲染成一个
自包含的聊天记录页（浅 / 深色自适应、图片网格、灯箱），页面与图集图片都经
AstrBot 文件服务（``/api/file/{token}``，免鉴权路由，token 即访问凭据）下发，
链接用 AstrBot 的「对外可达的回调接口地址」（``callback_api_base``）拼出。

- 页面无外部资源；脚本用 CSP sha256 放行；``noindex,nofollow``。
- 图片不复制、不 base64：注册缓存目录里现成文件的 token 直接热链。链接时效与
  缓存共用（``CACHE_TTL_HOURS``），图片文件必然活得和链接一样久；token 是内存态，
  AstrBot 重启后旧链接失效。
- 同一内容复用同一网页：调用方以「内容标识 → (原始链接, 页面 token)」做复用表，
  token 失效自动重建（:func:`webpage_token_expired` 自校验）。
- QQ 客户端直接打开外站链接常被拦（「如需浏览，请使用浏览器访问」），QQ 系
  平台默认经腾讯文档的外链跳转页（docs.qq.com/scenario/link.html）打开网页。

布局与机制改写自 qbob-main（MIT License）的 ``core/forwardpage.py``。
"""

from __future__ import annotations

import base64
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
    "create_webpage",
    "format_share_message",
    "tdocs_jump",
    "webpage_token_expired",
]

#: 插件方名称（页面里的说话人）与首字头像
BOT_NAME = "莉卡解析"

# 头像色相: 按名字取, 同一人整页同色（qbob 同款）
_HUES = (212, 160, 24, 340, 262, 188, 44, 300)

# 裸链接自动成链; 在转义后的文本上匹配, 不会匹配到标签
_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_URL_TAIL = "。，、；：！？…）】》」』.,;:!?)"

# 腾讯文档的外链跳转页（qbob cards.DOCS_JUMP 的移植）: 经它打开的网页可在 QQ 内直接浏览
DOCS_JUMP = "https://docs.qq.com/scenario/link.html?url="


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
    def repl(match: re.Match) -> str:
        url = match.group(0)
        tail = ""
        while url and url[-1] in _URL_TAIL:
            tail = url[-1] + tail
            url = url[:-1]
        return (f'<a href="{url}" rel="noreferrer noopener" target="_blank">{url}</a>'
                + tail)

    return _URL_RE.sub(repl, escaped)


def _hue_index(name: str) -> int:
    return hashlib.sha1(name.encode("utf-8")).digest()[0] % len(_HUES)


def _hue_style() -> str:
    light = "".join(f".a{i}{{--ab:hsl({h} 60% 91%);--af:hsl({h} 45% 38%)}}"
                    for i, h in enumerate(_HUES))
    dark = "".join(f".a{i}{{--ab:hsl({h} 28% 24%);--af:hsl({h} 55% 74%)}}"
                   for i, h in enumerate(_HUES))
    return f"{light}@media(prefers-color-scheme:dark){{{dark}}}"


_STYLE = """
:root{color-scheme:light dark;--bg:#f2f2f7;--ink:#1c1c1e;--mute:#8e8e93;
--line:rgba(60,60,67,.12);--tile:#e9e9ee;--hatch:#dcdce2;--link:#0a7aff;
--bar:rgba(242,242,247,.84);
--pane:hsl(var(--h1,212) 52% 98%);--gsh:0 1px 2px rgba(15,23,42,.05),0 8px 24px rgba(15,23,42,.06)}
@media(prefers-color-scheme:dark){:root{--bg:#000;--ink:#f2f2f7;--mute:#8e8e93;
--line:rgba(84,84,88,.48);--tile:#2c2c2e;--hatch:#3a3a3c;--link:#409cff;
--bar:rgba(0,0,0,.72);
--pane:hsl(var(--h1,212) 15% 12%);--gsh:0 8px 24px rgba(0,0,0,.4)}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:15.5px/1.6 -apple-system,
"PingFang SC","HarmonyOS Sans SC","MiSans","Noto Sans CJK SC","Microsoft YaHei",
system-ui,sans-serif;-webkit-font-smoothing:antialiased}
.top{position:sticky;top:0;z-index:2;background:var(--bar);-webkit-backdrop-filter:
saturate(180%) blur(14px);backdrop-filter:saturate(180%) blur(14px);
border-bottom:1px solid var(--line)}
.bar{max-width:680px;margin:0 auto;padding:12px 16px;display:flex;align-items:baseline;
gap:10px}
h1{font-size:17px;font-weight:600;margin:0;letter-spacing:-.01em}
.cnt{color:var(--mute);font-size:13px;font-variant-numeric:tabular-nums;margin-left:auto}
.sheet{max-width:680px;margin:12px auto 0;background:var(--pane);border-radius:18px;
padding:4px 0;overflow:hidden;box-shadow:var(--gsh)}
@media(max-width:700px){.sheet{margin:8px 8px 0}}
.day{display:table;margin:12px auto 2px;padding:2px 12px;border-radius:999px;background:var(--tile);
color:var(--mute);font-size:12px;font-variant-numeric:tabular-nums}
.g{display:flex;gap:12px;padding:12px 16px;border-top:1px solid var(--line)}
.day+.g,.sheet>.g:first-child{border-top:0;padding-top:8px}
.av{flex:none;width:36px;height:36px;border-radius:50%;display:flex;align-items:center;
justify-content:center;font-size:15px;font-weight:600;background:var(--ab,var(--tile));
color:var(--af,var(--mute));user-select:none;overflow:hidden}
.bd{flex:1;min-width:0}
.name{font-size:13px;font-weight:600;color:var(--af,var(--ink));line-height:20px}
.m{position:relative;padding:2px 0}
.m+.m{margin-top:4px}
.txt{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}
.txt a{color:var(--link);text-decoration:none}
.pics{display:grid;gap:3px;margin:6px 0 2px}
.pics.c2{grid-template-columns:repeat(2,minmax(0,1fr))}
.pics.c3{grid-template-columns:repeat(3,minmax(0,1fr))}
.pics a{display:block;min-width:0;border-radius:10px;overflow:hidden;background:var(--tile)
center/cover no-repeat;box-shadow:inset 0 0 0 1px var(--line)}
.pics a:focus-visible{outline:2px solid var(--link);outline-offset:2px}
.pics img{display:block;width:100%;height:100%;object-fit:cover;aspect-ratio:1}
.pics.c1{grid-template-columns:minmax(0,1fr)}
.pics.c1 a{width:fit-content;max-width:100%;min-width:96px;min-height:96px}
.pics.c1 img{width:auto;max-width:100%;height:auto;aspect-ratio:auto;object-fit:fill;
background:var(--tile)}
.gone{display:flex;align-items:center;justify-content:center;margin:6px 0 2px;height:84px;
border-radius:10px;color:var(--mute);font-size:13px;background:repeating-linear-gradient(
135deg,var(--tile) 0 8px,var(--hatch) 8px 9px)}
.pics .gone{margin:0;height:auto;aspect-ratio:1}
.pics.c1 .gone{aspect-ratio:auto;height:84px}
.ft{padding:20px 16px 28px;color:var(--mute);font-size:12px;text-align:center;
font-variant-numeric:tabular-nums}
.empty{padding:44px 16px;text-align:center;color:var(--mute)}
.lb{position:fixed;inset:0;z-index:9;background:#000;display:flex;align-items:center;
justify-content:center;touch-action:none;overflow:hidden}
.lb[hidden]{display:none}
.lb img{max-width:100vw;max-height:100vh;object-fit:contain;user-select:none;
-webkit-user-drag:none;transition:transform .16s ease-out;will-change:transform}
.lb .cnt{position:fixed;top:14px;left:0;right:0;
text-align:center;color:#9a9a9e;font-size:13px;margin:0;pointer-events:none}
.lb button{position:fixed;z-index:1;border:0;background:rgba(0,0,0,.45);color:#f2f2f7;
font:20px/1 system-ui;width:40px;height:40px;border-radius:20px;cursor:pointer}
.lb button:focus-visible{outline:2px solid #fff}
.lb .x{top:10px;right:12px}
.lb .p,.lb .n{top:50%;margin-top:-20px}
.lb .p{left:10px}.lb .n{right:10px}
.lb.one .p,.lb.one .n{display:none}
.lbopen{overflow:hidden}
@media(prefers-reduced-motion:reduce){.lb img{transition:none}}
""".strip()

# 灯箱: 滑动/方向键切图, 双击或双指放大, 点背景或 × 关闭(点图不关, 免得误关双击).
# touchmove 一律 preventDefault: iOS 上 overflow:hidden 拦不住底层页面滚动.
# CSP 哈希在运行时按内容计算, 改脚本无需手动更新.（qbob 同款脚本）
_SCRIPT = """
(function(){var L=[].slice.call(document.querySelectorAll('a.img'));if(!L.length)return;
var lb=document.getElementById('lb'),im=lb.querySelector('img'),c=lb.querySelector('.cnt'),
i=0,s=1,bs=1,tx=0,ty=0,tap=0,t0=null,d0=0,s0=1,mv=false,ld=null,drag=null,bk=0;
if(L.length<2)lb.className+=' one';
function ap(){im.style.transform='translate('+tx+'px,'+ty+'px) scale('+s+')'}
function reset(){s=1;bs=1;tx=ty=0;im.style.width=im.style.height=im.style.maxWidth=im.style.maxHeight='';ap()}
function clamp(){var mx=Math.max(0,(im.offsetWidth*s-lb.clientWidth)/2),
my=Math.max(0,(im.offsetHeight*s-lb.clientHeight)/2);
tx=Math.min(mx,Math.max(-mx,tx));ty=Math.min(my,Math.max(-my,ty))}
function zoom(ns,x,y){ns=Math.min(8/bs,Math.max(1/bs,ns));var cx=lb.clientWidth/2,cy=lb.clientHeight/2,k=ns/s;
tx=(x-cx)-k*((x-cx)-tx);ty=(y-cy)-k*((y-cy)-ty);s=ns;clamp();ap()}
function bake(){clearTimeout(bk);if(s===1)return;if(Math.abs(bs*s-1)<.01)return reset();
var w=im.offsetWidth*s;bs*=s;s=1;im.style.transition='none';im.style.maxWidth=im.style.maxHeight='none';
im.style.width=w+'px';im.style.height='auto';ap();requestAnimationFrame(function(){im.style.transition=''})}
function later(){clearTimeout(bk);bk=setTimeout(bake,200)}
function toggle(x,y){if(s>1||bs>1)reset();else{zoom(Math.max(2.5,lb.clientWidth/im.offsetWidth),x,y);later()}}
function go(n){i=(n+L.length)%L.length;reset();var a=L[i];im.src=a.href;
c.textContent=(i+1)+' / '+L.length;lb.hidden=false;document.body.classList.add('lbopen')}
function off(){lb.hidden=true;im.removeAttribute('src');document.body.classList.remove('lbopen');L[i].focus()}
L.forEach(function(a,n){a.addEventListener('click',function(e){e.preventDefault();go(n)})});
lb.addEventListener('click',function(e){var b=e.target.closest('button');
if(b){b.className==='p'?go(i-1):b.className==='n'?go(i+1):off();return}
if(e.target!==im&&!mv)off()});
im.addEventListener('dblclick',function(e){e.preventDefault();toggle(e.clientX,e.clientY)});
lb.addEventListener('wheel',function(e){e.preventDefault();zoom(s*(e.deltaY<0?1.2:1/1.2),e.clientX,e.clientY);later()},{passive:false});
im.addEventListener('mousedown',function(e){if(s*bs>1){drag={x:e.clientX,y:e.clientY,tx:tx,ty:ty};e.preventDefault()}});
window.addEventListener('mousemove',function(e){if(!drag)return;im.style.transition='none';
tx=drag.tx+e.clientX-drag.x;ty=drag.ty+e.clientY-drag.y;clamp();ap();mv=true});
window.addEventListener('mouseup',function(){drag=null;im.style.transition='';setTimeout(function(){mv=false},0)});
document.addEventListener('keydown',function(e){if(lb.hidden)return;
if(e.key==='Escape')off();else if(e.key==='ArrowLeft')go(i-1);else if(e.key==='ArrowRight')go(i+1)});
function dist(t){var dx=t[0].clientX-t[1].clientX,dy=t[0].clientY-t[1].clientY;return Math.sqrt(dx*dx+dy*dy)}
lb.addEventListener('touchstart',function(e){var t=e.touches;mv=false;im.style.transition='none';
if(t.length===2){d0=dist(t);s0=s;t0=null}else t0={x:t[0].clientX,y:t[0].clientY,tx:tx,ty:ty}},{passive:true});
lb.addEventListener('touchmove',function(e){var t=e.touches;e.preventDefault();
if(t.length===2){zoom(s0*dist(t)/d0,(t[0].clientX+t[1].clientX)/2,(t[0].clientY+t[1].clientY)/2);mv=true}
else if(s*bs>1&&t0){tx=t0.tx+t[0].clientX-t0.x;ty=t0.ty+t[0].clientY-t0.y;clamp();ap();mv=true}},{passive:false});
lb.addEventListener('touchend',function(e){im.style.transition='';if(e.touches.length)return;
if(s!==1)bake();var ch=e.changedTouches[0];
if(t0&&s*bs===1&&!mv){var dx=ch.clientX-t0.x;if(Math.abs(dx)>48){mv=true;go(dx<0?i+1:i-1);t0=null;return}}
if(!mv&&e.target===im){var now=Date.now();if(now-tap<320){e.preventDefault();toggle(ch.clientX,ch.clientY);tap=0}else tap=now}
t0=null});
})();
""".strip()


def _csp(script: str) -> str:
    """只放行指定哈希的脚本。

    与 qbob 的差别：页面经 AstrBot 文件服务下发，没有响应头可用，CSP 由
    ``<meta>`` 标签承载（frame-ancestors 在 meta 里会被忽略，干脆不写）；
    ``callback_api_base`` 允许填 http://（内网 / 未配 TLS），所以 img-src 也放开 http:。
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


def _render_pics(urls: list[str]) -> str:
    """相邻图片排成一格: 1 张满栏不限高, 2/4 张两列, 其余三列. 空串 = 已失效占位。"""
    cols = 1 if len(urls) == 1 else 2 if len(urls) in (2, 4) else 3
    cells: list[str] = []
    for url in urls:
        if url:
            # decoding=async: 大图解码不阻塞滚动
            cells.append(f'<a class="img" href="{_esc(url)}">'
                         f'<img src="{_esc(url)}" alt="" loading="lazy" '
                         f'decoding="async"></a>')
        else:
            cells.append('<div class="gone">图片 · 已失效</div>')
    return f'<div class="pics c{cols}">{"".join(cells)}</div>'


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
    """单个节点 -> 气泡内容; 相邻图片并成一格。"""
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
        out.append(f'<p class="txt">{_autolink(_esc(value))}</p>')
    flush_pics()
    return "".join(out)


def _shell(body: str, title: str, script: str, hue: int) -> str:
    csp = _csp(script)
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        # 不开 viewport-fit=cover, 页面无需铺到刘海下
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow">'
        # 经 AstrBot 文件服务下发, CSP 只能写在 meta 里
        f'<meta http-equiv="Content-Security-Policy" content="{_esc(csp)}">'
        f"<title>{_esc(title)}</title>"
        f"<style>{_STYLE}{_hue_style()}:root{{--h1:{hue};}}</style></head>"
        f"<body>{body}<script>{script}</script></body></html>"
    )


def render_share_page(
    header: str,
    summary: str,
    items_html: list[str],
    gone_pics: int,
    ttl_hours: int,
) -> str:
    """整页 HTML（不含图片地址解析，纯同步）。"""
    hue = _hue_index(BOT_NAME)
    rows = "".join(f'<div class="m">{part}</div>' for part in items_html)
    group = (
        f'<section class="g a{hue}"><div class="av">{_esc(BOT_NAME[:1])}</div>'
        f'<div class="bd"><div class="name">{_esc(BOT_NAME)}</div>{rows}</div></section>'
    )
    parts: list[str] = []
    if gone_pics:
        # 页顶统一说明一次失效, 单个图格内另有占位
        parts.append('<div class="day">部分图片已失效</div>')
    parts.append(group)
    made = time.strftime("%Y-%m-%d %H:%M")
    if int(ttl_hours) > 0:
        ttl_note = f"链接约 {int(ttl_hours)} 小时内有效"
    else:
        ttl_note = "链接在 AstrBot 重启前有效"
    body = (
        '<header class="top"><div class="bar">'
        f"<h1>{_esc(header or BOT_NAME)}</h1>"
        f'<span class="cnt">{_esc(summary)}</span></div></header>'
        f'<main class="sheet">{"".join(parts)}</main>'
        f'<footer class="ft">{made} 生成 · {ttl_note}</footer>'
        '<div class="lb" id="lb" hidden><p class="cnt"></p><img alt="" draggable="false">'
        '<button class="p" aria-label="上一张">‹</button>'
        '<button class="n" aria-label="下一张">›</button>'
        '<button class="x" aria-label="关闭">×</button></div>'
    )
    return _shell(body, title=header or BOT_NAME, script=_SCRIPT, hue=hue)


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


def summarize_items(text_items: list[list]) -> str:
    """一行摘要, 如 "5 条内容 · 8 张图片"（复用链接时也要拼通知文案, 故公开）。"""
    n_pics = sum(
        1
        for item in text_items
        for kind, _ in _collect_blocks(item)
        if kind == "pic"
    )
    return _summarize(len(text_items), n_pics)


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
    event: AstrMessageEvent, header: str, text_items: list[list], url: str
) -> str:
    """聊天里的链接通知文案。

    ``url`` 必须传**原始链接**（复用与新建都一样）：QQ 系平台在发送时现判并经
    腾讯文档跳转页包装，其他平台原样发出——同一链接在不同平台能以各自合适的形态出现。
    """
    link = tdocs_jump(url) if _wants_tdocs(event) else url
    lines = []
    if header:
        lines.append(header)
    lines.append(f"📄 {summarize_items(text_items)}，点击查看：{link}")
    return "\n".join(lines)


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
