#!/usr/bin/env python3
"""独立冒烟测试：B站扫码登录 + 链接解析（不启动 AstrBot）。

用途：在没有 AstrBot 运行环境的情况下快速验证插件核心功能，并把全过程日志写入文件。
脚本只做三件事：装一个最小的 ``astrbot`` 桩、跑真实的插件实现、把结果打到屏幕与日志。

用法::

    # 只跑解析（用内置示例链接）
    python scripts/dev_smoke_test.py

    # 先扫码登录，再解析自己的链接
    python scripts/dev_smoke_test.py --login https://www.bilibili.com/video/BV1GJ411x7h7

    # 只看解析结果，不下载媒体
    python scripts/dev_smoke_test.py --no-download <url>

产物（默认在 ``scripts/dev_test_out/``）::

    dev_smoke_<时间戳>.log   ← 完整日志（就是要发给开发者的那个文件）
    config/                  ← 本次测试的 cookie（bilibili_cookies.json），与真实插件数据隔离
    data/                    ← 扫码登录的加密 cookie / 状态 / 密钥
    cache/                   ← 下载的媒体与渲染卡片

注意：数据目录是**独立的**，不会动 AstrBot 里的真实登录态；如需复用真实 cookie，
把 ``scripts/dev_test_out/config/bilibili_cookies.json`` 拷过去即可。
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import io
import os
import platform
import re
import subprocess
import sys
import time
import traceback
import types
from pathlib import Path

# ---------------------------------------------------------------- 基础路径

SCRIPT = Path(__file__).resolve()
PLUGIN_ROOT = SCRIPT.parent.parent          # .../astrbot_plugin_rika_share
# scripts/ 自身放进 sys.path：脚本要在没有 AstrBot 时独立运行，日志桩从这里取
sys.path.insert(0, str(SCRIPT.parent))

from dev_logger import StubLogger  # noqa: E402
OUT_ROOT = SCRIPT.parent / "dev_test_out"

#: 日志与终端输出共用一条流：写到哪里都同时进日志文件
_ORIG_STDOUT = sys.stdout


class _Tee:
    """把写往标准输出/错误的内容同时落到日志文件。"""

    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for s in self._streams:
            try:
                s.write(data)
            except Exception:
                pass
        return len(data)

    def flush(self):
        for s in self._streams:
            try:
                s.flush()
            except Exception:
                pass

    def isatty(self):
        return False

    def fileno(self):
        return self._streams[0].fileno()


_LOGFILE = None


#: 塞给 ``astrbot.api.logger`` 的那个桩（脚本自己也可以直接用）
_API_LOGGER = StubLogger("astrbot.api")


def setup_output(verbose: bool) -> Path:
    """建立输出：屏幕与日志文件内容一致（全部走 ``_Tee``）。

    刻意不配置 Python 内置日志模块——按插件审核规则，日志器只能来自
    ``astrbot.api``；第三方库的输出保持各自的默认设置。
    """
    global _LOGFILE
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = OUT_ROOT / f"dev_smoke_{stamp}.log"
    _API_LOGGER.set_level("DEBUG" if verbose else "INFO")
    # line buffering=1：即使脚本卡住/被中断，已写内容也不会丢
    _LOGFILE = open(path, "w", encoding="utf-8", buffering=1)
    tee = _Tee(_ORIG_STDOUT, _LOGFILE)
    sys.stdout = tee
    sys.stderr = tee
    return path


def log(msg: str = "") -> None:
    """脚本自身的输出（与插件日志同流，顺序一致）。"""
    print(msg, flush=True)


def rule(title: str = "") -> None:
    if title:
        log(f"\n{'=' * 8} {title} {'=' * 8}")
    else:
        log("-" * 64)


# ---------------------------------------------------------------- astrbot 桩


class _StubComponent:
    """最小的消息组件替身：只记录构造参数，便于打印内容。"""

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    @classmethod
    def fromFileSystem(cls, path, **kw):  # noqa: N802 - 对齐 AstrBot 命名
        obj = cls.__new__(cls)
        obj.args = (path,)
        obj.kwargs = kw
        return obj

    def __repr__(self):
        text = self.args[0] if self.args else self.kwargs
        if isinstance(text, str) and len(text) > 60:
            text = text[:57] + "..."
        return f"<{type(self).__name__} {text!r}>"


class _StubMessageChain:
    def __init__(self, chain=None):
        self.chain = list(chain or [])

    def message(self, text):
        self.chain.append(text)
        return self

    def file_image(self, path):
        self.chain.append(("image", path))
        return self

    def __repr__(self):
        return f"MessageChain({self.chain!r})"


class _StubEvent:
    pass


class _StubResult:
    pass


def install_astrbot_stub() -> None:
    """注册一个最小的 astrbot 包，让插件实现可以在没有框架的情况下导入。

    只覆盖插件实际用到的那几个符号（见各模块的 import），不模拟框架行为。
    """
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api.logger = _API_LOGGER

    components = types.ModuleType("astrbot.api.message_components")
    for name in ("Plain", "Image", "Video", "Record", "File", "Node", "Nodes", "Json"):
        setattr(components, name, type(name, (_StubComponent,), {}))
    api.message_components = components

    event = types.ModuleType("astrbot.api.event")
    event.AstrMessageEvent = _StubEvent
    event.MessageEventResult = _StubResult
    event.MessageChain = _StubMessageChain

    star = types.ModuleType("astrbot.api.star")
    star.Context = object
    star.Star = object
    star.StarTools = object
    star.register = lambda *a, **kw: (lambda cls: cls)

    sys.modules.update(
        {
            "astrbot": astrbot,
            "astrbot.api": api,
            "astrbot.api.message_components": components,
            "astrbot.api.event": event,
            "astrbot.api.star": star,
        }
    )


class FakeEvent:
    """最小的 AstrMessageEvent 替身，供 BiliAccountService 使用。"""

    def __init__(self, sender_id: str):
        self._sender_id = sender_id
        self.message_str = ""
        self.unified_msg_origin = f"dev:FriendMessage:{sender_id}"

    def get_sender_id(self):
        return self._sender_id

    def get_platform_name(self):
        return "dev_smoke"

    def plain_result(self, text):
        return ("plain", text)

    def image_result(self, path):
        return ("image", str(path))

    def chain_result(self, chain):
        return ("chain", chain)


class FakeContext:
    """记录账号服务通过 context 主动发出的消息。"""

    def __init__(self):
        self.sent = []

    async def send_message(self, umo, chain):
        self.sent.append((umo, chain))
        _API_LOGGER.info("[主动消息 %s] %r", umo, chain)
        return True


# ---------------------------------------------------------------- 环境自检

#: (import 名, pip 名, 用途)
DEPENDENCIES = [
    ("httpx", "httpx", "HTTP 请求 / 下载"),
    ("aiofiles", "aiofiles", "异步写文件"),
    ("bs4", "beautifulsoup4", "微博 / NGA HTML 解析"),
    ("bilibili_api", "bilibili-api-python", "B站接口"),
    ("msgspec", "msgspec", "平台模型解析"),
    ("curl_cffi", "curl-cffi", "B站客户端 / 下载回退"),
    ("aiohttp", "aiohttp", "B站账号服务"),
    ("qrcode", "qrcode[pil]", "扫码登录二维码"),
    ("cryptography", "cryptography", "cookie 加密"),
    ("PIL", "Pillow", "卡片渲染"),
    ("fontTools", "fonttools", "字体回退"),
]


def check_environment() -> bool:
    rule("环境自检")
    log(f"Python      : {sys.version.split()[0]}  ({sys.executable})")
    log(f"系统        : {platform.platform()}")
    log(f"插件目录    : {PLUGIN_ROOT}")
    log(f"工作目录    : {Path.cwd()}")
    log("")

    missing = []
    for module, pip_name, purpose in DEPENDENCIES:
        try:
            mod = __import__(module)
            version = getattr(mod, "__version__", "")
            log(f"  [ok]   {module:<14} {version:<12} {purpose}")
        except Exception as e:  # noqa: BLE001
            missing.append((module, pip_name))
            log(f"  [缺失] {module:<14} {'':<12} {purpose}  ({e})")

    if missing:
        pkgs = " ".join(p for _, p in missing)
        log("")
        log("缺少依赖，二选一：")
        log("  A) 用已经在跑插件的那个解释器来执行本脚本（AstrBot 正常运行说明依赖已装好）")
        log("  B) 建一个隔离环境（本脚本自带 astrbot 桩，不需要装 astrbot 本体）：")
        if sys.platform.startswith("win"):
            log(f"     {sys.executable} -m venv .venv-test")
            log(f"     .venv-test\\Scripts\\pip install {pkgs}")
            log("     .venv-test\\Scripts\\python scripts\\dev_smoke_test.py --login <url>")
        else:
            log(f"     {sys.executable} -m venv .venv-test")
            log(f"     .venv-test/bin/pip install {pkgs}")
            log("     .venv-test/bin/python scripts/dev_smoke_test.py --login <url>")
        return False
    log("")
    return True


# ---------------------------------------------------------------- B站凭证体检


def _mask(name: str, value) -> str:
    if value is None:
        return f"{name}=缺失"
    text = str(value)
    if not text:
        return f"{name}=空"
    return f"{name}=有(len={len(text)})"


async def report_credential(parser, log_title: str = "B站凭证体检") -> None:
    """打印当前生效凭证的字段与校验状态——这是排查 540P / 不续期的关键信息。"""
    rule(log_title)
    try:
        cred = await parser.credential
    except Exception as e:  # noqa: BLE001
        log(f"  取凭证抛异常: {type(e).__name__}: {e}")
        log(traceback.format_exc())
        return

    if cred is None:
        log("  credential = None（未登录；playurl 只能拿到 540P 及以下）")
    else:
        fields = cred.get_cookies()
        log("  credential 已就绪，字段：")
        for key in (
            "SESSDATA",
            "bili_jct",
            "DedeUserID",
            "DedeUserID__ckMd5",
            "buvid3",
            "buvid4",
            "ac_time_value",
        ):
            log(f"    - {_mask(key, fields.get(key))}")
        extra = sorted(set(fields) - {
            "SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5",
            "buvid3", "buvid4", "ac_time_value",
        })
        log(f"    其它字段: {extra or '无'}")
        log(
            "    判定: "
            f"has_sessdata={cred.has_sessdata()} "
            f"has_bili_jct={cred.has_bili_jct()} "
            f"has_ac_time_value={cred.has_ac_time_value()}"
        )
        if not cred.has_ac_time_value():
            log(
                "    ⚠️ 缺少 ac_time_value（扫码登录未保存 refresh_token）→ 凭证过期后无法自动续期"
            )

    for label, coro in (
        ("check_valid()", cred.check_valid() if cred else None),
        ("check_refresh()", cred.check_refresh() if cred else None),
    ):
        if coro is None:
            log(f"  {label}: 跳过（无凭证）")
            continue
        try:
            log(f"  {label}: {await coro}")
        except Exception as e:  # noqa: BLE001
            log(f"  {label}: 抛异常 {type(e).__name__}: {e}")

    log(f"  CACHE_TTL_SECONDS = {parser.CACHE_TTL_SECONDS}")
    log(f"  VALIDATE_INTERVAL = {parser.VALIDATE_INTERVAL}")
    exported = parser.export_cookie()
    log(f"  export_cookie()   = {'有' if exported else '空'}"
        f"{f'（{len(exported)} 字符）' if exported else ''}")


# ---------------------------------------------------------------- 扫码登录


def open_file(path: Path) -> None:
    """尽力用系统默认程序打开图片，方便直接扫码。"""
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        log(f"  已尝试用系统看图器打开：{path}")
    except Exception as e:  # noqa: BLE001
        log(f"  自动打开失败（请手动打开上面的路径）：{e}")


def print_ascii_qr(url: str) -> None:
    """在终端直接打印二维码（只打终端，不进日志，避免刷屏）。"""
    try:
        qr = __import__("qrcode").QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        buf = io.StringIO()
        try:
            qr.print_ascii(out=buf, invert=True)
        except TypeError:
            qr.print_ascii(invert=True)
            return
        _ORIG_STDOUT.write(buf.getvalue())
        _ORIG_STDOUT.flush()
    except Exception as e:  # noqa: BLE001
        log(f"  终端二维码渲染失败（不影响登录，用图片扫即可）：{e}")


async def do_qr_login(service, sender_id: str, wait: int) -> bool:
    """驱动 BiliAccountService.login()，等待轮询结束。"""
    rule("B站扫码登录")

    # 捕获二维码内容，便于在终端也打一份
    captured: dict[str, str] = {}
    original_build = service._build_qrcode_image

    def hooked(url: str):
        captured["url"] = url
        return original_build(url)

    service._build_qrcode_image = hooked  # type: ignore[method-assign]

    event = FakeEvent(sender_id)
    try:
        async for item in service.login(event):
            kind, payload = item if isinstance(item, tuple) else ("?", item)
            if kind == "image":
                log(f"\n[二维码图片] {payload}")
                open_file(Path(payload))
                if captured.get("url"):
                    log("[二维码内容（可直接在终端扫码）]")
                    print_ascii_qr(captured["url"])
            else:
                log(f"[登录流程] {payload}")
    except Exception as e:  # noqa: BLE001
        log(f"扫码登录出错: {type(e).__name__}: {e}")
        log(traceback.format_exc())
        return False
    finally:
        service._build_qrcode_image = original_build  # type: ignore[method-assign]

    task = service._login_tasks.get(sender_id)
    if task is None:
        log("未找到轮询任务，登录流程异常结束")
        return False

    log(f"\n等待扫码（最长 {wait} 秒）...")
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=wait)
    except asyncio.TimeoutError:
        log(f"等待超时（{wait}s），未完成扫码")
        return False
    except Exception as e:  # noqa: BLE001
        log(f"轮询异常: {type(e).__name__}: {e}")
        return False

    rule("登录结果")
    log(f"  解析器导出的 cookie 字段: {sorted(_cookie_names(service._parser_cookie() or ''))}")
    log(f"  服务内存 cookie 字段    : {sorted(_cookie_names(service._cookie))}")
    log(f"  加密 cookie 文件已写入  : {service._cookie_file.exists()}  {service._cookie_file}")
    bili = service.parsers.get("bilibili")
    cookie_file = getattr(bili, "_cookies_file", None)
    if cookie_file is not None:
        log(f"  解析器 cookie 文件      : {cookie_file}  存在={cookie_file.exists()}")
    return True


def _cookie_names(cookie_str: str) -> set[str]:
    names = set()
    for part in (cookie_str or "").split(";"):
        part = part.strip()
        if "=" in part:
            names.add(part.split("=", 1)[0].strip())
    return names


# ---------------------------------------------------------------- 链接解析


def describe_task(task) -> str:
    return f"{type(task).__name__}"


async def report_contents(result, log_prefix: str = "      ") -> None:
    from link_parser.models import ImageContent, VideoContent

    log(f"{log_prefix}contents({len(result.contents)}):")
    if not result.contents:
        log(f"{log_prefix}  - 无")
    for i, cont in enumerate(result.contents):
        kind = type(cont).__name__
        marks = []
        if isinstance(cont, VideoContent):
            marks.append(f"duration={cont.duration}s")
            if cont.is_image_like:
                marks.append("动图/实况")
            if getattr(cont, "is_gif", False):
                marks.append("gif")
            if getattr(cont, "is_live_photo", False):
                marks.append("live_photo")
        elif isinstance(cont, ImageContent):
            if cont.alt:
                marks.append(f"alt={cont.alt!r}")
            if getattr(cont, "is_gif", False):
                marks.append("gif")
        try:
            path = await cont.path_task.safe_get()
        except Exception as e:  # noqa: BLE001
            log(f"{log_prefix}  {i + 1}. {kind:<14} {' '.join(marks)}  下载失败: {e}")
            continue
        if path is None:
            log(f"{log_prefix}  {i + 1}. {kind:<14} {' '.join(marks)}  path=None（未下载/被跳过）")
        else:
            size = path.stat().st_size if path.exists() else -1
            log(
                f"{log_prefix}  {i + 1}. {kind:<14} {' '.join(marks)}  "
                f"{path.name}  {size / 1024:.1f}KB"
            )

    log(f"{log_prefix}graphics({len(result.graphics)}):")
    for i, g in enumerate(result.graphics[:5]):
        if isinstance(g, str):
            text = g if len(g) < 60 else g[:57] + "..."
            log(f"{log_prefix}  {i + 1}. [文本] {text!r}")
        else:
            try:
                path = await g.path_task.safe_get()
            except Exception:  # noqa: BLE001
                path = None
            log(f"{log_prefix}  {i + 1}. [图片] {path}")


async def probe_bili_quality(parser, result, log_prefix: str = "      ") -> None:
    """直接问 B站「这个视频给我哪些清晰度」，用来判断登录态是否真的生效。"""
    matched = re.search(r"(BV[0-9A-Za-z]{10})", result.url or "")
    if not matched:
        return
    bvid = matched.group(1)
    try:
        from bilibili_api.video import Video

        cred = await parser.credential
        video = Video(bvid=bvid, credential=cred)
        data = await video.get_download_url(page_index=0)
    except Exception as e:  # noqa: BLE001
        log(f"{log_prefix}[清晰度探测] 失败: {type(e).__name__}: {e}")
        return

    log(f"{log_prefix}[清晰度探测] {bvid}  凭证={'已登录' if cred is not None else 'None(未登录)'}")
    log(f"{log_prefix}  accept_quality={data.get('accept_quality')}")
    log(f"{log_prefix}  accept_description={data.get('accept_description')}")
    for form in data.get("support_formats") or []:
        log(
            f"{log_prefix}  qn={form.get('quality')} "
            f"{form.get('new_description') or form.get('display_desc')}"
        )
    log(f"{log_prefix}  dash={'有' if data.get('dash') else '无（说明只能拿 durl 低码率）'}")


async def parse_one(url: str, download: bool) -> dict:
    from link_parser.adapters import iter_adapters
    from link_parser.adapters.registry import AdapterBuildContext
    from link_parser.config import get_config
    from link_parser.exceptions import IgnoreException, ParseException, SilentException
    from link_parser.output import build_platform_output
    from link_parser.services.card_render import ShareCardRenderer
    from link_parser.services.downloader import StreamDownloader

    outcome = {"url": url, "ok": False, "platform": "", "title": "", "error": ""}

    rule(f"解析 {url}")
    spec = None
    for candidate in iter_adapters():
        if candidate.url_pattern.search(url):
            spec = candidate
            break
    if spec is None:
        log("  没有适配器匹配该链接（AstrBot 里会交给 Cloudflare 兜底或直接忽略）")
        outcome["error"] = "无适配器匹配"
        return outcome
    outcome["platform"] = spec.name

    pconfig = get_config()
    downloader = StreamDownloader(pconfig.cache_dir)
    ctx = AdapterBuildContext(
        downloader=downloader, config=pconfig, config_dir=pconfig.config_dir
    )

    started = time.perf_counter()
    try:
        parser = spec.create(ctx)
        keyword, searched = parser.search_url(url)
        log(f"  适配器={spec.name} 关键词={keyword} 匹配={searched.group(0)[:60]!r}")
        log(f"  内容标识={await parser.cache_identity(url)}")

        if spec.name == "bilibili":
            cred = await parser.credential
            log(f"  凭证: {'已登录' if cred is not None else 'None（未登录）'}")

        result = await parser.parse(keyword, searched)
    except SilentException as e:
        log(f"  静默跳过: {e}")
        outcome["error"] = f"SilentException: {e}"
        return outcome
    except IgnoreException as e:
        log(f"  主动忽略: {e}")
        outcome["error"] = f"IgnoreException: {e}"
        return outcome
    except ParseException as e:
        log(f"  解析失败: {e}")
        log(traceback.format_exc())
        outcome["error"] = f"ParseException: {e}"
        return outcome
    except Exception as e:  # noqa: BLE001
        log(f"  未预期异常: {type(e).__name__}: {e}")
        log(traceback.format_exc())
        outcome["error"] = f"{type(e).__name__}: {e}"
        return outcome

    elapsed = time.perf_counter() - started
    outcome["ok"] = True
    outcome["title"] = result.title or ""

    log(f"  耗时={elapsed:.2f}s")
    log(f"  platform={result.platform.name} ({result.platform.display_name})")
    log(f"  title={result.title!r}")
    log(f"  url={result.url}")
    if result.author:
        log(f"  author={result.author.name!r}  avatar={'有' if result.author.avatar else '无'}")
    if result.timestamp:
        when = dt.datetime.fromtimestamp(result.timestamp).strftime("%Y-%m-%d %H:%M:%S")
        log(f"  timestamp={when}")
    if result.text:
        text = result.text if len(result.text) < 160 else result.text[:157] + "..."
        log(f"  text={text!r}")
    if result.repost:
        log(f"  repost=有（转发内容，title={result.repost.title!r}）")

    log("  extra:")
    for key in sorted(result.extra):
        value = result.extra[key]
        if isinstance(value, str) and len(value) > 200:
            value = value[:197] + "..."
        log(f"    {key} = {value!r}")

    # 媒体下载（安全起见先看有没有超时长）
    if download:
        await report_contents(result)
    else:
        log(f"      contents({len(result.contents)}): 已跳过下载（--no-download）")

    # 消息链构建
    try:
        header, nodes = await build_platform_output(result, result.platform.name)
        log(f"  消息链: header={header!r} 节点数={len(nodes)}")
        for i, node in enumerate(nodes):
            head = ", ".join(repr(c) for c in node[:3])
            log(f"    节点{i + 1}({len(node)}): {head}")
    except Exception as e:  # noqa: BLE001
        log(f"  消息链构建失败: {type(e).__name__}: {e}")
        log(traceback.format_exc())

    # 卡片渲染
    try:
        renderer = ShareCardRenderer(
            pconfig.cache_dir,
            enabled=pconfig.RENDER_ENABLED,
            width=pconfig.RENDER_WIDTH,
            theme=pconfig.RENDER_THEME,
            font_path=pconfig.RENDER_FONT_PATH or None,
            layout=pconfig.RENDER_LAYOUT,
            cover_full_size=pconfig.RENDER_COVER_FULL_SIZE,
        )
        card = await renderer.render(result, cache_key=f"devsmoke:{url[:48]}")
        if card:
            log(f"  卡片: {card}  {card.stat().st_size / 1024:.1f}KB")
        else:
            log("  卡片: 未生成（渲染关闭或失败，AstrBot 里会回退文本输出）")
    except Exception as e:  # noqa: BLE001
        log(f"  卡片渲染失败: {type(e).__name__}: {e}")
        log(traceback.format_exc())

    if spec.name == "bilibili":
        await probe_bili_quality(parser, result)

    return outcome


# ---------------------------------------------------------------- 主流程


async def run(args) -> int:
    from link_parser.config import init_config
    from link_parser.exceptions import IgnoreException, SilentException

    # 插件会主动 create_task 下载媒体；这些任务失败时没人 await，
    # asyncio 会打一大段 "Task exception was never retrieved"。
    # IgnoreException / SilentException 是设计上的控制流（时长超限、跳过下载），
    # 降级成 DEBUG，避免把真正的错误淹没。
    def _handle_loop_exception(loop, context):
        exc = context.get("exception")
        if isinstance(exc, (IgnoreException, SilentException)):
            log(f"后台任务按设计跳过: {exc}")
            return
        loop.default_exception_handler(context)

    asyncio.get_running_loop().set_exception_handler(_handle_loop_exception)

    data_root = OUT_ROOT
    config_dir = data_root / "config"
    cache_dir = data_root / "cache"
    service_data = data_root / "data"
    for d in (config_dir, cache_dir, service_data):
        d.mkdir(parents=True, exist_ok=True)

    # 解析器会**主动**为视频创建下载任务（create_task），只靠不 await 拦不住。
    # 把时长上限置 0，下载任务会在拿到流地址后立刻抛 IgnoreException，
    # 从而不产生任何文件传输——顺带还能演示 limit_warnings 这条分支。
    overrides = {}
    if args.no_download:
        overrides["VIDEO_DURATION_MAXIMUM"] = 0
    init_config(overrides, cache_dir, config_dir)

    from link_parser.adapters import adapter_names
    from link_parser.services.bilibili_account import BiliAccountService

    rule("初始化")
    log(f"插件根目录: {PLUGIN_ROOT}")
    log(f"数据目录  : {data_root}")
    log(f"  配置    : {config_dir}")
    log(f"  缓存    : {cache_dir}")
    log(f"  登录态  : {service_data}")
    log(f"已注册平台: {adapter_names()}")
    if args.no_download:
        log("--no-download: VIDEO_DURATION_MAXIMUM 已置 0（视频不会被下载，卡片会带时长超限提示）")
    if getattr(args, "used_default_urls", False):
        log("提示: 未提供链接，使用内置示例；建议把自己的链接作为参数传入。")

    # 解析器实例（B站会用到；账号服务需要它才能回读/写入 cookie）
    from link_parser.adapters.registry import AdapterBuildContext, get_adapter
    from link_parser.config import get_config
    from link_parser.services.downloader import StreamDownloader

    pconfig = get_config()
    ctx = AdapterBuildContext(
        downloader=StreamDownloader(cache_dir),
        config=pconfig,
        config_dir=config_dir,
    )
    parsers = {"bilibili": get_adapter("bilibili").create(ctx)}

    context = FakeContext()
    service = BiliAccountService(context, service_data, parsers)
    await service.initialize()

    if args.login:
        await do_qr_login(service, args.sender, args.login_timeout)
        await report_credential(parsers["bilibili"], "登录后凭证体检")
    else:
        await report_credential(parsers["bilibili"], "B站凭证体检（未登录则显示 None）")

    results = []
    for url in args.urls:
        results.append(await parse_one(url, download=not args.no_download))

    rule("汇总")
    for item in results:
        status = "OK  " if item["ok"] else "FAIL"
        detail = item["title"] or item["error"]
        log(f"  [{status}] {item['platform'] or '-':<12} {item['url'][:70]}  {detail}")

    ok = sum(1 for r in results if r["ok"])
    log(f"\n  成功 {ok}/{len(results)}")

    await service.aclose()
    return 0 if ok == len(results) else 1


def parse_args():
    parser = argparse.ArgumentParser(
        description="插件独立冒烟测试（B站扫码登录 + 链接解析）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("urls", nargs="*", help="要解析的链接（留空则用内置示例）")
    parser.add_argument("--login", action="store_true", help="先进行 B站 扫码登录")
    parser.add_argument("--sender", default="dev_smoke_user", help="登录流程模拟的用户 ID")
    parser.add_argument(
        "--login-timeout", type=int, default=180, help="等待扫码的秒数（默认 180）"
    )
    parser.add_argument("--no-download", action="store_true", help="不下载媒体文件")
    parser.add_argument("--verbose", action="store_true", help="打开 DEBUG 日志")
    args = parser.parse_args()
    args.used_default_urls = not args.urls
    if args.used_default_urls:
        args.urls = ["https://www.bilibili.com/video/BV1GJ411x7h7"]
    return args


def main() -> int:
    args = parse_args()
    log_path = setup_output(args.verbose)

    log("=" * 64)
    log("  插件独立冒烟测试  link_parser")
    log(f"  日志文件: {log_path}")
    log("=" * 64)

    install_astrbot_stub()
    # link_parser 是插件根目录下的一级包（main.py 用相对导入引用它）
    sys.path.insert(0, str(PLUGIN_ROOT))

    if not check_environment():
        rule("结束")
        log("依赖不全，已停止。")
        log(f"日志已保存: {log_path}")
        return 2

    try:
        code = asyncio.run(run(args))
    except KeyboardInterrupt:
        rule("结束")
        log("被用户中断（Ctrl+C）")
        code = 130
    except Exception as e:  # noqa: BLE001
        rule("结束")
        log(f"脚本异常退出: {type(e).__name__}: {e}")
        log(traceback.format_exc())
        code = 1

    rule("结束")
    log(f"退出码: {code}")
    log(f"日志文件: {log_path}")
    log("请把上面这个 .log 文件发给开发者。")
    return code


if __name__ == "__main__":
    sys.exit(main())
