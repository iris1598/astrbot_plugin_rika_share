"""外部解析器插件接入点。

外部插件可以把自己注册为本插件的一个「平台适配器」：它提供一个**桥接模块**
（在 ``data.plugins.<插件名>/`` 下），模块内定义继承
:class:`~link_parser.adapters.base.BaseParser` 的解析器并暴露 ``register()``
函数（内部调用 :func:`~link_parser.adapters.registry.register_adapter`）。

本插件在入口模块（``main.py``）导入阶段、**生成平台 Handler 之前**调用
:func:`register_external_adapters`：逐个探测外部插件，已安装则导入其桥接模块
并调用 ``register()``。

- 外部插件**已安装**：对应平台进入注册表，事件过滤器、解析器实例化、
  设置页「解析器开关」等全部按内置平台同样的机制自动生效；
- 外部插件**未安装**：没有这个解析器，仅记一条 DEBUG 日志，其余功能不受影响；
- 桥接模块缺失 / 导入失败 / 缺少 ``register()`` / 注册抛异常：记 WARNING 并
  跳过该平台，不连累本插件加载。

为什么不做成「外部插件主动注册」：适配器注册表驱动着平台 Handler 的生成，
而 Handler 在本插件入口模块导入时就已按注册表快照生成完毕——外部插件的
加载顺序不受本插件控制（且可能晚于本插件实例化），主动注册会错过这两个
时机。反过来由本插件在导入阶段「拉取」外部桥接模块，时机就是确定的。
"""

from __future__ import annotations

import importlib
from types import ModuleType

from astrbot.api import logger

#: (外部插件目录名, 桥接模块名) 清单。目录名同时用于拼 ``data.plugins.`` 模块路径。
EXTERNAL_ADAPTERS: tuple[tuple[str, str], ...] = (
    ("astrbot_plugin_multincm", "rikashare_bridge"),
)

#: 外部插件包的候选模块根：插件以 ``data.plugins.<目录名>`` 加载，
#: 保留插件前缀与裸包名作为回退（开发脚本 / 未来模块根变化）。
_MODULE_ROOTS = ("data.plugins", "astrbot.builtin_stars", "")


def _import_bridge(plugin_name: str, bridge_name: str) -> ModuleType:
    """导入外部插件的桥接模块。

    成功返回模块对象；外部插件包不存在时抛出普通的
    ``ModuleNotFoundError``（调用方据此记 DEBUG 级「未安装」）；其余失败
    （桥接缺失 / 依赖缺失 / 桥接内部错误）原样抛出，由调用方记 WARNING。
    """
    package: ModuleType | None = None
    for root in _MODULE_ROOTS:
        plugin_root = f"{root}.{plugin_name}" if root else plugin_name
        try:
            package = importlib.import_module(plugin_root)
            break
        except ModuleNotFoundError as exc:
            if (exc.name or "") == plugin_root:
                continue  # 插件包本身不存在：按「未安装」换下一个候选根
            raise  # 插件包内部缺依赖等：按失败处理，让调用方记 WARNING
    if package is None:
        raise ModuleNotFoundError(f"未找到外部解析器插件: {plugin_name}")
    # 注意：桥接模块缺失时这里会抛 ModuleNotFoundError，与「插件未安装」是两回事
    return importlib.import_module(f"{package.__name__}.{bridge_name}")


def register_external_adapters() -> None:
    """探测并接入全部已安装的外部解析器插件。

    必须在 ``main.py`` 生成 ``_PLATFORM_HANDLERS`` 之前调用：注册表是
    Handler 生成的输入，晚于它就没有事件入口了。
    """
    for plugin_name, bridge_name in EXTERNAL_ADAPTERS:
        try:
            module = _import_bridge(plugin_name, bridge_name)
        except ModuleNotFoundError:
            logger.warning(
                f"[link_parser] 外部解析器插件 {plugin_name} 缺少桥接模块 "
                f"{bridge_name}，请升级该插件；已跳过接入"
            )
            continue
        except Exception as exc:  # noqa: BLE001 - 外部插件坏了不能连累本插件加载
            logger.warning(
                f"[link_parser] 外部解析器桥接模块导入失败，跳过 {plugin_name}: {exc}",
                exc_info=True,
            )
            continue

        register = getattr(module, "register", None)
        if not callable(register):
            logger.warning(
                f"[link_parser] 外部解析器桥接模块缺少 register() 函数，跳过 {plugin_name}"
            )
            continue
        try:
            register()
        except Exception as exc:  # noqa: BLE001 - 注册失败只影响这一个平台
            logger.warning(
                f"[link_parser] 外部解析器注册失败，跳过 {plugin_name}: {exc}",
                exc_info=True,
            )
            continue
        logger.info(f"[link_parser] 已接入外部解析器插件: {plugin_name}")


__all__ = ["EXTERNAL_ADAPTERS", "register_external_adapters"]
