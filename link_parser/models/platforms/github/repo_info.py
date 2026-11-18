"""GitHub REST API ``/repos/{owner}/{repo}`` 返回结构（只取需要的字段）。"""

from datetime import datetime

from msgspec import Struct
from msgspec.json import Decoder


class RepoOwner(Struct):
    login: str
    avatar_url: str | None = None


class RepoLicense(Struct):
    spdx_id: str | None = None
    name: str | None = None


class RepoInfo(Struct, kw_only=True):
    full_name: str
    html_url: str
    description: str | None = None
    stargazers_count: int = 0
    forks_count: int = 0
    open_issues_count: int = 0
    subscribers_count: int = 0
    language: str | None = None
    topics: list[str] = []
    license: RepoLicense | None = None
    pushed_at: str | None = None
    owner: RepoOwner

    @property
    def pushed_timestamp(self) -> int | None:
        """最近一次 push 的 ISO 8601 时间转秒级时间戳，解析失败返回 None。"""
        if not self.pushed_at:
            return None
        try:
            # Python 3.10 的 fromisoformat 不认 'Z'，统一替换成 +00:00
            dt = datetime.fromisoformat(self.pushed_at.replace("Z", "+00:00"))
            return int(dt.timestamp())
        except ValueError:
            return None

    @property
    def license_label(self) -> str | None:
        if self.license is None:
            return None
        return self.license.spdx_id or self.license.name


decoder: Decoder[RepoInfo] = Decoder(RepoInfo)
