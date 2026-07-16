"""异步路径包装 - 用于延迟获取下载结果"""

import asyncio
from pathlib import Path
from collections.abc import Callable, Coroutine
from typing import Any


class PathTask:
    __slots__ = ("_path", "_task", "_error")

    def __init__(
        self,
        task: asyncio.Task[Path] | Coroutine[Any, Any, Path],
    ):
        if isinstance(task, asyncio.Task):
            self._task: asyncio.Task[Path] = task
        else:
            self._task = asyncio.create_task(task)
        self._path: Path | None = None
        self._error: Exception | None = None

    async def get(self) -> Path:
        if self._path is not None:
            return self._path
        try:
            self._path = await self._task
        except Exception as e:
            self._error = e
            raise
        return self._path

    async def safe_get(
        self,
        on_error: Callable[[Exception], None] | None = None,
    ) -> Path | None:
        try:
            return await self.get()
        except Exception as e:
            if on_error is not None:
                on_error(e)
            return None

    def is_failed(self) -> bool:
        """检查底层 task 是否已完成且抛出了异常。"""
        if self._path is not None:
            return False  # 已成功拿到路径
        if self._error is not None:
            return True  # get() 已捕获过异常
        task = self._task
        if not isinstance(task, asyncio.Task):
            return False  # 还是裸 coroutine，未调度
        return task.done() and not task.cancelled() and task.exception() is not None

    def get_error(self) -> Exception | None:
        """返回已捕获的异常对象（若有）。仅在 is_failed() 为 True 后调用才有意义。"""
        if self._error is not None:
            return self._error
        task = self._task
        if isinstance(task, asyncio.Task) and task.done() and not task.cancelled():
            exc = task.exception()
            if exc is not None:
                self._error = exc
                return exc
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
