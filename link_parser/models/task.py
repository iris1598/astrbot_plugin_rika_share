"""异步路径包装 - 用于延迟获取下载结果"""

import asyncio
from pathlib import Path
from collections.abc import Callable, Coroutine
from typing import Any

from astrbot.api import logger

from ..exceptions import IgnoreException, SilentException


class PathTask:
    __slots__ = ("_path", "_task")

    def __init__(
        self,
        task: asyncio.Task[Path] | Coroutine[Any, Any, Path],
    ):
        if isinstance(task, asyncio.Task):
            self._task: asyncio.Task[Path] = task
        else:
            self._task = asyncio.create_task(task)
        self._path: Path | None = None

    async def get(self) -> Path:
        if self._path is not None:
            return self._path
        self._path = await self._task
        return self._path

    async def safe_get(
        self,
        on_error: Callable[[Exception], None] | None = None,
    ) -> Path | None:
        try:
            return await self.get()
        except (IgnoreException, SilentException) as e:
            # 控制流异常：例如视频时长超过限制时主动跳过下载。这不是错误，
            # 却会走到这里（任务由 create_task 创建，异常在此处才被取回）。
            # 打成 DEBUG，否则每遇到一个超长视频就刷一段 ERROR + traceback。
            logger.debug(f"PathTask 按设计跳过 | task={self._task.get_name()}: {e}")
            if on_error is not None:
                on_error(e)
            return None
        except Exception as e:
            from ..config import get_config

            # 配置还没初始化时 get_config() 自己会抛，别让它把真正的失败原因顶掉
            try:
                verbose = get_config().DEBUG_LOG_ENABLED
            except Exception:  # noqa: BLE001 - 只影响日志详细程度
                verbose = False
            if verbose:
                logger.exception(f"PathTask 获取失败 | task={self._task.get_name()}")
            if on_error is not None:
                on_error(e)
            return None

    @property
    async def uri(self) -> str | None:
        path = await self.safe_get()
        return path.as_uri() if path else None

    def __repr__(self) -> str:
        if self._path is not None:
            return f"PathTask(path={self._path.name})"
        else:
            return f"PathTask(task={self._task.get_name()}, done={self._task.done()})"
