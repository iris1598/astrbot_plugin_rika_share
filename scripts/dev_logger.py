# -*- coding: utf-8 -*-
"""开发脚本用的最小日志桩。

插件代码通过 ``from astrbot.api import logger`` 取日志器；按插件审核规则，日志器
必须且只能从 ``astrbot.api`` 导入，不得使用 Python 内置的日志模块。而这些脚本要在
**没有 AstrBot** 的情况下独立运行，于是把这里的 :class:`StubLogger` 塞给
``astrbot.api.logger``——接口与插件用到的那几个方法一致（debug / info / warning /
error / exception），输出直接走 ``print``，因此会跟着脚本的 stdout 一起被 tee 进日志文件。
"""

from __future__ import annotations

import traceback

_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


class StubLogger:
    """最小日志桩：只实现插件实际用到的接口。"""

    def __init__(self, name: str = "astrbot.api", level: str = "INFO") -> None:
        self.name = name
        self.level = _LEVELS[level.upper()]

    def set_level(self, level: str) -> None:
        self.level = _LEVELS[level.upper()]

    def is_enabled_for(self, level: str) -> bool:
        return _LEVELS[level.upper()] >= self.level

    def _emit(
        self,
        level: str,
        msg: object,
        args: tuple,
        with_traceback: bool = False,
    ) -> None:
        if _LEVELS[level] < self.level:
            return
        try:
            text = str(msg) % args if args else str(msg)
        except Exception:  # noqa: BLE001 - 格式化失败也得把原文打出来
            text = f"{msg} {args}"
        # 用 print 而不是直接写 sys.stdout：脚本会重定向 stdout 做 tee，
        # 这里必须每次动态取当前流，才能把日志一起写进文件。
        print(f"{level:<7} | {text}", flush=True)
        if with_traceback:
            for line in traceback.format_exc().rstrip().splitlines():
                print(f"        | {line}", flush=True)

    def debug(self, msg, *args, **kwargs):
        self._emit("DEBUG", msg, args)

    def info(self, msg, *args, **kwargs):
        self._emit("INFO", msg, args)

    def warning(self, msg, *args, **kwargs):
        self._emit("WARNING", msg, args)

    def error(self, msg, *args, **kwargs):
        self._emit("ERROR", msg, args)

    def critical(self, msg, *args, **kwargs):
        self._emit("CRITICAL", msg, args)

    def exception(self, msg, *args, **kwargs):
        self._emit("ERROR", msg, args, with_traceback=True)


__all__ = ["StubLogger"]
