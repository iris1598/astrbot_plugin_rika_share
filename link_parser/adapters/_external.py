"""外部解析器插件接入点。

外部插件可以把自己注册为本插件的一个「平台适配器」：它提供一个**桥接模块**
（在 ``data.plugins.<插件名>/`` 下，默认文件名 ``rikashare_bridge.py``），模块内
暴露 ``register(api)`` 函数，通过注入的 SDK 句柄声明解析器：

```python
def register(api):
    parser = api.parser(name="foo", display_name="Foo", url_pattern=r"foo\\.com")

    @parser.handle("foo.com", r"foo\\.com/video/(?P<vid>\\d+)")
    async def _parse(ctx):
        return ctx.result(title="…", url=ctx.matched)

    parser.register()
```

这里的 ``api`` 是 :class:`link_parser.external.ParserAPI`——**外部插件不需要 import
本插件的任何内部模块**（插件在 AstrBot 里的模块根是 ``data.plugins.<目录名>``，
写死路径很容易随版本失效）。

探测与接入时机：``main.py`` 在**生成平台 Handler 之前**调用
:func:`register_external_adapters`，逐个探测外部插件，已安装则导入其桥接模块并
调用 ``register(api)``。注册表是 Handler 生成的输入，所以这个顺序不能改。

- 外部插件**已安装**：对应平台进入注册表，事件过滤器、解析器实例化、
  设置页「解析器开关」等全部按内置平台同样的机制自动生效；
- 外部插件**未安装**：没有这个解析器，仅记一条 DEBUG 日志，其余功能不受影响；
- 桥接模块缺失 / 导入失败 / 注册抛异常：记 WARNING 并跳过该平台，不连累本插件加载。

为什么不做成「外部插件主动注册」：适配器注册表驱动着平台 Handler 的生成，
而 Handler 在本插件入口模块导入时就已按注册表快照生成完毕——外部插件的
加载顺序不受本插件控制（且可能晚于本插件实例化），主动注册会错过这两个
时机。反过来由本插件在导入阶段「拉取」外部桥接模块，时机就是确定的。
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from types import ModuleType

from astrbot.api import logger

from ..external import API

#: 桥接模块的约定文件名（不含 ``.py``）。外部插件只要在目录下放这个文件即视为
#: 愿意接入，无需在本插件里登记。
BRIDGE_MODULE_NAME = "rikashare_bridge"

#: 显式登记的 (外部插件目录名, 桥接模块名) 清单。
#:
#: 自动发现已经覆盖了绝大多数场景，这里只用于两种情况：
#: ① 桥接模块名不符合约定（不是 ``rikashare_bridge.py``）；
#: ② 需要固定接入顺序 / 提前于自动发现探测的关键插件。
EXTERNAL_ADAPTERS: tuple[tuple[str, str], ...] = (
    ("astrbot_plugin_multincm", "rikashare_bridge"),
)

#: 外部插件包的候选模块根：插件以 ``data.plugins.<目录名>`` 加载，
#: 保留插件前缀与裸包名作为回退（开发脚本 / 未来模块根变化）。
_MODULE_ROOTS = ("data.plugins", "astrbot.builtin_stars", "")

#: 本插件自己的目录名：自动发现要跳过自己。
_SELF_PLUGIN = "astrbot_plugin_rika_share"


def _plugin_root() -> Path | None:
    """``data/plugins`` 目录；读不到路径或目录不存在时返回 ``None``。"""
    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_plugin_path

        plugin_root = Path(get_astrbot_plugin_path())
    except Exception as exc:  # noqa: BLE001 - 自动发现不是必需能力
        logger.debug(f"[link_parser] 定位数据插件目录失败，跳过自动发现: {exc}")
        return None
    return plugin_root if plugin_root.is_dir() else None


def _discover_bridges() -> list[tuple[str, str]]:
    """自动发现装了约定桥接模块的插件，返回 ``(插件目录名, 桥接模块名)``。

    ``data/plugins`` 下凡是有 ``rikashare_bridge.py`` 的插件都视为愿意接入；
    只检查文件是否存在，**不导入**，因此放进来的坏文件不会拖垮本插件加载
    （真正的导入在 :func:`register_external_adapters` 里逐个 try）。
    """
    plugin_root = _plugin_root()
    if plugin_root is None:
        return []

    discovered: list[tuple[str, str]] = []
    try:
        entries = list(plugin_root.iterdir())
    except OSError as exc:
        logger.debug(f"[link_parser] 扫描数据插件目录失败，跳过自动发现: {exc}")
        return discovered

    for entry in entries:
        name = entry.name
        # 只看常规插件目录：排除本插件、隐藏/暂存目录，以及没有 metadata.yaml 的普通包
        if (
            name.startswith((".", "_"))
            or name == _SELF_PLUGIN
            or not (entry / "metadata.yaml").is_file()
            or not (entry / f"{BRIDGE_MODULE_NAME}.py").is_file()
        ):
            continue
        discovered.append((name, BRIDGE_MODULE_NAME))
    return discovered


def _import_bridge(plugin_name: str, bridge_name: str) -> ModuleType | None:
    """导入外部插件的桥接模块。

    返回 ``None`` 表示**插件包本身不存在**（未安装）；桥接缺失 / 依赖缺失 /
    桥接内部错误则原样抛出，由调用方记 WARNING——两者是不同的问题，
    日志级别也必须不同。
    """
    package: ModuleType | None = None
    for root in _MODULE_ROOTS:
        plugin_root = f"{root}.{plugin_name}" if root else plugin_name
        try:
            package = importlib.import_module(plugin_root)
            break
        except ModuleNotFoundError as exc:
            missing = exc.name or ""
            # 缺的是「候选根自身」（如 astrbot.builtin_stars 整包不存在）或插件包本身：
            # 都说明这条路走不通，换下一个候选根。缺的是插件内部依赖时不在此列，
            # 要原样抛出由调用方记 WARNING。
            if missing == plugin_root or (
                missing and plugin_root.startswith(f"{missing}.")
            ):
                continue
            raise
    if package is None:
        return None
    # 注意：桥接模块缺失时这里会抛 ModuleNotFoundError，与「插件未安装」是两回事
    return importlib.import_module(f"{package.__name__}.{bridge_name}")


def _call_register(module: ModuleType) -> bool:
    """调用桥接模块的 ``register``：注入 SDK 句柄，兼容旧的无参签名。

    用签名判断而不是靠捕获 ``TypeError``：后者会把桥接内部真正的 TypeError
    误当成「签名不匹配」，从而掩盖真实故障。

    Returns:
        ``False`` 表示模块没有 ``register()``。
    """
    register = getattr(module, "register", None)
    if not callable(register):
        return False

    try:
        accepts_arg = bool(inspect.signature(register).parameters)
    except (TypeError, ValueError):
        accepts_arg = True  # 内建 / C 扩展无法取签名：按新契约调用

    if accepts_arg:
        register(API)
    else:
        # 旧版桥接 ``def register()``：SDK 句柄注入不了，退回无参调用。
        logger.debug(
            f"[link_parser] {module.__name__} 的 register() 未接收参数，"
            "按旧契约调用（建议改为 register(api) 以使用 SDK）"
        )
        register()
    return True


def _connect(plugin_name: str, bridge_name: str) -> None:
    """接入单个外部插件：导入桥接模块并调用其 ``register``。"""
    module = _import_bridge(plugin_name, bridge_name)
    if module is None:
        logger.debug(f"[link_parser] 外部解析器插件 {plugin_name} 未安装，跳过")
        return

    if not _call_register(module):
        logger.warning(
            f"[link_parser] 外部解析器桥接模块 {plugin_name}.{bridge_name} "
            "缺少 register(api) 函数，跳过接入"
        )
        return
    logger.info(f"[link_parser] 已接入外部解析器插件: {plugin_name}")


def register_external_adapters() -> None:
    """探测并接入全部已安装的外部解析器插件。

    必须在 ``main.py`` 生成 ``_PLATFORM_HANDLERS`` 之前调用：注册表是
    Handler 生成的输入，晚于它就没有事件入口了。

    显式清单（:data:`EXTERNAL_ADAPTERS`）优先，随后再补上自动发现的桥接模块；
    重复的插件只接入一次。
    """
    seen: set[str] = set()
    candidates: list[tuple[str, str]] = list(EXTERNAL_ADAPTERS)
    listed = {name for name, _ in candidates}
    candidates.extend(item for item in _discover_bridges() if item[0] not in listed)

    for plugin_name, bridge_name in candidates:
        if plugin_name in seen:
            continue
        seen.add(plugin_name)
        try:
            _connect(plugin_name, bridge_name)
        except ModuleNotFoundError as exc:
            logger.warning(
                f"[link_parser] 外部解析器插件 {plugin_name} 缺少桥接模块 "
                f"{bridge_name}（或该模块依赖缺失），请升级该插件；已跳过接入: {exc}"
            )
        except Exception as exc:  # noqa: BLE001 - 外部插件坏了不能连累本插件加载
            logger.warning(
                f"[link_parser] 外部解析器接入失败，跳过 {plugin_name}: {exc}",
                exc_info=True,
            )


__all__ = [
    "BRIDGE_MODULE_NAME",
    "EXTERNAL_ADAPTERS",
    "register_external_adapters",
]
