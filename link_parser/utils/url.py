"""URL 工具：从消息文本中取出链接、做稳定归一化。

这里只处理「与内容无关」的差异（跟踪参数、fragment、大小写、尾斜杠），
用于在适配器拿不到明确内容 ID 时兜底生成缓存键。
能拿到平台内容 ID 的场景一律优先用 ID（见 ``BaseParser.cache_identity``）。
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

#: 与内容无关的分享 / 跟踪参数，参与缓存键前剔除
TRACKING_PARAMS: frozenset[str] = frozenset(
    {
        # 通用投放 / 统计
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "spm_id_from",
        "vd_source",
        "from_source",
        "referer",
        "referrer",
        "unique_k",
        "share_uid",
        "share_source",
        "share_medium",
        "share_plat",
        "share_token",
        "share_tag",
        "share_times",
        "s_trans",
        "wxsharehd",
        "wxfid",
        "timestamp",
        "_t",
        # 抖音 / 快手
        "tt_from",
        "is_from_webapp",
        "sender_device",
        "web_id",
        "sec_user_id",
        "is_copy_url",
        "is_ssr",
        "shareToken",
        "shareObjectId",
        "shareMethod",
        "shareId",
        "shareTokenStr",
        # 小红书
        "xsec_source",
        "xsec_token",
        "appuid",
        "apptime",
        "share_from_user_hidden",
        "author_share",
        "xhsshare",
        "ignoreEngage",
        "app_platform",
        # B站
        "buvid",
        "up_id",
        "spm_id",
        "share_medium_f",
        "share_plat_f",
        "share_session_id",
        "share_tag_f",
        "unique_k_f",
    }
)

_URL_RE = re.compile(r"https?://[^\s'\"<>]+")

#: 归一化结果超过该长度时改用摘要，避免缓存键过长
_MAX_KEY_LEN = 256


def extract_first_url(text: str) -> str | None:
    """取文本中的第一个 http(s) 链接，没有则返回 ``None``。"""
    if not text:
        return None
    matched = _URL_RE.search(text)
    return matched.group(0).rstrip(".,!?;:)'\"】」》）") if matched else None


def normalize_url(url: str) -> str:
    """把 URL 归一化为稳定字符串。

    规则：scheme / host 小写、去掉 fragment、剔除 :data:`TRACKING_PARAMS` 中的参数、
    其余 query 排序、路径去掉尾斜杠。无法解析时返回原串。
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw

    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() not in TRACKING_PARAMS
        )
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def stable_key(value: str) -> str:
    """把可能很长的归一化结果压缩成定长键（超长才摘要）。"""
    if len(value) <= _MAX_KEY_LEN:
        return value
    return hashlib.md5(value.encode("utf-8")).hexdigest()


__all__ = ["TRACKING_PARAMS", "extract_first_url", "normalize_url", "stable_key"]
