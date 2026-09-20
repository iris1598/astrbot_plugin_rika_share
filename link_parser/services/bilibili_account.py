"""B站账号服务：扫码登录、Cookie 加密持久化、有效性监控与自动应用。

从插件入口抽离出来的有状态服务，负责：

- ``/bili_login`` 扫码登录流程（生成二维码 → 轮询扫码状态 → 保存 Cookie）
- Cookie 的 Fernet 加密持久化（密钥文件与 Cookie 文件都在插件数据目录下）
- 定时检测 Cookie 有效性，失效/恢复时通知管理员，并在响应头回传新 Cookie 时自动刷新
- 将最新 Cookie 自动应用到 ``BilibiliParser``

插件入口只保留 AstrBot 指令装饰器与薄封装。
"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncGenerator, Dict, Optional

import aiohttp
import qrcode
from cryptography.fernet import Fernet
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context
from astrbot.api.event import MessageChain

from ..config import get_config
from ..output.replies import error_result

if TYPE_CHECKING:  # pragma: no cover
    from ..adapters.base import BaseParser

__all__ = ["BiliAccountService"]

# ========== B站扫码登录 API ==========
BILI_QR_GENERATE_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
BILI_QR_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
BILI_NAV_URL = "https://api.bilibili.com/x/web-interface/nav"

# 扫码状态码
QR_CODE_UNSCANNED = 86101
QR_CODE_SCANNED = 86090
QR_CODE_EXPIRED = 86038
QR_CODE_SUCCESS = 0

# 二维码有效期（秒）
QR_CODE_EXPIRE_TIME = 180
POLL_INTERVAL = 5

_COOKIE_FILE_NAME = "bili_cookie_encrypted.json"
_STATUS_FILE_NAME = "bili_cookie_status.json"
_KEY_FILE_NAME = ".bili_cookie_key"


class BiliAccountService:
    """B站 Cookie 生命周期管理。"""

    def __init__(
        self,
        context: Context,
        data_dir: Path,
        parsers: dict[str, "BaseParser"],
    ):
        self.context = context
        self.data_dir = data_dir
        self.parsers = parsers

        self._cookie: str = ""
        self._http_session: aiohttp.ClientSession | None = None
        self._monitor_running: bool = False
        self._monitor_task: asyncio.Task | None = None
        self._login_tasks: Dict[str, asyncio.Task] = {}
        self._cookie_lock = asyncio.Lock()
        self._file_lock = asyncio.Lock()
        self._last_status: Optional[Dict] = None
        self._last_check_time: Optional[datetime] = None
        self._was_invalid: bool = False

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._status_file = self.data_dir / _STATUS_FILE_NAME
        self._cookie_file = self.data_dir / _COOKIE_FILE_NAME
        self._key_file = self.data_dir / _KEY_FILE_NAME

    # ==================== 生命周期 ====================

    async def initialize(self) -> None:
        """加载持久化状态与 Cookie，建立 HTTP 会话并按需启动监控。"""
        await self._load_last_status()
        await self._load_cookie()
        self._http_session = aiohttp.ClientSession()

        if self._cookie:
            self.apply_cookie_to_parser(self._cookie)

        if get_config().BILI_COOKIE_MONITOR_ENABLED and self._cookie:
            self.start_monitor()

    async def aclose(self) -> None:
        """停止监控与轮询任务，关闭 HTTP 会话。"""
        self._monitor_running = False

        for _uid, task in list(self._login_tasks.items()):
            if not task.done():
                task.cancel()
        self._login_tasks.clear()

        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("终止B站监控任务时发生异常")

        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
            logger.debug("B站 HTTP 会话已关闭")

    # ==================== AstrBot 指令实现 ====================

    async def login(self, event: AstrMessageEvent) -> AsyncGenerator[MessageEventResult, None]:
        """扫码登录：获取二维码图片并轮询扫码结果。"""
        sender_id = event.get_sender_id()

        # 检查是否有正在进行的登录
        if sender_id in self._login_tasks and not self._login_tasks[sender_id].done():
            yield event.plain_result("⏳ 你有一个正在进行的扫码登录，请先完成或等待超时")
            return

        try:
            if not self._http_session:
                self._http_session = aiohttp.ClientSession()

            yield event.plain_result("🔄 正在生成B站登录二维码...")

            async with self._http_session.get(
                BILI_QR_GENERATE_URL,
                headers=self._api_headers(),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()

            if data.get("code") != 0:
                result = error_result(
                    event, f"❌ 获取二维码失败: {data.get('message', '未知错误')}"
                )
                if result is not None:
                    yield result
                return

            qrcode_url = data["data"]["url"]
            qrcode_key = data["data"]["qrcode_key"]

            if not qrcode_key:
                result = error_result(event, "❌ 获取qrcode_key失败")
                if result is not None:
                    yield result
                return

            # 生成二维码图片
            qr_image = self._build_qrcode_image(qrcode_url)
            if not qr_image:
                result = error_result(
                    event, "❌ 二维码生成失败，请检查是否已安装 qrcode 库"
                )
                if result is not None:
                    yield result
                return

            # 保存并发送二维码图片
            qr_path = self.data_dir / f"qrcode_{sender_id}.png"
            os.makedirs(self.data_dir, exist_ok=True)
            qr_image.save(str(qr_path), "PNG")

            yield event.image_result(str(qr_path))

            yield event.plain_result(
                "📱 请使用 **B站App** 扫描上方二维码登录\n"
                "⏱️ 二维码有效期约3分钟\n"
                "📋 扫码后请在手机上点击「确认登录」"
            )

            logger.info(
                f"已发送B站登录二维码给用户 {sender_id}，qrcode_key: {qrcode_key[:8]}..."
            )

            # 启动异步轮询
            task = asyncio.create_task(
                self._poll_qr_login(sender_id, qrcode_key, qr_path)
            )
            self._login_tasks[sender_id] = task

        except asyncio.TimeoutError:
            result = error_result(event, "❌ 请求超时，请稍后重试")
            if result is not None:
                yield result
        except aiohttp.ClientError as e:
            result = error_result(event, f"❌ 网络错误: {e}")
            if result is not None:
                yield result
        except Exception as e:
            logger.exception("扫码登录出错")
            result = error_result(event, f"❌ 生成二维码失败: {e}")
            if result is not None:
                yield result

    async def check(self, event: AstrMessageEvent) -> AsyncGenerator[MessageEventResult, None]:
        """手动检测 Cookie 状态。"""
        if not self._cookie:
            yield event.plain_result(
                "⚠️ 尚未配置B站Cookie，请使用 /bili_login 扫码登录\n"
                "或在插件配置中填入 BILI_CK"
            )
            return

        if not self._http_session:
            yield event.plain_result("⚠️ 插件正在初始化中，请稍后再试")
            return

        result = await self.check_cookie_valid()

        if result["valid"]:
            msg = (
                f"✅ B站Cookie有效\n用户: {result.get('username', '未知')}\n"
                f"UID: {result.get('uid', 0)}"
            )
            yield event.plain_result(msg)
        else:
            error = error_result(
                event, f"❌ B站Cookie失效\n错误: {result.get('error', '未知错误')}"
            )
            if error is not None:
                yield error

        self._last_status = result
        self._last_check_time = datetime.now()
        await self._save_last_status()

    def status_text(self) -> str:
        """当前 Cookie 与监控状态文案。"""
        lines = [
            f"Cookie状态: {'已配置' if self._cookie else '未配置'}",
            f"监控状态: {'运行中' if self._monitor_running else '已停止'}",
        ]
        if self._last_status:
            status = "有效" if self._last_status.get("valid") else "失效"
            lines.append(f"上次检测: {status}")
            if self._last_check_time:
                lines.append(
                    f"检测时间: {self._last_check_time.strftime('%Y-%m-%d %H:%M:%S')}"
                )
        return "\n".join(lines)

    # ==================== Cookie 应用与检测 ====================

    def apply_cookie_to_parser(self, cookie_str: str) -> None:
        """将Cookie立即应用到BilibiliParser"""
        parser = self.parsers.get("bilibili")
        if parser and hasattr(parser, "update_cookie"):
            parser.update_cookie(cookie_str)
            logger.info("B站Cookie已自动应用到BilibiliParser")
        else:
            logger.warning("BilibiliParser 不可用，无法应用Cookie")

    async def check_cookie_valid(self) -> dict:
        """检测B站Cookie是否有效"""
        if not self._cookie:
            return {"valid": False, "error": "Cookie为空"}
        if not self._http_session:
            return {"valid": False, "error": "HTTP会话未初始化"}

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Cookie": self._cookie,
            "Referer": "https://www.bilibili.com/",
        }

        try:
            async with self._http_session.get(
                BILI_NAV_URL,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()

                if data.get("code") == 0 and data.get("data", {}).get("isLogin"):
                    # Cookie有效时从响应头刷新
                    set_cookie_headers = resp.headers.getall("Set-Cookie", [])
                    if set_cookie_headers:
                        await self._refresh_cookie_from_headers(set_cookie_headers)

                    u = data["data"]
                    return {
                        "valid": True,
                        "username": u.get("uname", ""),
                        "uid": u.get("mid", 0),
                        "vip": u.get("vipStatus") == 1,
                    }
                error_msg = data.get("message", "未知错误")
                code = data.get("code")
                if code == -101:
                    error_msg = "账号未登录或Cookie已过期"
                elif code == -352:
                    error_msg = "请求被风控"
                return {"valid": False, "error": error_msg, "code": code}

        except asyncio.TimeoutError:
            return {"valid": False, "error": "请求超时"}
        except aiohttp.ClientError as e:
            return {"valid": False, "error": f"网络错误: {e}"}
        except Exception as e:
            return {"valid": False, "error": f"未知错误: {e}"}

    async def _refresh_cookie_from_headers(self, set_cookie_headers: list) -> bool:
        """从Set-Cookie响应头中刷新Cookie"""
        if not set_cookie_headers:
            return False

        new_cookies = {}
        for header in set_cookie_headers:
            cookie_part = header.split(";")[0].strip()
            if "=" in cookie_part:
                name, value = cookie_part.split("=", 1)
                name = name.strip()
                value = value.strip()
                if value:
                    new_cookies[name] = value

        if not new_cookies:
            return False

        async with self._cookie_lock:
            existing = {}
            for part in self._cookie.split(";"):
                part = part.strip()
                if "=" in part:
                    k, v = part.split("=", 1)
                    existing[k.strip()] = v.strip()

            merged = {**existing, **new_cookies}
            new_cookie_str = "; ".join(f"{k}={v}" for k, v in merged.items())

            if new_cookie_str != self._cookie:
                self._cookie = new_cookie_str
                await self._save_cookie(new_cookie_str)
                self.apply_cookie_to_parser(new_cookie_str)
                logger.info(f"B站Cookie已自动刷新，更新了 {len(new_cookies)} 个字段")
                return True

        return False

    # ==================== 监控循环 ====================

    def start_monitor(self) -> None:
        """启动Cookie监控循环"""
        if self._monitor_task and not self._monitor_task.done():
            return
        self._monitor_running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(
            f"B站Cookie监控已启动，检测间隔: {get_config().BILI_COOKIE_CHECK_INTERVAL}秒"
        )

    async def _monitor_loop(self) -> None:
        """Cookie监控循环 - 只在状态翻转时通知一次"""
        pconfig = get_config()
        while self._monitor_running:
            try:
                result = await self.check_cookie_valid()
                self._last_status = result
                self._last_check_time = datetime.now()
                await self._save_last_status()

                is_valid = result["valid"]
                if is_valid:
                    if self._was_invalid:
                        # 从失效→恢复，发一次通知
                        await self._notify_admin(
                            "✅ B站Cookie已恢复", f"用户: {result.get('username')}"
                        )
                        self._was_invalid = False
                else:
                    if not self._was_invalid:
                        # 从有效→失效，发一次通知
                        await self._notify_admin(
                            "❌ B站Cookie已失效", f"错误: {result.get('error')}"
                        )
                        self._was_invalid = True
                    logger.warning(f"B站Cookie仍处于失效状态: {result.get('error')}")

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("B站Cookie监控出错")

            if self._monitor_running:
                await asyncio.sleep(pconfig.BILI_COOKIE_CHECK_INTERVAL)

    # ==================== 扫码轮询 ====================

    async def _poll_qr_login(self, sender_id: str, qrcode_key: str, qr_path: Path) -> None:
        """异步轮询扫码状态"""
        try:
            start_time = datetime.now()
            last_notified_status = None

            while True:
                elapsed = (datetime.now() - start_time).total_seconds()

                if elapsed >= QR_CODE_EXPIRE_TIME:
                    logger.info(f"用户 {sender_id} 的二维码已过期")
                    await self._notify_user(
                        sender_id,
                        "⏱️ 二维码已过期\n请重新发送 /bili_login 获取新二维码",
                    )
                    break

                if not self._http_session or self._http_session.closed:
                    break

                try:
                    async with self._http_session.get(
                        BILI_QR_POLL_URL,
                        params={"qrcode_key": qrcode_key},
                        headers=self._api_headers(),
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        poll_data = await resp.json()
                        set_cookie_headers = resp.headers.getall("Set-Cookie", [])
                except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                    logger.warning(f"轮询扫码状态失败: {e}")
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                code = poll_data.get("data", {}).get("code", -1)

                if code == QR_CODE_UNSCANNED:
                    pass

                elif code == QR_CODE_SCANNED:
                    if last_notified_status != QR_CODE_SCANNED:
                        await self._notify_user(
                            sender_id,
                            "✅ 已扫码\n请在手机上点击「确认登录」完成授权",
                        )
                        last_notified_status = QR_CODE_SCANNED

                elif code == QR_CODE_EXPIRED:
                    await self._notify_user(
                        sender_id,
                        "⏱️ 二维码已过期\n请重新发送 /bili_login 获取新二维码",
                    )
                    break

                elif code == QR_CODE_SUCCESS:
                    logger.info(f"用户 {sender_id} 扫码登录成功")
                    await self._on_login_success(sender_id, set_cookie_headers)
                    break

                else:
                    logger.warning(f"未知扫码状态码: {code}")

                await asyncio.sleep(POLL_INTERVAL)

        except asyncio.CancelledError:
            logger.info(f"用户 {sender_id} 的扫码轮询被取消")
        except Exception:
            logger.exception(f"扫码轮询出错 (用户: {sender_id})")
        finally:
            if sender_id in self._login_tasks:
                del self._login_tasks[sender_id]
            if qr_path.exists():
                try:
                    qr_path.unlink()
                except Exception:
                    pass

    async def _on_login_success(self, sender_id: str, set_cookie_headers: list) -> None:
        """扫码确认后：保存、应用、验证 Cookie 并通知用户。"""
        # 从Set-Cookie头提取cookie
        cookie_dict = {}
        for header in set_cookie_headers:
            cookie_part = header.split(";")[0].strip()
            if "=" in cookie_part:
                name, value = cookie_part.split("=", 1)
                cookie_dict[name.strip()] = value.strip()

        if not cookie_dict:
            await self._notify_error_user(
                sender_id, "❌ 登录成功但未获取到Cookie，请重试"
            )
            return

        cookie_str = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())

        # 更新状态
        async with self._cookie_lock:
            self._cookie = cookie_str

        # 持久化保存
        await self._save_cookie(cookie_str)

        # 立即应用到BilibiliParser
        self.apply_cookie_to_parser(cookie_str)

        # 如果监控未启动，启动监控
        if not self._monitor_running:
            self.start_monitor()

        # 验证cookie
        result = await self.check_cookie_valid()
        self._last_status = result
        self._last_check_time = datetime.now()
        await self._save_last_status()

        if result["valid"]:
            await self._notify_user(
                sender_id,
                f"🎉 登录成功，B站Cookie已生效并自动应用！\n"
                f"👤 用户: {result.get('username', '未知')}\n"
                f"🆔 UID: {result.get('uid', 0)}\n"
                f"{'👑 大会员' if result.get('vip') else '🐟 普通用户'}\n"
                f"{'🚀 监控已自动启动' if self._monitor_running else '⚠️ 监控未运行'}",
            )
            self._was_invalid = False
        else:
            await self._notify_error_user(
                sender_id,
                f"⚠️ Cookie已保存但验证失败: {result.get('error')}",
            )

    # ==================== 通知 ====================

    async def _notify_error_user(self, sender_id: str, message: str) -> None:
        """向扫码登录用户发送错误消息，受错误消息发送开关控制。"""
        if not get_config().SEND_ERROR_MESSAGES:
            return
        await self._notify_user(sender_id, message)

    async def _notify_user(self, sender_id: str, message: str) -> None:
        """向指定用户发送消息"""
        try:
            umo = sender_id if ":" in sender_id else f"default:FriendMessage:{sender_id}"
            await self.context.send_message(umo, MessageChain().message(message))
        except Exception as e:
            logger.error(f"发送消息给 {sender_id} 失败: {e}")

    async def _notify_admin(self, title: str, message: str) -> None:
        """向配置的通知目标QQ号发送Cookie状态通知（只发一次，不重复）"""
        pconfig = get_config()
        user_id = pconfig.BILI_NOTIFY_USER_ID
        if not user_id:
            logger.info(f"[B站Cookie监控] {title}: {message} (未配置通知目标，仅记录日志)")
            return
        try:
            umo = user_id if ":" in user_id else f"default:FriendMessage:{user_id}"
            await self.context.send_message(umo, MessageChain().message(f"{title}\n{message}"))
            logger.info(f"已发送B站Cookie通知到 {user_id}: {title}")
        except Exception as e:
            logger.error(f"发送B站Cookie通知失败: {e}")

    # ==================== 工具 ====================

    @staticmethod
    def _api_headers() -> dict:
        """获取B站API请求头"""
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.bilibili.com/",
            "Accept": "application/json, text/plain, */*",
        }

    @staticmethod
    def _build_qrcode_image(url: str):
        """生成二维码图片"""
        try:
            qr = qrcode.QRCode(
                version=None,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=10,
                border=4,
            )
            qr.add_data(url)
            qr.make(fit=True)
            return qr.make_image(fill_color="black", back_color="white")
        except Exception as e:
            logger.error(f"生成二维码失败: {e}")
            return None

    # ==================== 持久化 ====================

    async def _load_last_status(self) -> None:
        """加载上次Cookie检测状态"""
        async with self._file_lock:
            try:
                if self._status_file.exists():
                    with open(self._status_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self._last_status = data.get("last_status")
                    self._was_invalid = data.get("was_invalid", False)
                    if data.get("last_check_time"):
                        self._last_check_time = datetime.fromisoformat(
                            data["last_check_time"]
                        )
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.error(f"加载B站Cookie状态失败: {e}")

    async def _save_last_status(self) -> None:
        """保存当前Cookie检测状态"""
        async with self._file_lock:
            try:
                os.makedirs(self.data_dir, exist_ok=True)
                data = {
                    "last_status": self._last_status,
                    "last_check_time": (
                        self._last_check_time.isoformat()
                        if self._last_check_time
                        else None
                    ),
                    "was_invalid": self._was_invalid,
                }
                with open(self._status_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except (IOError, OSError) as e:
                logger.error(f"保存B站Cookie状态失败: {e}")

    async def _load_cookie(self) -> None:
        """从持久化存储中加载Cookie（优先），其次从配置加载"""
        # 先尝试从持久化文件加载
        try:
            if self._cookie_file.exists():
                with open(self._cookie_file, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
                saved = config_data.get("cookie", "")
                if saved:
                    decrypted = self._decrypt_cookie(saved)
                    if decrypted:
                        self._cookie = decrypted
                        logger.info("已从持久化存储加载B站Cookie")
                        return
                    logger.warning("B站Cookie解密失败")
        except (IOError, OSError, json.JSONDecodeError) as e:
            logger.error(f"加载持久化Cookie失败: {e}")

        # 再从配置加载
        pconfig = get_config()
        if pconfig.BILI_CK:
            self._cookie = pconfig.BILI_CK
            logger.info("已从插件配置加载B站Cookie")

    async def _save_cookie(self, cookie_str: str) -> None:
        """加密持久化保存Cookie"""
        if not cookie_str:
            return
        try:
            config_data: dict[str, Any] = {}
            if self._cookie_file.exists():
                with open(self._cookie_file, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
            config_data["cookie"] = self._encrypt_cookie(cookie_str)
            config_data["timestamp"] = datetime.now().isoformat()
            os.makedirs(self.data_dir, exist_ok=True)
            with open(self._cookie_file, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
            logger.info("B站Cookie已加密保存")
        except (IOError, OSError, json.JSONDecodeError) as e:
            logger.error(f"保存B站Cookie失败: {e}")

    def _get_fernet(self) -> Fernet:
        """获取或生成加密密钥"""
        os.makedirs(self.data_dir, exist_ok=True)
        if self._key_file.exists():
            key = self._key_file.read_bytes()
            return Fernet(key)
        key = Fernet.generate_key()
        self._key_file.write_bytes(key)
        try:
            os.chmod(str(self._key_file), 0o600)
        except (OSError, NotImplementedError):
            pass
        return Fernet(key)

    def _encrypt_cookie(self, cookie_str: str) -> str:
        """加密Cookie字符串"""
        if not cookie_str:
            return ""
        fernet = self._get_fernet()
        return fernet.encrypt(cookie_str.encode("utf-8")).decode("utf-8")

    def _decrypt_cookie(self, encrypted: str) -> str:
        """解密Cookie字符串"""
        if not encrypted:
            return ""
        try:
            fernet = self._get_fernet()
            return fernet.decrypt(encrypted.encode("utf-8")).decode("utf-8")
        except Exception:
            logger.error("B站Cookie解密失败，密钥可能已变更，请重新扫码登录")
            return ""
