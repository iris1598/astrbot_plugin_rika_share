"""链接解析调试探针。

把解析主流程逐步跑一遍并记录成一份可下载的文本报告：

    识别平台 → 缓存标识 → 解析 → 媒体下载 → 卡片渲染 → 输出构建 → Cloudflare 兜底判断

和 :meth:`ParserPlugin._process_url` 的**有意差异**：

- **不读也不写** ``_content_cache`` / ``_identity_cache``，每次都是全新解析
  （否则「命中缓存」会把真正要看的解析过程掩盖掉）；
- **不向任何会话发送消息**，也不改动 ``parsers`` / 渲染器的配置；
- 只记录**探针自己关心的事件**（每步开始/结束/异常、媒体逐项结果、跳过决策），
  不拦截、也不改动框架 logger 的任何状态（不改级别、不挂处理器）；
- 报告里所有 Cookie / Token 都会被替换成 ``***``——它是拿来贴给别人的。

媒体下载与卡片渲染都默认执行，因为它们正是「解析看着正常、消息却发不出去」的常见断点。
"""

from __future__ import annotations

import platform as _platform
import re
import sys
import time
import traceback
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from astrbot.api import logger

from ..config import get_config
from ..exceptions import IgnoreException, ParseException, SilentException
from ..models import ImageContent, VideoContent
from ..output import build_platform_output

#: 报告里要打码的配置项（值是 Cookie / Token，不能出现在可下载的日志里）
_SECRET_KEYS = ("BILI_CK", "XHS_CK", "CLOUDFLARE_API_TOKEN")

#: 兜底打码：即便某个库把 Cookie 直接写进了日志，也能盖掉
_SECRET_PATTERNS = (
    re.compile(r"(SESSDATA=)[^;,\s\"']+", re.IGNORECASE),
    re.compile(r"(bili_jct=)[^;,\s\"']+", re.IGNORECASE),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{8,}"),
)

_MASK = "***"


# ==================== 数据结构 ==================== #


@dataclass(slots=True)
class DebugStep:
    """一个流程步骤的执行结果。"""

    name: str
    status: str  # ok / fail / skip
    detail: str = ""
    elapsed_ms: int = 0
    traceback_text: str = ""


@dataclass(slots=True)
class DebugReport:
    """一次调试的完整结果。"""

    token: str
    url: str
    platform: str
    ok: bool
    steps: list[DebugStep]
    summary: dict[str, Any]
    log_path: Path
    text: str
    elapsed_ms: int
    started_at: datetime = field(default_factory=datetime.now)

    def payload(self) -> dict[str, Any]:
        """给网页设置页用的精简结构（不含完整日志正文，正文走下载接口）。"""
        return {
            "token": self.token,
            "url": self.url,
            "platform": self.platform,
            "ok": self.ok,
            "elapsed_ms": self.elapsed_ms,
            "started_at": self.started_at.strftime("%Y-%m-%d %H:%M:%S"),
            "log_name": self.log_path.name,
            "steps": [
                {
                    "name": step.name,
                    "status": step.status,
                    "detail": step.detail,
                    "elapsed_ms": step.elapsed_ms,
                }
                for step in self.steps
            ],
            "summary": self.summary,
            "text": self.text,
        }


# ==================== 流程日志（探针自己记录） ==================== #


@dataclass(slots=True)
class DebugEvent:
    """一条调试事件。"""

    time: str  # HH:MM:SS.mmm
    level: str  # info / warn / error
    message: str
    traceback_text: str = ""


class EventLog:
    """探针自己的事件日志。

    **为什么不拦截框架日志**：审核规则要求日志器必须、且只能从 ``astrbot.api``
    导入（``from astrbot.api import logger``），不得使用 Python 内置的日志模块。
    所以这里既不往 logger 上挂处理器、也不改它的级别，而是把调试过程中真正要看的东西
    自己记下来——每步的开始/结束/异常、媒体逐项结果、跳过的决策。框架侧照旧把插件的
    完整输出打到 AstrBot 日志面板，两边互不干扰，探针也不再改动任何全局状态。
    """

    def __init__(self) -> None:
        self.events: list[DebugEvent] = []

    def _add(self, level: str, message: str, traceback_text: str = "") -> None:
        now = datetime.now()
        stamp = f"{now:%H:%M:%S}.{now.microsecond // 1000:03d}"
        self.events.append(DebugEvent(stamp, level, message, traceback_text))

    def info(self, message: str) -> None:
        self._add("info", message)

    def warn(self, message: str) -> None:
        self._add("warn", message)

    def error(self, message: str, exc: BaseException | None = None) -> None:
        """记一条错误；给了异常就带上完整堆栈（报告里最有用的部分）。"""
        stack = ""
        if exc is not None:
            stack = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            ).rstrip()
        self._add("error", message, stack)

    @property
    def text(self) -> str:
        """渲染成报告里的日志段落（与旧的 capture 输出格式保持一致）。"""
        lines: list[str] = []
        for event in self.events:
            lines.append(f"{event.time} | {event.level.upper():<7} | {event.message}")
            if event.traceback_text:
                for text in event.traceback_text.splitlines():
                    lines.append(f"        | {text}")
        return "\n".join(lines)


# ==================== 小工具 ==================== #


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _describe(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}".strip()
    return text[:400] if text else type(exc).__name__


def _mask(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: m.group(1) + _MASK, text)
    pconfig = _safe_config()
    if pconfig is not None:
        for key in _SECRET_KEYS:
            value = getattr(pconfig, key, None)
            if isinstance(value, str) and len(value) > 8:
                text = text.replace(value, _MASK)
    return text


def _safe_config():
    try:
        return get_config()
    except Exception:  # noqa: BLE001 - 未初始化时只影响报告里的环境信息
        return None


def _file_info(path: Path | None) -> str:
    if path is None:
        return "—"
    try:
        size = path.stat().st_size
    except OSError:
        return f"{path}（读不到大小）"
    return f"{path} ({_human_size(size)})"


def _display_width(text: str) -> int:
    """按终端显示宽度算长度：中日韩全角字符占两列，否则按字符数对齐会歪。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _display_width(text))


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


#: 「按设计跳过」的异常：时长超限、媒体为空等，不是故障
_SKIP_EXCEPTIONS = (IgnoreException, SilentException)

#: ``IgnoreException`` 不传消息时的模板文案（「可忽略异常」），对调试没信息量
_IGNORE_DEFAULT_MESSAGE = str(IgnoreException())


def _skip_reason(exc: BaseException) -> str:
    """把「按设计跳过」的异常说成人话。

    ``IgnoreException`` 在适配器里常常是光秃秃地 ``raise IgnoreException``，
    默认文案「可忽略异常」指不到任何东西，所以退回一句能指方向的话；
    带了消息（多数情况）就直接用。
    """
    text = str(exc).strip()
    if text and text != _IGNORE_DEFAULT_MESSAGE:
        return text
    return "按设计跳过下载（时长超限、媒体为空等）"


def _media_kind(content: Any) -> str:
    if isinstance(content, VideoContent):
        if content.is_gif:
            return "动图"
        if content.live_photo_path is not None:
            return "实况照片"
        if content.is_live_photo:
            return "视频(实况源)"
        return "视频"
    if isinstance(content, ImageContent):
        return "图片"
    return type(content).__name__


# ==================== 主流程 ==================== #


class _AbortFlow(Exception):
    """步骤失败到没法继续时抛出，由 :func:`run_debug_probe` 收口。"""


async def _step(
    steps: list[DebugStep],
    events: EventLog,
    name: str,
    action: Callable[[], Awaitable[Any]],
    *,
    fatal: bool,
    detail_of: Callable[[Any], str] | None = None,
    skip_statuses: tuple[type[BaseException], ...] = (),
) -> Any:
    """执行一步并记录状态、耗时与异常栈。

    ``fatal`` 为真时，失败与「按设计跳过」都会中断后续步骤——两者都意味着
    拿不到结果，继续往下跑只会刷一堆 AttributeError。
    """
    started = time.monotonic()
    try:
        value = await action()
    except skip_statuses as exc:
        # 按设计跳过（如视频时长超限）不算失败
        cost = _ms(started)
        events.info(f"[跳过] {name}：{_describe(exc)}（{cost} ms）")
        steps.append(DebugStep(name, "skip", _describe(exc), cost))
        if fatal:
            raise _AbortFlow from exc
        return None
    except Exception as exc:  # noqa: BLE001 - 调试页必须把失败原因完整带出来
        cost = _ms(started)
        events.error(f"[失败] {name}：{_describe(exc)}（{cost} ms）", exc)
        steps.append(DebugStep(name, "fail", _describe(exc), cost, traceback.format_exc()))
        if fatal:
            raise _AbortFlow from exc
        return None

    cost = _ms(started)
    detail = detail_of(value) if detail_of else ""
    events.info(f"[完成] {name}：{detail}（{cost} ms）" if detail else f"[完成] {name}（{cost} ms）")
    steps.append(DebugStep(name, "ok", detail, cost))
    return value


async def run_debug_probe(
    plugin: Any,
    url: str,
    *,
    download_media: bool = True,
    render_card: bool = True,
) -> DebugReport:
    """对 ``url`` 跑一遍完整解析流程，返回带日志正文的报告。"""
    token = uuid.uuid4().hex[:12]
    started_wall = datetime.now()
    started = time.monotonic()
    steps: list[DebugStep] = []
    summary: dict[str, Any] = {}
    platform_name = ""
    events = EventLog()

    events.info(
        f"开始调试：{url}"
        f"（下载媒体={'是' if download_media else '否'} / 渲染卡片={'是' if render_card else '否'}）"
    )
    logger.info("=" * 60)
    logger.info("[调试] 开始测试解析: %s", url)
    try:
        platform_name, summary = await _run_pipeline(
            plugin,
            url,
            token,
            steps,
            events,
            summary,
            download_media=download_media,
            render_card=render_card,
        )
    except _AbortFlow:
        events.warn("流程在失败步骤处中止，后续步骤未执行")
    except Exception as exc:  # noqa: BLE001 - 兜底，保证一定产出报告
        events.error("未预期异常，流程中止", exc)
        steps.append(
            DebugStep("未预期异常", "fail", _describe(exc), 0, traceback.format_exc())
        )
    elapsed = _ms(started)
    events.info(f"流程结束，总耗时 {elapsed} ms")
    logger.info("[调试] 流程结束，耗时 %d ms", _ms(started))
    logger.info("=" * 60)

    ok = bool(steps) and all(step.status != "fail" for step in steps)
    text = _build_report_text(
        plugin,
        url,
        token,
        started_wall,
        elapsed,
        steps,
        summary,
        events.text,
        download_media,
        render_card,
    )
    log_path = _write_report(plugin, token, text)
    return DebugReport(
        token=token,
        url=url,
        platform=platform_name,
        ok=ok,
        steps=steps,
        summary=summary,
        log_path=log_path,
        text=text,
        elapsed_ms=elapsed,
        started_at=started_wall,
    )


async def _run_pipeline(
    plugin: Any,
    url: str,
    token: str,
    steps: list[DebugStep],
    events: EventLog,
    summary: dict[str, Any],
    *,
    download_media: bool,
    render_card: bool,
) -> tuple[str, dict[str, Any]]:
    """跑完整流程；fatal 步骤失败会抛 :class:`_AbortFlow`。"""
    # ---------- 1. 识别平台 ----------
    async def _detect() -> Any:
        if not plugin.parsers:
            raise ParseException("没有任何已启用的解析器（检查「解析器开关」）")
        attempts: list[str] = []
        for name, parser in plugin.parsers.items():
            try:
                parser.search_url(url)
            except (ParseException, SilentException):
                attempts.append(f"{name}✗")
                continue
            attempts.append(f"{name}✓")
            return name, parser
        raise ParseException(f"没有平台能处理该链接（{' '.join(attempts)}）")

    detected = await _step(
        steps,
        events,
        "识别平台",
        _detect,
        fatal=True,
        detail_of=lambda v: f"{v[0]}（{v[1].platform.display_name}）",
    )
    _, parser = detected
    platform_name: str = detected[0]

    disabled = getattr(plugin, "disabled_platforms", None)
    if disabled:
        summary["已禁用的平台"] = ", ".join(disabled)

    # ---------- 2. 缓存标识 ----------
    identity = await _step(
        steps,
        events,
        "缓存标识",
        lambda: parser.cache_identity(url),
        fatal=True,
        detail_of=lambda v: str(v),
    )
    summary["缓存标识"] = identity
    ttl = getattr(parser, "CACHE_TTL_SECONDS", None)
    summary["结果缓存有效期"] = f"{ttl}s" if ttl else "不设有效期"

    # ---------- 3. 解析 ----------
    keyword, searched = parser.search_url(url)
    summary["匹配关键词"] = keyword

    async def _parse() -> Any:
        return await parser.parse(keyword, searched)

    result = await _step(
        steps,
        events,
        "解析接口",
        _parse,
        fatal=True,
        # 视频时长超限之类的「按设计跳过」在这里记 SKIP，不算解析失败
        skip_statuses=(IgnoreException, SilentException),
        detail_of=lambda r: f"{r.platform.display_name} · {r.extra.get('content_type', '动态')}",
    )

    summary.update(_summarize_result(result))

    # ---------- 4. 媒体下载 ----------
    if download_media:
        await _download_all(result, steps, events, summary)
    else:
        events.info("[跳过] 媒体下载：已按选项跳过")
        steps.append(DebugStep("媒体下载", "skip", "已按选项跳过", 0))

    # ---------- 5. 卡片渲染 ----------
    renderer = getattr(plugin, "_renderer", None)
    if not render_card:
        events.info("[跳过] 卡片渲染：已按选项跳过")
        steps.append(DebugStep("卡片渲染", "skip", "已按选项跳过", 0))
    elif renderer is None or not renderer.enabled:
        events.warn("[跳过] 卡片渲染：渲染未启用（或 Pillow 缺失）")
        steps.append(DebugStep("卡片渲染", "skip", "渲染未启用（或 Pillow 缺失）", 0))
    else:
        # cache_key 带上本次会话标识，卡片文件名唯一 —— 不会覆盖真正发出去的那张
        rendered = await _step(
            steps,
            events,
            "卡片渲染",
            lambda: renderer.render(result, cache_key=f"debug_{token}"),
            fatal=False,
            detail_of=lambda p: _file_info(p) if p else "返回 None（失败详情见日志）",
        )
        summary["卡片文件"] = _file_info(rendered) if rendered else "未生成"

    # ---------- 6. 输出构建 ----------
    built = await _step(
        steps,
        events,
        "输出构建",
        lambda: build_platform_output(result, platform_name),
        fatal=False,
        detail_of=lambda v: f"header={v[0]!r}，节点 {len(v[1])} 组",
    )
    if built:
        summary["消息头"] = built[0]

    # ---------- 7. Cloudflare 兜底判断 ----------
    await _cloudflare_step(plugin, url, steps, events, summary)
    return platform_name, summary


async def _download_all(
    result: Any,
    steps: list[DebugStep],
    events: EventLog,
    summary: dict[str, Any],
) -> None:
    """逐个取媒体路径，失败不影响后续（与主流程的 safe_get 语义一致）。

    ``safe_get`` 会把「按设计跳过」（时长超限等）和**真正的下载失败**一起吞成
    ``None``，只靠返回值分不出来——所以这里用它的 ``on_error`` 回调把异常捞回来，
    再按类型分类。否则一个超长视频会被记成「下载失败」，把看日志的人带偏。
    """
    targets: list[tuple[str, Any]] = []
    for index, content in enumerate(result.contents, 1):
        targets.append((f"#{index} {_media_kind(content)}", content.path_task))
        if isinstance(content, VideoContent):
            if content.cover is not None:
                targets.append((f"#{index} 封面", content.cover))
            if content.still_path is not None and content.still_path is not content.path_task:
                targets.append((f"#{index} 图片产物", content.still_path))

    started = time.monotonic()
    if not targets:
        events.info("[跳过] 媒体下载：解析结果里没有媒体内容")
        steps.append(DebugStep("媒体下载", "skip", "解析结果里没有媒体内容", _ms(started)))
        summary["媒体下载"] = "无"
        return

    lines: list[str] = []
    done = failed = skipped = 0
    for label, task in targets:
        item_started = time.monotonic()
        caught: list[BaseException] = []
        path: Path | None = None
        try:
            path = await task.safe_get(on_error=caught.append)
        except Exception as exc:  # noqa: BLE001 - safe_get 已兜底，这里再兜一层
            caught.append(exc)
        cost = _ms(item_started)

        if path is not None:
            done += 1
            lines.append(f"      {label}: {_file_info(path)}（{cost} ms）")
            events.info(f"媒体 {label}：{_file_info(path)}（{cost} ms）")
            continue

        exc = caught[0] if caught else None
        if isinstance(exc, _SKIP_EXCEPTIONS):
            skipped += 1
            reason = _skip_reason(exc)
            lines.append(f"      {label}: [跳过] {reason}（{cost} ms）")
            events.info(f"媒体 {label} 按设计跳过：{reason}（{cost} ms）")
        else:
            failed += 1
            reason = _describe(exc) if exc else "没拿到异常"
            lines.append(f"      {label}: [失败] {reason}（{cost} ms）")
            # 带堆栈：这条以前只能靠框架日志里那句 logger.exception，现在自己记
            events.error(f"媒体 {label} 下载失败：{reason}（{cost} ms）", exc)

    counts = f"{len(targets)} 个媒体，成功 {done} 个"
    if failed:
        counts += f"，失败 {failed} 个"
    if skipped:
        counts += f"，按设计跳过 {skipped} 个"
    if failed:
        status = "fail"
    elif skipped and not done:
        # 全被跳过时算法不产出媒体，这一步没干活，标成跳过比标通过准确
        status = "skip"
    else:
        status = "ok"
    steps.append(DebugStep("媒体下载", status, counts, _ms(started)))
    summary["媒体下载"] = "\n".join(lines)


async def _cloudflare_step(
    plugin: Any,
    url: str,
    steps: list[DebugStep],
    events: EventLog,
    summary: dict[str, Any],
) -> None:
    """报告 Cloudflare 兜底会不会接管这个链接（不改动任何状态）。"""
    from .web_screenshot import is_url_blacklisted

    pconfig = _safe_config()
    if pconfig is None or not pconfig.CLOUDFLARE_FALLBACK_ENABLED:
        events.info("[跳过] Cloudflare 兜底：未启用")
        steps.append(DebugStep("Cloudflare 兜底", "skip", "未启用", 0))
        return
    client = getattr(plugin, "_cloudflare_client", None)
    if client is None or not client.is_configured:
        events.warn("[跳过] Cloudflare 兜底：已启用但缺少账号 ID / Token")
        steps.append(DebugStep("Cloudflare 兜底", "skip", "已启用但缺少账号 ID / Token", 0))
        return
    if is_url_blacklisted(url, pconfig.CLOUDFLARE_BLACKLIST):
        events.info("[跳过] Cloudflare 兜底：命中截图黑名单")
        steps.append(DebugStep("Cloudflare 兜底", "skip", "命中截图黑名单", 0))
        summary["Cloudflare 兜底"] = "命中黑名单，会跳过"
        return
    # 平台解析已经命中，兜底本来就不会触发；这里只报告「如果没命中会不会兜底」
    events.info("Cloudflare 兜底可用，但本链接已由适配器处理，不会走兜底")
    steps.append(DebugStep("Cloudflare 兜底", "ok", "可用（本链接已被适配器接管）", 0))
    summary["Cloudflare 兜底"] = "可用；但本链接已由适配器处理，不会走兜底"


def _summarize_result(result: Any) -> dict[str, Any]:
    """把 ParseResult 摘成报告里的一段。"""
    if result is None:
        return {}
    video = result.video
    summary: dict[str, Any] = {
        "标题": result.title or "（无）",
        "作者": (result.author.name if result.author else "（无）"),
        "内容类型": result.extra.get("content_type", "（未标注）"),
        "媒体数量": len(result.contents),
        "图集图片": len(result.all_grid_images),
        "视频": _media_kind(video) if video else "—",
        "正文长度": len(result.text or ""),
        "分享链接": result.url or "（无）",
    }
    for key, label in (
        ("duration", "时长"),
        ("online", "在线人数"),
        ("stats_line", "统计行"),
    ):
        value = result.extra.get(key)
        if value:
            summary[label] = str(value)
    warnings = result.extra.get("limit_warnings") or []
    if warnings:
        summary["警告"] = "；".join(str(w) for w in warnings)
    if result.graphics:
        summary["图文列表"] = f"{len(result.graphics)} 项"
    return summary


# ==================== 报告落盘 ==================== #


def debug_dir(plugin: Any) -> Path:
    path = Path(plugin.cache_dir) / "debug"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_report(plugin: Any, token: str, text: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = debug_dir(plugin) / f"debug_{stamp}_{token}.log"
    try:
        path.write_text(text, encoding="utf-8")
    except OSError:
        logger.warning("[调试] 报告写入失败: %s", path, exc_info=True)
    return path


def _environment_lines(plugin: Any) -> list[str]:
    pconfig = _safe_config()
    lines = [
        f"Python      : {sys.version.split()[0]} ({_platform.system()} {_platform.release()})",
        f"插件数据目录: {Path(plugin.cache_dir).parent}",
        f"缓存目录    : {plugin.cache_dir}",
        f"已启用平台  : {', '.join(plugin.parsers) or '（无）'}",
        f"已禁用平台  : {', '.join(getattr(plugin, 'disabled_platforms', []) or []) or '（无）'}",
    ]
    renderer = getattr(plugin, "_renderer", None)
    if renderer is not None:
        lines.append(
            f"卡片渲染    : {'开' if renderer.enabled else '关'}"
            f"（主题 {renderer.theme_name} / 布局 {renderer.layout_name} / 宽度 {renderer.width}px）"
        )
    client = getattr(plugin, "_cloudflare_client", None)
    if client is not None:
        lines.append(f"CF 截图     : {'已配置' if client.is_configured else '未配置凭据'}")
    if pconfig is not None:
        # 只列非敏感项；Cookie / Token 一律只报长度
        lines.append(
            f"关键配置    : 渲染={pconfig.RENDER_ENABLED} 时长上限={pconfig.VIDEO_DURATION_MAXIMUM}s "
            f"B站清晰度={pconfig.BILI_QUALITY} 调试日志={pconfig.DEBUG_LOG_ENABLED}"
        )
        for key in _SECRET_KEYS:
            value = getattr(pconfig, key, None)
            # 配置项声明为 string 但 schema 没给默认值时可能拿到字面量 "None"，一并当空处理
            if not isinstance(value, str):
                continue
            text = value.strip()
            if text and text.lower() != "none":
                lines.append(f"{key:<12}: 已配置（{len(text)} 字符，内容已打码）")
    return lines


def _build_report_text(
    plugin: Any,
    url: str,
    token: str,
    started_at: datetime,
    elapsed_ms: int,
    steps: list[DebugStep],
    summary: dict[str, Any],
    events_text: str,
    download_media: bool,
    render_card: bool,
) -> str:
    line = "=" * 72
    parts = [
        line,
        "莉卡解析 · 链接调试报告",
        line,
        f"生成时间 : {started_at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"目标链接 : {url}",
        f"选项     : 下载媒体={'是' if download_media else '否'} / 渲染卡片={'是' if render_card else '否'}",
        f"总耗时   : {elapsed_ms} ms",
        f"会话标识 : {token}",
        "",
        "---- 运行环境 " + "-" * 58,
        *_environment_lines(plugin),
        "",
        "---- 流程步骤 " + "-" * 58,
    ]
    icons = {"ok": "[ OK ]", "fail": "[FAIL]", "skip": "[SKIP]"}
    for index, step in enumerate(steps, 1):
        parts.append(
            f"{index:>2}. {icons.get(step.status, '[????]')} {step.name}"
            f"  ({step.elapsed_ms} ms)"
        )
        if step.detail:
            for text in step.detail.splitlines():
                parts.append(f"        {text}")
        if step.traceback_text:
            for text in step.traceback_text.rstrip().splitlines():
                parts.append(f"        | {text}")

    parts += ["", "---- 解析结果 " + "-" * 58]
    if summary:
        width = max(_display_width(str(key)) for key in summary)
        for key, value in summary.items():
            value_lines = str(value).splitlines() or [""]
            parts.append(f"{_pad(str(key), width)} : {value_lines[0]}")
            for extra in value_lines[1:]:
                parts.append(f"{' ' * width}   {extra}")
    else:
        parts.append("（解析未走到产出结果）")

    failed = [step for step in steps if step.status == "fail"]
    skipped = [step for step in steps if step.status == "skip"]
    if failed:
        verdict = f"有 {len(failed)} 个步骤失败：" + "、".join(step.name for step in failed)
    else:
        verdict = f"流程全部通过，耗时 {elapsed_ms} ms。"
        if skipped:
            verdict += f"（{len(skipped)} 步按设计跳过：" + "、".join(
                step.name for step in skipped
            ) + "）"
    parts += [
        "",
        "---- 结论 " + "-" * 62,
        verdict,
        "",
        "---- 流程日志 " + "-" * 58,
        "本段由探针自己记录（每一步的结果、媒体逐项结果、跳过与失败的原因），不含框架日志；",
        "插件在 AstrBot 日志面板里的完整输出不受本次调试影响。",
        "",
        events_text or "（本次没有记录到事件）",
        "",
        line,
        "报告结束",
        line,
        "",
    ]
    return _mask("\n".join(parts))
