"""插件网页设置页的后端接口层。

页面在 ``pages/rika/``，通过 AstrBot 的 bridge 调用这里注册的接口。分工：

- 本模块只做「取参数 → 校验 → 调用 :mod:`link_parser.config` 的读写能力 → 拼 JSON」，
  不重复实现解析/渲染/登录逻辑。
- 路由统一带插件名前缀（``/astrbot_plugin_rika_share/xxx``），这是 AstrBot 的要求；
  页面侧通过 bridge 写的是去掉前缀的相对路径。
- 只暴露**配置读写**与**链接调试**：保存后由 ``ParserPlugin.apply_runtime_config()`` 把新值应用到
  渲染器 / 解析器 / 截图客户端，不需要重载插件；调试接口只读地跑一遍流程并回传报告，不改运行时状态。

安全约定：页面运行在受限 iframe 里，但后端仍按「不可信输入」处理——
配置只接受 :data:`~link_parser.config.CONFIG_META` 白名单里的键，
且每个值都要过 :func:`~link_parser.config.coerce_value` 的类型与范围校验。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from astrbot.api import logger

from .config import (
    config_meta_payload,
    get_config,
    platform_options,
    verify_schema_alignment,
)

PLUGIN_NAME = "astrbot_plugin_rika_share"

#: 调试接口接受的链接长度上限
MAX_URL_LENGTH = 2048

#: 调试日志标识的合法形态（纯十六进制，防目录穿越）
_DEBUG_TOKEN_RE = re.compile(r"[0-9a-f]{12}")


def _json_response(data: Any, status_code: int = 200):
    from astrbot.api.web import json_response

    return json_response(data, status_code=status_code)


def _error(message: str, status_code: int = 400):
    from astrbot.api.web import error_response

    return error_response(message, status_code=status_code)


def _plugin_version() -> str:
    """读 ``metadata.yaml`` 里的版本号（取不到返回空串）。"""
    try:
        path = Path(__file__).resolve().parent.parent / "metadata.yaml"
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("version:"):
                return line.split(":", 1)[1].strip().strip('"').strip("'")
    except Exception:  # noqa: BLE001 - 版本号只用于展示，读不到就留空
        logger.debug("[link_parser] 读取 metadata.yaml 版本号失败", exc_info=True)
    return ""


def read_schema_problems() -> list[str]:
    """读 ``_conf_schema.json`` 并自检它与 CONFIG_META 是否一致。"""
    try:
        import json

        path = Path(__file__).resolve().parent.parent / "_conf_schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 自检失败不应影响页面可用
        logger.warning("[link_parser] 无法读取 _conf_schema.json，跳过一致性自检", exc_info=True)
        return []
    problems = verify_schema_alignment(schema)
    for problem in problems:
        logger.warning(f"[link_parser] 配置 schema 不一致：{problem}")
    return problems


class WebUIApi:
    """插件网页设置页的接口集合。"""

    def __init__(self, plugin: Any):
        self.plugin = plugin

    # ==================== 注册 ==================== #

    def register(self) -> None:
        context = self.plugin.context
        routes: tuple[tuple[str, Callable[..., Any], tuple[str, ...], str], ...] = (
            ("/config", self.get_config, ("GET",), "读取全部配置项"),
            ("/config", self.save_config, ("POST",), "保存配置项"),
            ("/config/reset", self.reset_config, ("POST",), "恢复默认配置"),
            ("/debug/run", self.debug_run, ("POST",), "对链接跑一遍解析流程并生成日志"),
            ("/debug/log", self.debug_log, ("GET",), "下载调试日志"),
        )
        for suffix, handler, methods, desc in routes:
            context.register_web_api(f"/{PLUGIN_NAME}{suffix}", handler, list(methods), desc)

    # ==================== 配置 ==================== #

    async def get_config(self):
        pconfig = get_config()
        payload = config_meta_payload()
        payload["values"] = pconfig.current_values()
        payload["problems"] = read_schema_problems()
        payload["version"] = _plugin_version()
        # 解析器开关的平台清单来自适配器注册表，新增平台自动出现
        payload["platforms"] = platform_options(pconfig)
        return _json_response(payload)

    async def save_config(self):
        from astrbot.api.web import request

        body = await request.json(default={}) or {}
        values = body.get("values") if isinstance(body, dict) else None
        if not isinstance(values, dict) or not values:
            return _error("没有需要保存的配置项")

        pconfig = get_config()
        changed, errors = pconfig.apply_updates(values)
        runtime_ok = True
        runtime: dict[str, Any] = {}
        if changed:
            try:
                runtime = await self.plugin.apply_runtime_config()
            except Exception as exc:  # noqa: BLE001 - 热更新失败不能吞掉已保存的配置
                runtime_ok = False
                logger.warning("[link_parser] 应用新配置失败", exc_info=True)
                errors.append(f"配置已保存，但运行时热更新失败：{str(exc)[:120]}")
        return _json_response(
            {
                "changed": changed,
                "errors": errors,
                "runtime_ok": runtime_ok,
                "runtime": runtime,
                "values": pconfig.current_values(),
            }
        )

    # ==================== 链接调试 ==================== #

    async def debug_run(self):
        """对提交的链接跑一遍完整解析流程，返回步骤结果 + 日志正文。"""
        from astrbot.api.web import request

        from .services.debug_probe import run_debug_probe

        body = await request.json(default={}) or {}
        url = str(body.get("url") or "").strip()
        if not url:
            return _error("请填写要测试的链接")
        if len(url) > MAX_URL_LENGTH:
            return _error(f"链接过长（上限 {MAX_URL_LENGTH} 字符）")
        if not url.lower().startswith(("http://", "https://")):
            return _error("链接需要以 http:// 或 https:// 开头")

        # 页面给的是「是否执行」的开关，缺省都执行
        download_media = body.get("download_media", True) is not False
        render_card = body.get("render_card", True) is not False

        try:
            report = await run_debug_probe(
                self.plugin,
                url,
                download_media=download_media,
                render_card=render_card,
            )
        except Exception as exc:  # noqa: BLE001 - 调试接口本身也不能把栈抛给页面
            logger.exception("[link_parser] 调试流程异常")
            return _error(f"调试流程异常：{str(exc)[:200]}", status_code=500)
        return _json_response(report.payload())

    async def debug_log(self):
        """下载调试日志文本。``token`` 只允许十六进制，防止目录穿越。"""
        from astrbot.api.web import file_response, request

        from .services.debug_probe import debug_dir

        token = str(request.query.get("token") or "").strip().lower()
        if not _DEBUG_TOKEN_RE.fullmatch(token):
            return _error("无效的日志标识")

        directory = debug_dir(self.plugin)
        # 不记内存状态：按 token 后缀找（重载插件后依然能下载）
        matches = sorted(directory.glob(f"debug_*_{token}.log"), reverse=True)
        if not matches:
            return _error("日志已不存在（可能已被缓存清理），请重新测试")
        path = matches[0]
        return file_response(
            path,
            filename=f"rika_debug_{token}.log",
            content_type="text/plain; charset=utf-8",
        )

    async def reset_config(self):
        pconfig = get_config()
        changed = pconfig.reset_to_defaults()
        runtime_ok = True
        runtime: dict[str, Any] = {}
        errors: list[str] = []
        if changed:
            try:
                runtime = await self.plugin.apply_runtime_config()
            except Exception as exc:  # noqa: BLE001 - 同上
                runtime_ok = False
                logger.warning("[link_parser] 恢复默认配置后热更新失败", exc_info=True)
                errors.append(f"已恢复默认，但运行时热更新失败：{str(exc)[:120]}")
        return _json_response(
            {
                "changed": changed,
                "errors": errors,
                "runtime_ok": runtime_ok,
                "runtime": runtime,
                "values": pconfig.current_values(),
            }
        )
