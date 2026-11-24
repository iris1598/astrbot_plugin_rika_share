"""分群 / 分会话稀疏配置覆写管理与持久化。

仅允许覆写 :data:`~link_parser.config.schema.GROUP_OVERRIDABLE_KEYS` 中定义的
零重解析代价项；未覆写字段一律继承全局配置。
"""

from __future__ import annotations

import fnmatch
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .schema import _ITEM_BY_KEY, coerce_value, is_group_overridable

_FILE_NAME = "group_configs.json"
_SEEN_MAX = 512


def normalize_scope_id(raw: str | None) -> str:
    """规范化分群作用域标识。

    - ``""`` / ``"global"`` → ``""``（代表全局配置）；
    - 不含 ``":"`` 的纯群号 / ID → ``"group:<id>"``；
    - 完整 ``umo``（``platform:type:session``）或通配规则原样保留。
    """
    text = str(raw or "").strip()
    if not text or text.lower() == "global":
        return ""
    if ":" not in text:
        return f"group:{text}"
    return text


def _extract_group_id(umo: str | None, group_id: str | None = None) -> str:
    gid = str(group_id or "").strip()
    if gid:
        return gid
    raw = str(umo or "").strip()
    parts = raw.split(":", 2)
    if len(parts) == 3 and "group" in parts[1].lower():
        return parts[2].strip()
    return ""


def _split_umo_or_none(raw: str) -> tuple[str, str, str] | None:
    parts = raw.split(":", 2)
    if len(parts) != 3:
        return None
    return parts[0], parts[1], parts[2]


def _match_wildcard_umo(pattern: str, umo: str) -> bool:
    pat_parts = _split_umo_or_none(pattern)
    umo_parts = _split_umo_or_none(umo)
    if pat_parts is None or umo_parts is None:
        return False
    return all(
        p == "" or fnmatch.fnmatchcase(target, p)
        for p, target in zip(pat_parts, umo_parts)
    )


class GroupConfigManager:
    """管理按群组 / 会话 UMO 的稀疏配置覆写与近期活跃群目录。"""

    def __init__(self, config_dir: Path):
        self.config_dir = Path(config_dir)
        self.file_path = self.config_dir / _FILE_NAME
        self._lock = threading.RLock()
        self._groups: dict[str, dict[str, Any]] = {}
        self._seen: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        """从磁盘加载分群配置并做白名单/类型校验。"""
        with self._lock:
            self._groups = {}
            if not self.file_path.exists():
                return
            try:
                raw = json.loads(self.file_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                from astrbot.api import logger

                logger.warning(
                    f"[link_parser] 读取分群配置 {self.file_path} 失败，已使用空配置",
                    exc_info=True,
                )
                return

            entries = raw.get("groups") if isinstance(raw, dict) else None
            if not isinstance(entries, dict):
                return

            for raw_scope, node in entries.items():
                scope_id = normalize_scope_id(raw_scope)
                if not scope_id or not isinstance(node, dict):
                    continue
                raw_overrides = node.get("overrides")
                if not isinstance(raw_overrides, dict):
                    continue
                cleaned: dict[str, Any] = {}
                for k, v in raw_overrides.items():
                    if not is_group_overridable(k):
                        continue
                    item = _ITEM_BY_KEY.get(k)
                    if item is None:
                        continue
                    coerced, err = coerce_value(item, v)
                    if err is None:
                        cleaned[k] = coerced
                label = str(node.get("label") or "").strip()[:48]
                if not cleaned and not label:
                    continue
                self._groups[scope_id] = {
                    "label": label,
                    "overrides": cleaned,
                    "updated_at": str(node.get("updated_at") or ""),
                }

    def _save_locked(self) -> bool:
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            payload = {"version": 1, "groups": self._groups}
            data = json.dumps(payload, ensure_ascii=False, indent=2)
            tmp = self.file_path.with_name(f".{self.file_path.name}.{os.getpid()}.tmp")
            tmp.write_text(data, encoding="utf-8")
            tmp.replace(self.file_path)
            return True
        except OSError:
            from astrbot.api import logger

            logger.exception("[link_parser] 写入分群配置失败")
            return False

    # ==================== 运行期读取 ==================== #

    def resolve_overrides(
        self,
        umo: str | None,
        group_id: str | None = None,
    ) -> tuple[str | None, dict[str, Any]]:
        """解析 ``(匹配到的作用域, 生效覆写字典)``。"""
        raw_umo = str(umo or "").strip()
        gid = _extract_group_id(raw_umo, group_id)

        with self._lock:
            if raw_umo and raw_umo in self._groups:
                return raw_umo, dict(self._groups[raw_umo]["overrides"])

            if gid:
                gid_scope = f"group:{gid}"
                if gid_scope in self._groups:
                    return gid_scope, dict(self._groups[gid_scope]["overrides"])

            if raw_umo:
                for scope_id, node in self._groups.items():
                    if "*" in scope_id and _match_wildcard_umo(scope_id, raw_umo):
                        return scope_id, dict(node["overrides"])

        return None, {}

    # ==================== WebUI 管理接口 ==================== #

    def list_profiles(self) -> list[dict[str, Any]]:
        """返回全部已配置的分群条目列表。"""
        with self._lock:
            items = []
            for scope_id, node in sorted(self._groups.items()):
                overrides = dict(node.get("overrides") or {})
                items.append(
                    {
                        "scope_id": scope_id,
                        "label": node.get("label") or "",
                        "override_keys": sorted(overrides),
                        "override_count": len(overrides),
                        "overrides": overrides,
                        "updated_at": node.get("updated_at") or "",
                    }
                )
            return items

    def get_profile(self, scope_id: str) -> dict[str, Any]:
        """获取单个分群的覆写配置（不存在时返回空覆写视图）。"""
        sid = normalize_scope_id(scope_id)
        if not sid:
            return {
                "scope_id": "",
                "label": "全局默认",
                "override_keys": [],
                "overrides": {},
                "updated_at": "",
            }
        with self._lock:
            node = self._groups.get(sid)
            if not node:
                return {
                    "scope_id": sid,
                    "label": "",
                    "override_keys": [],
                    "overrides": {},
                    "updated_at": "",
                }
            overrides = dict(node.get("overrides") or {})
            return {
                "scope_id": sid,
                "label": node.get("label") or "",
                "override_keys": sorted(overrides),
                "overrides": overrides,
                "updated_at": node.get("updated_at") or "",
            }

    def upsert_overrides(
        self,
        scope_id: str,
        updates: dict[str, Any] | None = None,
        *,
        unset: list[str] | None = None,
        label: str | None = None,
    ) -> tuple[list[str], list[str], dict[str, Any]]:
        """更新/取消指定分群的配置覆写，返回 ``(changed_keys, errors, current_overrides)``。"""
        sid = normalize_scope_id(scope_id)
        if not sid:
            return [], ["缺少有效的群组标识（UMO 或群号）"], {}

        changed: list[str] = []
        errors: list[str] = []

        with self._lock:
            node = self._groups.setdefault(
                sid, {"label": "", "overrides": {}, "updated_at": ""}
            )
            overrides: dict[str, Any] = node["overrides"]

            if label is not None:
                clean_label = str(label).strip()[:48]
                if clean_label != node.get("label", ""):
                    node["label"] = clean_label
                    changed.append("__label__")

            for key in unset or ():
                if key in overrides:
                    del overrides[key]
                    changed.append(key)

            for key, raw in (updates or {}).items():
                if not is_group_overridable(key):
                    errors.append(f"该项属于全局共享或需重新解析缓存的配置，不支持分群覆写：{key}")
                    continue
                item = _ITEM_BY_KEY.get(key)
                if item is None:
                    errors.append(f"未知配置项：{key}")
                    continue
                val, err = coerce_value(item, raw)
                if err is not None:
                    errors.append(err)
                    continue
                if key not in overrides or overrides[key] != val:
                    overrides[key] = val
                    changed.append(key)

            if changed:
                node["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if not node["overrides"] and not node["label"]:
                    self._groups.pop(sid, None)
                if not self._save_locked():
                    errors.append("分群配置已生效但写入磁盘失败")

            current = dict(self._groups.get(sid, {}).get("overrides") or {})

        return changed, errors, current

    def delete_profile(self, scope_id: str) -> bool:
        """清空并移除指定分群全部自定义覆写。"""
        sid = normalize_scope_id(scope_id)
        if not sid:
            return False
        with self._lock:
            if sid not in self._groups:
                return False
            self._groups.pop(sid, None)
            self._save_locked()
            return True

    # ==================== 近期活跃群感知 ==================== #

    def record_seen_group(
        self,
        umo: str,
        *,
        group_id: str = "",
        platform_id: str = "",
        name: str = "",
    ) -> None:
        """在内存中轻量化记录经过插件的消息来源（零磁盘 IO / 零阻塞）。"""
        raw_umo = str(umo or "").strip()
        if not raw_umo:
            return
        parts = _split_umo_or_none(raw_umo)
        gid = str(group_id or "").strip()
        pid = str(platform_id or "").strip()
        is_group = False
        if parts is not None:
            if not pid:
                pid = parts[0]
            if "group" in parts[1].lower():
                is_group = True
                if not gid:
                    gid = parts[2]
        elif gid:
            is_group = True

        if not is_group and not gid:
            return

        with self._lock:
            prev = self._seen.get(raw_umo, {})
            if len(self._seen) >= _SEEN_MAX and raw_umo not in self._seen:
                oldest = next(iter(self._seen))
                self._seen.pop(oldest, None)
            self._seen[raw_umo] = {
                "umo": raw_umo,
                "group_id": gid or prev.get("group_id", ""),
                "platform_id": pid or prev.get("platform_id", ""),
                "name": str(name or prev.get("name", "")).strip(),
                "last_seen": time.time(),
            }

    def list_seen_groups(self) -> list[dict[str, Any]]:
        """返回内存中记录的近期活跃群组。"""
        with self._lock:
            return sorted(
                (dict(v) for v in self._seen.values()),
                key=lambda item: item.get("last_seen", 0),
                reverse=True,
            )


__all__ = ["GroupConfigManager", "normalize_scope_id"]
